"""Pexels API stock footage downloader.

Downloads one unique clip per scene, using scene-specific b-roll keywords
for maximum visual variety.
"""
from __future__ import annotations

import logging
import os
import random
import uuid

import httpx

from app.config import settings
from app.models import ScriptSection

logger = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"


async def download_footage_for_sections(
    sections: list[ScriptSection],
) -> list[str]:
    """Download one stock video clip per script section.

    Uses each section's b_roll_keywords for targeted searches,
    ensuring visual variety across the entire video.
    """
    if not settings.pexels_api_key:
        raise RuntimeError("PEXELS_API_KEY not configured")

    downloaded: list[str] = []
    used_video_ids: set[int] = set()
    headers = {"Authorization": settings.pexels_api_key}

    async with httpx.AsyncClient(timeout=60.0) as client:
        for section in sections:
            queries = section.b_roll_keywords or [section.label.lower()]
            clip_path = await _find_and_download_clip(
                client, headers, queries, used_video_ids
            )
            if clip_path:
                downloaded.append(clip_path)
            else:
                # Fallback: use a generic tech query
                clip_path = await _find_and_download_clip(
                    client, headers, ["technology office modern"], used_video_ids
                )
                if clip_path:
                    downloaded.append(clip_path)

    if not downloaded:
        raise RuntimeError("No stock footage found for any section")

    logger.info("Downloaded %d unique clips for %d sections", len(downloaded), len(sections))
    return downloaded


async def _find_and_download_clip(
    client: httpx.AsyncClient,
    headers: dict,
    queries: list[str],
    used_ids: set[int],
) -> str | None:
    """Search Pexels and download one clip not already used."""
    for query in queries:
        try:
            response = await client.get(
                PEXELS_VIDEO_SEARCH,
                headers=headers,
                params={
                    "query": query,
                    "per_page": 10,
                    "size": "medium",
                    "orientation": "landscape",
                },
            )
            response.raise_for_status()
            data = response.json()

            # Shuffle to avoid always picking the first result
            videos = data.get("videos", [])
            random.shuffle(videos)

            for video in videos:
                vid_id = video.get("id")
                if vid_id in used_ids:
                    continue

                video_file = _pick_best_file(video.get("video_files", []))
                if not video_file:
                    continue

                file_path = await _download_file(client, video_file["link"])
                used_ids.add(vid_id)
                logger.info("Downloaded clip for '%s': %s", query, file_path)
                return file_path
        except Exception as e:
            logger.warning("Failed to fetch clip for '%s': %s", query, e)
            continue

    return None


def _pick_best_file(video_files: list[dict]) -> dict | None:
    """Select the best quality HD file (prefer 1920x1080, fallback to largest)."""
    hd_files = [f for f in video_files if f.get("width", 0) >= 1280]
    if not hd_files:
        hd_files = video_files

    if not hd_files:
        return None

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
