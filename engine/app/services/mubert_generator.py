"""Mubert AI Music — generates unique royalty-free background music per video.

Uses the Mubert TTM (Text-to-Music) API to create a custom track matching
the video's mood. Falls back to local music files if API is unavailable.
"""
from __future__ import annotations

import glob
import logging
import os
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MUBERT_API_URL = "https://api.mubert.com/v2/RecordTrackTTM"

# Mood → Mubert prompt mapping
MOOD_PROMPTS = {
    "energetic": "upbeat electronic, motivational, fast tempo, corporate tech, modern",
    "chill": "lofi ambient, relaxed, soft piano, warm, calm background",
    "corporate": "corporate motivational, inspiring, light percussion, professional",
}


async def get_music_track(mood: str, duration: int) -> str | None:
    """Get a music track — Mubert API if available, local files as fallback."""
    if settings.mubert_api_key:
        try:
            path = await _generate_mubert_track(mood, duration)
            if path:
                return path
        except Exception as e:
            logger.warning("Mubert generation failed, falling back to local: %s", e)

    return _pick_local_music(mood)


async def _generate_mubert_track(mood: str, duration: int) -> str | None:
    """Generate a unique music track via Mubert TTM API."""
    prompt = MOOD_PROMPTS.get(mood, MOOD_PROMPTS["energetic"])

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Submit generation request
        response = await client.post(
            MUBERT_API_URL,
            json={
                "method": "RecordTrackTTM",
                "params": {
                    "pat": settings.mubert_api_key,
                    "duration": min(duration + 30, 300),  # Extra 30s for looping headroom
                    "tags": [],
                    "prompt": prompt,
                    "mode": "track",
                    "bitrate": 128,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != 1:
            logger.warning("Mubert API error: %s", data)
            return None

        tasks = data.get("data", {}).get("tasks", [])
        if not tasks:
            return None

        task_id = tasks[0].get("task_id")
        if not task_id:
            return None

        # Poll for completion
        download_url = await _poll_mubert_task(client, task_id)
        if not download_url:
            return None

        # Download the track
        output_path = os.path.join(settings.output_dir, f"music_{uuid.uuid4().hex[:8]}.mp3")
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

        logger.info("Mubert track generated: %s (mood: %s)", output_path, mood)
        return output_path


async def _poll_mubert_task(client: httpx.AsyncClient, task_id: str) -> str | None:
    """Poll Mubert API until track is ready. Returns download URL."""
    import asyncio

    for _ in range(30):  # Max 60 seconds
        await asyncio.sleep(2)

        response = await client.post(
            "https://api.mubert.com/v2/TrackStatus",
            json={
                "method": "TrackStatus",
                "params": {
                    "pat": settings.mubert_api_key,
                    "task_id": task_id,
                },
            },
        )
        data = response.json()

        if data.get("status") == 1:
            download_link = data.get("data", {}).get("tasks", [{}])[0].get("download_link")
            if download_link:
                return download_link

    logger.warning("Mubert task %s timed out", task_id)
    return None


def _pick_local_music(mood: str) -> str | None:
    """Fallback: pick a local music file from assets/music/."""
    music_dir = os.path.join(settings.assets_dir, "music")
    if not os.path.isdir(music_dir):
        return None

    import random

    for pattern in [f"{mood}.*", f"{mood}_*"]:
        matches = glob.glob(os.path.join(music_dir, pattern))
        if matches:
            return matches[0]

    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        matches = glob.glob(os.path.join(music_dir, ext))
        if matches:
            return random.choice(matches)

    return None
