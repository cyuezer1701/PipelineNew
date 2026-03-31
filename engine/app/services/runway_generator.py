"""Runway Gen-4.5 API integration for AI-generated cinematic footage.

Generates consistent character footage using text-to-video with
cinematographic lens data enrichment and character references.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

import httpx

from app.config import settings
from app.models import Scene, ShotType

logger = logging.getLogger(__name__)

RUNWAY_API_BASE = "https://api.dev.runwayml.com/v1"

# Cinematic lens enrichments per shot type
SHOT_ENRICHMENTS = {
    ShotType.ESTABLISHING: "Wide establishing shot, 24mm lens, f/8, deep focus, cinematic lighting, 4K film grain",
    ShotType.CLOSE_UP: "Tight close-up, 85mm lens, f/1.8, shallow depth of field, dramatic rim lighting",
    ShotType.WIDE: "Wide angle, 16mm lens, f/5.6, full environment visible, natural ambient lighting",
    ShotType.MEDIUM: "Medium shot, 50mm lens, f/2.8, waist-up framing, soft key light, film look",
    ShotType.DETAIL: "Extreme close-up, 100mm macro, f/2.0, selective focus, product beauty lighting",
    ShotType.OVER_SHOULDER: "Over-the-shoulder POV, 35mm lens, f/2.0, shallow DOF, motivated lighting",
}


async def generate_runway_footage(
    scenes: list[Scene],
    character_ref: str | None = None,
) -> dict[int, str]:
    """Generate AI footage for scenes via Runway Gen-4.5.

    Returns: {scene_id: local_video_path} for successfully generated scenes.
    """
    if not settings.runway_api_key:
        raise RuntimeError("RUNWAY_API_KEY not configured")

    results: dict[int, str] = {}
    headers = {
        "Authorization": f"Bearer {settings.runway_api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }

    async with httpx.AsyncClient(timeout=300.0, headers=headers) as client:
        # Generate footage concurrently (max 3 at a time to respect rate limits)
        semaphore = asyncio.Semaphore(3)

        async def _generate_with_limit(scene: Scene) -> tuple[int, str | None]:
            async with semaphore:
                try:
                    path = await _generate_single_shot(
                        client=client,
                        visual_prompt=scene.visual_prompt,
                        shot_type=scene.shot_type,
                        duration=min(scene.duration, 10),  # Runway max ~10s
                        character_ref=character_ref,
                    )
                    return scene.scene_id, path
                except Exception as e:
                    logger.warning("Runway generation failed for scene %d: %s", scene.scene_id, e)
                    return scene.scene_id, None

        tasks = [_generate_with_limit(scene) for scene in scenes]
        completed = await asyncio.gather(*tasks)

        for scene_id, path in completed:
            if path:
                results[scene_id] = path

    logger.info("Runway generated %d/%d scenes", len(results), len(scenes))
    return results


async def _generate_single_shot(
    client: httpx.AsyncClient,
    visual_prompt: str,
    shot_type: ShotType,
    duration: float,
    character_ref: str | None = None,
) -> str:
    """Call Runway API for a single shot, poll until complete, download result."""

    # Enrich prompt with cinematic lens data
    enrichment = SHOT_ENRICHMENTS.get(shot_type, SHOT_ENRICHMENTS[ShotType.MEDIUM])
    full_prompt = f"{visual_prompt}. {enrichment}"

    # Build request body
    body: dict = {
        "model": "gen4.5",
        "promptText": full_prompt,
        "duration": max(5, int(duration)),
        "ratio": "1280:720",
    }

    if character_ref:
        body["referenceImages"] = [{"uri": character_ref, "tag": "@character"}]
        body["promptText"] = f"@character {full_prompt}"

    # Submit generation task
    response = await client.post(f"{RUNWAY_API_BASE}/text_to_video", json=body)
    response.raise_for_status()
    task_id = response.json()["id"]

    logger.info("Runway task submitted: %s", task_id)

    # Poll for completion (max 10 minutes — Gen-4.5 is slower)
    for _ in range(120):
        await asyncio.sleep(5)
        status_resp = await client.get(f"{RUNWAY_API_BASE}/tasks/{task_id}")
        status_resp.raise_for_status()
        task_data = status_resp.json()

        status = task_data.get("status", "")
        if status == "SUCCEEDED":
            output_url = task_data["output"][0]
            return await _download_video(client, output_url)
        elif status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Runway task {task_id} {status}: {task_data.get('error', '')}")

    raise RuntimeError(f"Runway task {task_id} timed out after 10 minutes")


async def _download_video(client: httpx.AsyncClient, url: str) -> str:
    """Download generated video to local output directory."""
    output_path = os.path.join(settings.output_dir, f"runway_{uuid.uuid4().hex[:8]}.mp4")

    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                f.write(chunk)

    logger.info("Runway video downloaded: %s", output_path)
    return output_path
