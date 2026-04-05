"""
SpeedTube API: video metadata via yt-dlp and direct CDN URLs for playback.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

load_dotenv()

# --- Config (override via .env) ------------------------------------------------

DEFAULT_CORS_ORIGINS = "http://localhost:5173"
_cors_raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app = FastAPI(title="SpeedTube API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# --- Merged quality presets (label + yt-dlp format selector string) ------------

# Prefer merged video+audio; fall back to best single file at or below that height.
QUALITY_PRESETS: list[tuple[str, str]] = [
    ("1080p", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
    ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("480p", "bestvideo[height<=480]+bestaudio/best[height<=480]"),
    ("360p", "bestvideo[height<=360]+bestaudio/best[height<=360]"),
]


def merged_format_options() -> list[dict[str, str]]:
    """Fixed merged-quality options with human labels and yt-dlp format strings."""
    return [{"label": label, "format": selector} for label, selector in QUALITY_PRESETS]


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


def _extract_info(url: str, ydl_opts: dict[str, Any]) -> dict[str, Any]:
    with YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def fetch_video_info(url: str) -> dict[str, Any]:
    """Extract full info dict (title, thumbnails, duration)."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    return _extract_info(url, opts)


def _url_from_info(info: dict[str, Any]) -> str | None:
    """Single direct HTTP URL for HTML5 video, if yt-dlp exposes one."""
    if info.get("url"):
        return str(info["url"])
    return None


def resolve_stream_url(url: str, format_selector: str) -> str:
    """Resolve a direct CDN URL for the given yt-dlp format selector string."""
    opts: dict[str, Any] = {
        "format": format_selector,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    info = _extract_info(url, opts)
    direct = _url_from_info(info)
    if not direct:
        raise ValueError(
            "No direct stream URL for this format. Try another quality or a different video."
        )
    return direct


# --- API models ----------------------------------------------------------------


class VideoInfoRequest(BaseModel):
    url: str = Field(..., description="YouTube (or supported) video URL")


class VideoInfoResponse(BaseModel):
    title: str
    thumbnail_url: str | None
    duration: float | None
    formats: list[dict[str, str]] = Field(
        ...,
        description='Each item has "label" (e.g. 1080p) and "format" (yt-dlp selector string)',
    )


class StreamUrlResponse(BaseModel):
    stream_url: str


# --- Routes ---------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/video-info", response_model=VideoInfoResponse)
async def video_info(body: VideoInfoRequest) -> VideoInfoResponse:
    """
    Return metadata and merged quality options (label + format selector string).
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

    formats = merged_format_options()
    return VideoInfoResponse(
        title=title,
        thumbnail_url=thumb,
        duration=duration,
        formats=formats,
    )


@app.get("/api/stream", response_model=StreamUrlResponse)
async def stream(
    url: str = Query(..., description="Original video page URL"),
    format_selector: str = Query(
        ...,
        description="yt-dlp format selector string (same as in video-info)",
        alias="format",
    ),
) -> StreamUrlResponse:
    """
    Return the final direct CDN URL for this video and format selector.
    The browser should set the video element's src to this URL (no proxying).
    """
    try:
        stream_url = await asyncio.to_thread(resolve_stream_url, url, format_selector)
    except DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return StreamUrlResponse(stream_url=stream_url)
