"""
SpeedTube API: audio-only playback — yt-dlp resolves best audio; bytes proxied via httpx.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

load_dotenv()

DEFAULT_CORS_ORIGINS = "http://localhost:5173"
_cors_raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

STREAM_TIMEOUT = float(os.getenv("STREAM_TIMEOUT_SECONDS", "300"))
PROXY_CHUNK_BYTES = 512 * 1024

# Resolved CDN audio URL per page URL (YouTube URLs valid ~hours; refresh every 5 min)
_AUDIO_CDN_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300

_YDL_BASE_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

app = FastAPI(title="SpeedTube API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# --- yt-dlp ---------------------------------------------------------------------


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    if info.get("thumbnail"):
        return str(info["thumbnail"])
    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return None
    best = max(thumbs, key=lambda t: (t.get("width") or 0, t.get("height") or 0))
    return best.get("url")


def _extract_info(url: str, ydl_opts: dict[str, Any]) -> dict[str, Any]:
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_video_info(url: str) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    return _extract_info(url, opts)


def _url_from_info(info: dict[str, Any]) -> str | None:
    if info.get("url"):
        return str(info["url"])
    return None


def _pick_audio_url(info: dict[str, Any]) -> str | None:
    u = _url_from_info(info)
    if u:
        return u
    for f in info.get("requested_formats") or []:
        if not f.get("url"):
            continue
        acodec = f.get("acodec")
        if acodec not in (None, "none"):
            return str(f["url"])
    return None


def _extract_best_audio_cdn_url_sync(page_url: str) -> str:
    opts = {**_YDL_BASE_OPTS, "format": "bestaudio/best"}
    info = _extract_info(page_url, opts)
    cdn = _pick_audio_url(info)
    if not cdn:
        raise ValueError("Could not resolve an audio stream URL for this URL.")
    return cdn


def _cache_get_cdn_url(page_url: str) -> str | None:
    entry = _AUDIO_CDN_CACHE.get(page_url)
    if not entry:
        return None
    if time.monotonic() > entry["expires_at"]:
        del _AUDIO_CDN_CACHE[page_url]
        return None
    return str(entry["cdn_url"])


def _cache_set_cdn_url(page_url: str, cdn_url: str) -> None:
    _AUDIO_CDN_CACHE[page_url] = {
        "cdn_url": cdn_url,
        "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
    }


async def resolve_best_audio_cdn_url(page_url: str) -> str:
    """Return direct CDN URL for best audio, using 5-minute in-memory cache."""
    cached = _cache_get_cdn_url(page_url)
    if cached:
        return cached
    cdn = await asyncio.to_thread(_extract_best_audio_cdn_url_sync, page_url)
    _cache_set_cdn_url(page_url, cdn)
    return cdn


# --- API models ----------------------------------------------------------------


class VideoInfoRequest(BaseModel):
    url: str = Field(..., description="YouTube (or supported) page URL")


class VideoInfoResponse(BaseModel):
    title: str
    thumbnail_url: str | None
    duration: float | None


class StreamUrlsResponse(BaseModel):
    audio_url: str


# --- Proxy ----------------------------------------------------------------------


async def _proxy_audio_upstream(request: Request, page_url: str) -> StreamingResponse:
    client: httpx.AsyncClient | None = None
    try:
        cdn_url = await resolve_best_audio_cdn_url(page_url)

        range_header = request.headers.get("range")
        upstream_headers: dict[str, str] = {}
        if range_header:
            upstream_headers["Range"] = range_header

        timeout = httpx.Timeout(STREAM_TIMEOUT, connect=30.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

        try:
            req = client.build_request("GET", cdn_url, headers=upstream_headers)
            response = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            await client.aclose()
            client = None
            raise RuntimeError(f"Upstream request failed: {e}") from e

        if response.status_code >= 400:
            err_body = await response.aread()
            await response.aclose()
            await client.aclose()
            client = None
            raise RuntimeError(
                f"Upstream returned {response.status_code}: {err_body[:500]!r}"
            )

        passthrough: dict[str, str] = {
            "Content-Type": response.headers.get("content-type", "audio/mp4"),
            "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
            "Cache-Control": "no-store",
        }
        if "content-range" in response.headers:
            passthrough["Content-Range"] = response.headers["content-range"]
        if "content-length" in response.headers:
            passthrough["Content-Length"] = response.headers["content-length"]

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes(chunk_size=PROXY_CHUNK_BYTES):
                    yield chunk
            finally:
                await response.aclose()
                if client is not None:
                    await client.aclose()

        return StreamingResponse(
            body(),
            status_code=response.status_code,
            media_type=passthrough["Content-Type"],
            headers=passthrough,
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Proxy error (audio): {e}")
        if client is not None:
            await client.aclose()
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Routes ---------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/video-info", response_model=VideoInfoResponse)
async def video_info(body: VideoInfoRequest) -> VideoInfoResponse:
    """Return title, thumbnail, and duration only."""
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

    return VideoInfoResponse(
        title=title,
        thumbnail_url=thumb,
        duration=duration,
    )


@app.get("/api/stream", response_model=StreamUrlsResponse)
async def stream(request: Request, url: str = Query(..., description="Original page URL")):
    """
    Return same-origin proxy URL for best audio. Warms the CDN URL cache.
    """
    try:
        await resolve_best_audio_cdn_url(url)
        base = str(request.base_url).rstrip("/")
        q = urlencode({"url": url})
        return StreamUrlsResponse(audio_url=f"{base}/api/proxy/audio?{q}")
    except Exception as e:
        print(f"Stream error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/proxy/audio")
async def proxy_audio(
    request: Request,
    url: str = Query(..., description="Original YouTube (or supported) page URL"),
) -> StreamingResponse:
    """Proxy best-audio stream bytes with Range support."""
    return await _proxy_audio_upstream(request, url)
