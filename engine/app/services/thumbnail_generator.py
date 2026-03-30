"""Thumbnail generation — extract frame + add bold text overlay."""
from __future__ import annotations

import asyncio
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


async def generate_thumbnail(
    video_path: str,
    text: str,
    output_path: str | None = None,
) -> str:
    """Extract a frame from the middle of the video and add bold text overlay."""
    if not output_path:
        base = os.path.splitext(video_path)[0]
        output_path = f"{base}_thumb.jpg"

    # Get video duration
    duration = await _get_duration(video_path)
    seek_time = duration / 2  # middle of video

    escaped_text = (
        text.upper()
        .replace("'", "\u2019")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )

    # Extract frame + add text overlay in one pass
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", video_path,
        "-vframes", "1",
        "-vf", (
            f"scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
            f"eq=contrast=1.3:saturation=1.3:brightness=0.05,"
            f"drawtext=fontfile={FONT_PATH}"
            f":text='{escaped_text}'"
            f":fontsize=72"
            f":fontcolor=white"
            f":borderw=5"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=(h-th)/2"
            f":box=1"
            f":boxcolor=black@0.5"
            f":boxborderw=20"
        ),
        "-q:v", "2",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
        raise RuntimeError(f"Thumbnail generation failed: {error_msg}")

    logger.info("Thumbnail generated: %s", output_path)
    return output_path


async def _get_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 45.0  # fallback
