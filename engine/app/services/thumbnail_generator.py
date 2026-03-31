"""Thumbnail generation — Ideogram AI or frame-extracted.

If Ideogram API key is configured, generates a custom YouTube thumbnail
with bold text rendered directly in the image (Ideogram is best at text-on-image).
Falls back to extracting a frame from the video with FFmpeg text overlay.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

IDEOGRAM_API_URL = "https://api.ideogram.ai/generate"


async def generate_thumbnail(
    video_path: str,
    text: str,
    topic: str = "",
    output_path: str | None = None,
) -> str:
    """Generate a YouTube thumbnail — Ideogram AI or frame-extracted."""
    if not output_path:
        base = os.path.splitext(video_path)[0]
        output_path = f"{base}_thumb.jpg"

    if settings.ideogram_api_key:
        try:
            return await _generate_ideogram_thumbnail(text, topic, output_path)
        except Exception as e:
            logger.warning("Ideogram thumbnail failed, falling back to frame extraction: %s", e)

    return await _extract_frame_thumbnail(video_path, text, output_path)


async def _generate_ideogram_thumbnail(text: str, topic: str, output_path: str) -> str:
    """Generate a thumbnail using Ideogram API (best at text-on-image)."""
    # Ideogram renders text directly into the image — perfect for thumbnails
    prompt = (
        f'YouTube thumbnail with large bold text "{text.upper()}" prominently displayed. '
        f"Topic: {topic}. "
        f"Eye-catching design with vibrant blue and orange color scheme. "
        f"Modern tech aesthetic, dramatic lighting, clean composition. "
        f"Abstract technology background with glowing elements, data visualization, "
        f"circuit patterns. The text must be huge, bold, and clearly readable. "
        f"Professional YouTube thumbnail style like MKBHD or Fireship. "
        f"16:9 aspect ratio, high contrast, cinematic."
    )

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            IDEOGRAM_API_URL,
            headers={
                "Api-Key": settings.ideogram_api_key,
                "Content-Type": "application/json",
            },
            json={
                "image_request": {
                    "prompt": prompt,
                    "aspect_ratio": "ASPECT_16_9",
                    "model": "V_2",
                    "magic_prompt_option": "AUTO",
                    "style_type": "REALISTIC",
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        # Get the image URL from response
        image_url = data["data"][0]["url"]

        # Download the generated image
        img_path = os.path.join(settings.output_dir, f"thumb_raw_{uuid.uuid4().hex[:8]}.png")
        async with client.stream("GET", image_url) as resp:
            resp.raise_for_status()
            with open(img_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

    # Scale to YouTube thumbnail size (1280x720)
    await _scale_thumbnail(img_path, output_path)
    _safe_remove(img_path)

    logger.info("Ideogram thumbnail generated: %s", output_path)
    return output_path


async def _scale_thumbnail(image_path: str, output_path: str) -> None:
    """Scale image to 1280x720 for YouTube."""
    cmd = [
        "ffmpeg", "-y", "-i", image_path,
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        "-q:v", "2",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def _extract_frame_thumbnail(video_path: str, text: str, output_path: str) -> str:
    """Fallback: extract frame from video middle + add text overlay."""
    duration = await _get_duration(video_path)
    seek_time = duration / 2

    escaped = (
        text.upper()
        .replace("'", "\u2019")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )

    cmd = [
        "ffmpeg", "-y", "-ss", str(seek_time), "-i", video_path,
        "-vframes", "1",
        "-vf", (
            f"scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
            f"eq=contrast=1.3:saturation=1.3:brightness=0.05,"
            f"drawbox=x=0:y=ih*0.55:w=iw:h=ih*0.45:color=black@0.45:t=fill,"
            f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=82:fontcolor=white"
            f":borderw=6:bordercolor=black"
            f":x=(w-text_w)/2:y=(h-th)/2+60"
        ),
        "-q:v", "2",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
        raise RuntimeError(f"Thumbnail generation failed: {error_msg}")

    logger.info("Frame thumbnail generated: %s", output_path)
    return output_path


async def _get_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 45.0


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
