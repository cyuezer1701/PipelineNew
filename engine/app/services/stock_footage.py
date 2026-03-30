"""Pexels API stock footage downloader."""
from __future__ import annotations

import logging
import os
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


async def download_footage(
    queries: list[str],
    target_duration: int = 60,
    per_clip: int = 15,
) -> list[str]:
    """Search and download stock videos from Pexels.

    Downloads enough clips to cover `target_duration` seconds,
    aiming for clips around `per_clip` seconds each.
    """
    if not settings.pexels_api_key:
        raise RuntimeError("PEXELS_API_KEY not configured")

    clips_needed = max(1, target_duration // per_clip)
    downloaded: list[str] = []

    headers = {"Authorization": settings.pexels_api_key}

    async with httpx.AsyncClient(timeout=60.0) as client:
        for query in queries:
            if len(downloaded) >= clips_needed:
                break

            response = await client.get(
                PEXELS_VIDEO_SEARCH,
                headers=headers,
                params={
                    "query": query,
                    "per_page": clips_needed - len(downloaded),
                    "size": "medium",
                    "orientation": "landscape",
                },
            )
            response.raise_for_status()
            data = response.json()

            for video in data.get("videos", []):
                if len(downloaded) >= clips_needed:
                    break

                # Pick the best HD file
                video_file = _pick_best_file(video.get("video_files", []))
                if not video_file:
                    continue

                file_path = await _download_file(client, video_file["link"])
                downloaded.append(file_path)
                logger.info("Downloaded clip: %s", file_path)

    if not downloaded:
        raise RuntimeError(f"No stock footage found for queries: {queries}")

    return downloaded


def _pick_best_file(video_files: list[dict]) -> dict | None:
    """Select the best quality HD file (prefer 1920x1080, fallback to largest)."""
    hd_files = [f for f in video_files if f.get("width", 0) >= 1280]
    if not hd_files:
        hd_files = video_files

    if not hd_files:
        return None

    # Prefer 1080p
    for f in hd_files:
        if f.get("width") == 1920 and f.get("height") == 1080:
            return f

    return max(hd_files, key=lambda f: f.get("width", 0))


async def _download_file(client: httpx.AsyncClient, url: str) -> str:
    """Download a video file to the output directory."""
    output_path = os.path.join(settings.output_dir, f"clip_{uuid.uuid4().hex[:8]}.mp4")

    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                f.write(chunk)

    return output_path
