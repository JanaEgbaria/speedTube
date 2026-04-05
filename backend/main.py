"""
SpeedTube API: video metadata via yt-dlp and proxied streaming with Range support.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

load_dotenv()

# --- Config (override via .env) ------------------------------------------------

DEFAULT_CORS_ORIGINS = "http://localhost:5173"
_cors_raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# Upstream read timeout for long streams (seconds)
STREAM_TIMEOUT = float(os.getenv("STREAM_TIMEOUT_SECONDS", "300"))

app = FastAPI(title="SpeedTube API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# --- yt-dlp helpers ------------------------------------------------------------


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    """Best thumbnail URL: top-level field or largest from thumbnails list."""
    if info.get("thumbnail"):
        return str(info["thumbnail"])
    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return None
    best = max(thumbs, key=lambda t: (t.get("width") or 0, t.get("height") or 0))
    return best.get("url")


def _build_format_options(info: dict[str, Any]) -> list[dict[str, str]]:
    """
    Build format choices with human-readable labels and yt-dlp format_id.
    Prefers muxed video+audio; includes video-only with a clear label if needed.
    """
    formats = info.get("formats") or []
    rows: list[tuple[int, dict[str, str]]] = []
    seen: set[str] = set()

    for f in formats:
        fid = f.get("format_id")
        if not fid or fid in seen:
            continue
        if not f.get("url"):
            continue
        vcodec = f.get("vcodec")
        if vcodec in (None, "none"):
            continue

        height = f.get("height")
        acodec = f.get("acodec")
        if acodec in (None, "none"):
            label = f"{height}p (no audio)" if height else f"{fid} (no audio)"
        else:
            label = f"{height}p" if height else (f.get("resolution") or str(fid))

        seen.add(fid)
        sort_h = height or 0
        rows.append((sort_h, {"label": label, "format_id": str(fid)}))

    # Highest resolution first
    rows.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in rows]


def _extract_info(url: str, ydl_opts: dict[str, Any]) -> dict[str, Any]:
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_video_info(url: str) -> dict[str, Any]:
    """Extract full info dict (title, thumbnails, duration, formats)."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    return _extract_info(url, opts)


def resolve_stream_url(url: str, format_id: str) -> str:
    """Resolve a direct HTTP URL for the requested format_id."""
    opts: dict[str, Any] = {
        "format": format_id,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    info = _extract_info(url, opts)
    direct = info.get("url")
    if not direct:
        raise ValueError(
            "No direct URL for this format. It may require merging or a different format_id."
        )
    return str(direct)


# --- API models ----------------------------------------------------------------


class VideoInfoRequest(BaseModel):
    url: str = Field(..., description="YouTube (or supported) video URL")


class VideoInfoResponse(BaseModel):
    title: str
    thumbnail_url: str | None
    duration: float | None
    formats: list[dict[str, str]]


# --- Routes ---------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/video-info", response_model=VideoInfoResponse)
async def video_info(body: VideoInfoRequest) -> VideoInfoResponse:
    """
    Return metadata and playable format options for the given URL.
    """
    try:
        info = await asyncio.to_thread(fetch_video_info, body.url)
    except DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    title = info.get("title") or "Unknown"
    thumb = _pick_thumbnail(info)
    duration = info.get("duration")
    if duration is not None:
        duration = float(duration)

    formats = _build_format_options(info)
    return VideoInfoResponse(
        title=title,
        thumbnail_url=thumb,
        duration=duration,
        formats=formats,
    )


@app.get("/api/stream")
async def stream(
    request: Request,
    url: str = Query(..., description="Original video page URL"),
    format_id: str = Query(..., description="yt-dlp format id to stream"),
) -> StreamingResponse:
    """
    Proxy the remote media with support for Range requests (seeking in HTML5 video).
    """
    try:
        stream_url = await asyncio.to_thread(resolve_stream_url, url, format_id)
    except DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    range_header = request.headers.get("range")
    upstream_headers: dict[str, str] = {}
    if range_header:
        upstream_headers["Range"] = range_header

    timeout = httpx.Timeout(STREAM_TIMEOUT, connect=30.0)
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    try:
        req = client.build_request("GET", stream_url, headers=upstream_headers)
        response = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {e}") from e

    if response.status_code >= 400:
        err_body = await response.aread()
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"Upstream returned {response.status_code}: {err_body[:500]!r}",
        )

    # Forward range-related headers; force video/mp4 for the player (typical progressive formats).
    passthrough: dict[str, str] = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
    }
    if "content-range" in response.headers:
        passthrough["Content-Range"] = response.headers["content-range"]
    if "content-length" in response.headers:
        passthrough["Content-Length"] = response.headers["content-length"]

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        media_type="video/mp4",
        headers=passthrough,
    )
