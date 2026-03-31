"""AI Sound Effects — generates and compiles a SFX track for the video.

Uses ElevenLabs Sound Generation API to create transition sounds (whoosh, pop, thud),
then builds a single SFX audio track with sounds placed at scene transition timestamps.
SFX are cached locally after first generation to save API costs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

import httpx

from app.config import settings
from app.models import Scene

logger = logging.getLogger(__name__)

# SFX definitions: name → prompt for ElevenLabs
SFX_LIBRARY = {
    "whoosh": "short cinematic whoosh transition sound, clean, modern",
    "thud": "deep subtle bass impact hit, low frequency thud, cinematic",
    "pop": "short bright pop notification sound, clean digital",
}

ELEVENLABS_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"


async def generate_sfx_track(
    scenes: list[Scene],
    target_duration: float,
) -> str | None:
    """Generate a single SFX audio track with sounds at transition points.

    Returns path to the SFX track MP3, or None if SFX generation is unavailable.
    """
    if not settings.elevenlabs_api_key:
        return None

    # Ensure we have cached SFX files
    sfx_dir = os.path.join(settings.assets_dir, "sfx")
    os.makedirs(sfx_dir, exist_ok=True)

    await _ensure_sfx_cached(sfx_dir)

    whoosh_path = os.path.join(sfx_dir, "whoosh.mp3")
    thud_path = os.path.join(sfx_dir, "thud.mp3")

    if not os.path.exists(whoosh_path):
        logger.warning("SFX files not available, skipping SFX track")
        return None

    # Build SFX placement timeline
    transition_times = _get_transition_times(scenes)

    if not transition_times:
        return None

    # Create SFX track: silent base + overlay sounds at transition points
    output_path = os.path.join(settings.output_dir, f"sfx_{uuid.uuid4().hex[:8]}.mp3")
    await _compile_sfx_track(transition_times, whoosh_path, thud_path, target_duration, output_path)

    logger.info("SFX track generated with %d sounds: %s", len(transition_times), output_path)
    return output_path


async def _ensure_sfx_cached(sfx_dir: str) -> None:
    """Generate and cache SFX files if they don't exist yet."""
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, prompt in SFX_LIBRARY.items():
            path = os.path.join(sfx_dir, f"{name}.mp3")
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                continue  # Already cached

            try:
                response = await client.post(
                    ELEVENLABS_SFX_URL,
                    headers=headers,
                    json={
                        "text": prompt,
                        "duration_seconds": 1.0,
                    },
                )
                if response.status_code == 200:
                    with open(path, "wb") as f:
                        f.write(response.content)
                    logger.info("Cached SFX: %s", name)
                else:
                    logger.warning("SFX generation failed for '%s': %d", name, response.status_code)
            except Exception as e:
                logger.warning("SFX generation error for '%s': %s", name, e)


def _get_transition_times(scenes: list[Scene]) -> list[float]:
    """Calculate timestamps where scene transitions happen.
    Limits to max 8 transitions to avoid FFmpeg amix input limits."""
    times = []
    current = 0.0
    for i, scene in enumerate(scenes):
        current += scene.duration
        if i < len(scenes) - 1:
            times.append(current)

    # Limit to max 8 SFX — pick evenly spaced transitions
    if len(times) > 8:
        step = len(times) / 8
        times = [times[int(i * step)] for i in range(8)]

    return times


async def _compile_sfx_track(
    transition_times: list[float],
    whoosh_path: str,
    thud_path: str,
    total_duration: float,
    output_path: str,
) -> None:
    """Create a single audio file with SFX placed at transition timestamps."""
    # Build FFmpeg filter: silent base + adelay'd SFX overlays
    # Each transition gets a whoosh slightly before the cut
    inputs = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}"]
    filter_parts = []
    mix_inputs = ["[0:a]"]
    input_count = 1  # silent base is input 0

    for i, t in enumerate(transition_times):
        sfx_file = whoosh_path if i % 2 == 0 else thud_path
        input_idx = input_count
        inputs.extend(["-i", sfx_file])
        input_count += 1

        delay_ms = max(0, int((t - 0.2) * 1000))
        filter_parts.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}[s{i}]")
        mix_inputs.append(f"[s{i}]")

    n_inputs = len(mix_inputs)
    filter_str = ";".join(filter_parts)
    if filter_str:
        filter_str += ";"
    filter_str += f"{''.join(mix_inputs)}amix=inputs={n_inputs}:duration=first:normalize=0[out]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-t", str(total_duration),
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
        logger.warning("SFX track compilation failed: %s", error_msg)
        raise RuntimeError(f"SFX compilation failed: {error_msg}")
