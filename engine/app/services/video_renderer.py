"""FFmpeg-based video renderer with professional editing effects.

Features:
- Crossfade transitions between clips (0.5s)
- Ken Burns zoom effect on each clip
- Animated text overlays with semi-transparent background box
- Slide-in text animation
- Lower-third style section labels
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from app.config import settings
from app.models import ScriptSection

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CROSSFADE_DURATION = 0.5


async def render_video(
    footage_paths: list[str],
    audio_path: str,
    sections: list[ScriptSection],
    target_duration: int = 90,
) -> str:
    """Render a professional-looking video with transitions and text overlays."""
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    # Match clips to sections (1 clip per section, loop if fewer clips)
    matched_clips = _match_clips_to_sections(footage_paths, sections)

    # Build the full FFmpeg command in one pass
    await _render_full(matched_clips, audio_path, sections, output_path, target_duration)

    logger.info("Video rendered: %s", output_path)
    return output_path


def _match_clips_to_sections(
    clips: list[str], sections: list[ScriptSection]
) -> list[str]:
    """Ensure we have one clip per section, cycling if needed."""
    if not clips:
        raise RuntimeError("No footage clips provided")
    matched = []
    for i in range(len(sections)):
        matched.append(clips[i % len(clips)])
    return matched


async def _render_full(
    clips: list[str],
    audio_path: str,
    sections: list[ScriptSection],
    output_path: str,
    target_duration: int,
) -> None:
    """Single-pass render: trim clips per section, add zoom, crossfade, text overlays."""
    n = len(sections)
    inputs = []
    filter_parts = []

    # Step 1: Input each clip, trim to section duration, scale, apply Ken Burns zoom
    for i, (clip, section) in enumerate(zip(clips, sections)):
        dur = section.duration
        inputs.extend(["-i", clip])

        # Slow zoom in (Ken Burns) — zooms from 100% to 110% over the clip duration
        # Also scale and pad to 1080p
        filter_parts.append(
            f"[{i}:v]trim=0:{dur},setpts=PTS-STARTPTS,"
            f"scale=2048:1152:force_original_aspect_ratio=decrease,"
            f"pad=2048:1152:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"zoompan=z='1+0.1*on/({dur}*25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={dur}*25:s=1920x1080:fps=25,"
            f"setpts=PTS-STARTPTS"
            f"[v{i}];"
        )

    # Step 2: Crossfade transitions between consecutive clips
    if n == 1:
        filter_parts.append(f"[v0]copy[base];")
    else:
        # First crossfade: v0 x v1
        cf = CROSSFADE_DURATION
        filter_parts.append(
            f"[v0][v1]xfade=transition=fadeblack:duration={cf}"
            f":offset={sections[0].duration - cf}[xf1];"
        )
        # Chain remaining crossfades
        accumulated_duration = sections[0].duration + sections[1].duration - cf
        for i in range(2, n):
            prev = f"xf{i-1}"
            out = f"xf{i}" if i < n - 1 else "base"
            offset = accumulated_duration - cf
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition=fadeblack:duration={cf}"
                f":offset={offset}[{out}];"
            )
            accumulated_duration += sections[i].duration - cf

        if n == 2:
            # Rename xf1 to base
            filter_parts.append(f"[xf1]copy[base];")

    # Step 3: Text overlays with semi-transparent background and slide-in animation
    text_filters = _build_text_overlays(sections)
    if text_filters:
        filter_parts.append(f"[base]{text_filters}[outv]")
    else:
        filter_parts.append(f"[base]copy[outv]")

    filter_complex = "".join(filter_parts)

    # Add audio input
    inputs.extend(["-i", audio_path])
    audio_idx = n  # audio is the last input

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", f"{audio_idx}:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-t", str(target_duration),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]

    await _run_ffmpeg(cmd)


def _build_text_overlays(sections: list[ScriptSection]) -> str:
    """Build text overlay filters with background box and fade animation."""
    filters = []
    current_time = 0.0

    for section in sections:
        if not section.overlay_text:
            current_time += section.duration
            continue

        start = current_time
        end = current_time + section.duration
        fade_in = 0.4
        fade_out = 0.4

        escaped_text = _escape_ffmpeg_text(section.overlay_text)
        escaped_label = _escape_ffmpeg_text(section.label)

        # Main overlay text — centered, with dark background box
        filters.append(
            f"drawtext=fontfile={FONT_PATH}"
            f":text='{escaped_text}'"
            f":fontsize=52"
            f":fontcolor=white"
            f":box=1"
            f":boxcolor=black@0.65"
            f":boxborderw=18"
            f":x='if(lt(t-{start},{fade_in}),"
            f"(-text_w)+(w/2+text_w/2)*((t-{start})/{fade_in}),"
            f"(w-text_w)/2)'"
            f":y=h-th-100"
            f":enable='between(t,{start},{end})'"
            f":alpha='if(gt(t,{end - fade_out}),({end}-t)/{fade_out},1)'"
        )

        # Section label — small, upper left, like a lower-third tag
        filters.append(
            f"drawtext=fontfile={FONT_PATH}"
            f":text='{escaped_label}'"
            f":fontsize=24"
            f":fontcolor=white"
            f":box=1"
            f":boxcolor=0x0066FF@0.8"
            f":boxborderw=10"
            f":x=40"
            f":y=40"
            f":enable='between(t,{start},{start + min(3.0, section.duration - 0.5)})'"
            f":alpha='if(lt(t-{start},0.3),(t-{start})/0.3,1)'"
        )

        current_time += section.duration

    return ",".join(filters) if filters else ""


def _escape_ffmpeg_text(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\u2019")  # Replace with curly apostrophe
        .replace(":", "\\:")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


async def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an FFmpeg command asynchronously."""
    logger.info("Running FFmpeg with %d inputs...", sum(1 for c in cmd if c == "-i"))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-1000:] if stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed (exit {proc.returncode}): {error_msg}")
