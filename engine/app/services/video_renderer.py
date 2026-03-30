"""FFmpeg-based video renderer with dynamic text overlays."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from app.config import settings
from app.models import ScriptSection

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


async def render_video(
    footage_paths: list[str],
    audio_path: str,
    sections: list[ScriptSection],
    target_duration: int = 60,
) -> str:
    """Render a final video by compositing footage, audio, and text overlays.

    Pipeline:
    1. Concatenate + trim footage clips to fill target_duration
    2. Overlay voiceover audio
    3. Add dynamic text overlays per section (fade in/out)
    4. Output 1080p H.264 MP4
    """
    job_id = uuid.uuid4().hex[:8]
    concat_path = os.path.join(settings.output_dir, f"concat_{job_id}.mp4")
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    # Step 1: Concatenate clips and trim to target duration
    await _concat_clips(footage_paths, concat_path, target_duration)

    # Step 2: Composite audio + text overlays
    await _composite(concat_path, audio_path, sections, output_path, target_duration)

    # Cleanup intermediate file
    _safe_remove(concat_path)

    logger.info("Video rendered: %s", output_path)
    return output_path


async def _concat_clips(
    clip_paths: list[str],
    output_path: str,
    target_duration: int,
) -> None:
    """Concatenate clips, scaling to 1080p, and trim to target duration."""
    # Build concat filter
    inputs = []
    filter_parts = []
    for i, path in enumerate(clip_paths):
        inputs.extend(["-i", path])
        filter_parts.append(
            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
        )

    # Concat all scaled streams
    concat_inputs = "".join(f"[v{i}]" for i in range(len(clip_paths)))
    filter_parts.append(
        f"{concat_inputs}concat=n={len(clip_paths)}:v=1:a=0[outv]"
    )

    filter_complex = "".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-t", str(target_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    await _run_ffmpeg(cmd)


async def _composite(
    video_path: str,
    audio_path: str,
    sections: list[ScriptSection],
    output_path: str,
    target_duration: int,
) -> None:
    """Add audio track and text overlays to the video."""
    # Build drawtext filter chain for each section
    drawtext_filters = _build_drawtext_filters(sections)

    filter_complex = f"[0:v]{drawtext_filters}[outv]" if drawtext_filters else "[0:v]copy[outv]"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-t", str(target_duration),
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    await _run_ffmpeg(cmd)


def _build_drawtext_filters(sections: list[ScriptSection]) -> str:
    """Build FFmpeg drawtext filter chain with fade in/out for each section."""
    filters = []
    current_time = 0

    for section in sections:
        if not section.overlay_text:
            current_time += section.duration
            continue

        start = current_time
        end = current_time + section.duration
        fade_in_end = start + 0.5
        fade_out_start = end - 0.5

        # Escape special chars for FFmpeg drawtext
        escaped_text = (
            section.overlay_text
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace(":", "\\:")
            .replace("%", "\\%")
        )

        filters.append(
            f"drawtext=fontfile={FONT_PATH}"
            f":text='{escaped_text}'"
            f":fontsize=48"
            f":fontcolor=white"
            f":borderw=3"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=h-th-80"
            f":enable='between(t,{start},{end})'"
            f":alpha='if(lt(t,{fade_in_end}),(t-{start})/0.5,"
            f"if(gt(t,{fade_out_start}),({end}-t)/0.5,1))'"
        )

        current_time += section.duration

    return ",".join(filters) if filters else ""


async def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an FFmpeg command asynchronously."""
    logger.info("Running: %s", " ".join(cmd[:6]) + " ...")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-500:] if stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed (exit {proc.returncode}): {error_msg}")


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
