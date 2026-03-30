"""Professional video renderer with all viral-quality features.

Features:
- Ken Burns zoom with color grading on each clip
- Varied transitions (fade, slide, smooth, circlecrop)
- Word-by-word animated captions (Hormozi style)
- Background music with auto-ducking
- FlowStack intro/outro branding
- YouTube Shorts (9:16) support
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import random
import uuid

from app.config import settings
from app.models import ScriptSection, WordTimestamp

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CROSSFADE_DURATION = 0.4

# Transitions mapped to scene types
TRANSITION_MAP = {
    "HOOK": ["fade"],
    "PROBLEM": ["fadeblack", "smoothdown"],
    "STAT": ["circlecrop", "fade"],
    "STEP": ["slideright", "slideleft"],
    "DEMO": ["smoothup", "smoothdown"],
    "BENEFIT": ["fade", "circlecrop"],
    "TRANSITION": ["fadeblack"],
    "CTA": ["fade", "smoothup"],
}
DEFAULT_TRANSITIONS = ["fade", "fadeblack", "slideright", "slideleft", "smoothup"]


async def render_video(
    footage_paths: list[str],
    audio_path: str,
    sections: list[ScriptSection],
    target_duration: int = 90,
    captions: list[WordTimestamp] | None = None,
    music_mood: str = "energetic",
    video_format: str = "landscape",
) -> str:
    """Render a professional video with all effects."""
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    # Resolution based on format
    if video_format == "shorts":
        width, height = 1080, 1920
        font_size_caption = 64
        font_size_overlay = 60
    else:
        width, height = 1920, 1080
        font_size_caption = 52
        font_size_overlay = 52

    matched_clips = _match_clips_to_sections(footage_paths, sections)

    # Step 1: Render intro
    intro_path = os.path.join(settings.output_dir, f"intro_{job_id}.mp4")
    await _render_intro(intro_path, width, height)

    # Step 2: Render main content (clips + transitions + overlays + captions)
    main_path = os.path.join(settings.output_dir, f"main_{job_id}.mp4")
    await _render_main(
        matched_clips, sections, main_path,
        target_duration, width, height,
        font_size_overlay, captions, font_size_caption,
    )

    # Step 3: Render outro
    outro_path = os.path.join(settings.output_dir, f"outro_{job_id}.mp4")
    await _render_outro(outro_path, width, height)

    # Step 4: Concat intro + main + outro
    concat_path = os.path.join(settings.output_dir, f"concat_{job_id}.mp4")
    await _concat_segments([intro_path, main_path, outro_path], concat_path)

    # Step 5: Mix audio (voiceover + background music with ducking)
    music_path = _pick_music_track(music_mood)
    await _mix_audio(concat_path, audio_path, music_path, output_path, video_format)

    # Cleanup
    for p in [intro_path, main_path, outro_path, concat_path]:
        _safe_remove(p)

    logger.info("Video rendered: %s", output_path)
    return output_path


def _match_clips_to_sections(clips: list[str], sections: list[ScriptSection]) -> list[str]:
    if not clips:
        raise RuntimeError("No footage clips provided")
    return [clips[i % len(clips)] for i in range(len(sections))]


# ── Intro/Outro Branding ──────────────────────────────────

async def _render_intro(output_path: str, w: int, h: int) -> None:
    """3-second branded intro: channel name zooms in on black background."""
    name = _esc(settings.channel_name)
    tagline = _esc(settings.channel_tagline)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d=3:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "3",
        "-vf", (
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize='40+80*(t/3)':fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30"
            f":alpha='min(1,t/0.5)',"
            f"drawtext=fontfile={FONT_PATH}:text='{tagline}'"
            f":fontsize=28:fontcolor=0xAAAAFF"
            f":x=(w-text_w)/2:y=(h/2)+40"
            f":alpha='if(lt(t,0.8),0,min(1,(t-0.8)/0.5))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest",
        output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_outro(output_path: str, w: int, h: int) -> None:
    """5-second outro with subscribe CTA."""
    name = _esc(settings.channel_name)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d=5:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "5",
        "-vf", (
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=72:fontcolor=red"
            f":x=(w-text_w)/2:y=(h/2)-60"
            f":alpha='min(1,t/0.5)',"
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=48:fontcolor=white"
            f":x=(w-text_w)/2:y=(h/2)+40"
            f":alpha='if(lt(t,0.5),0,min(1,(t-0.5)/0.5))',"
            f"drawtext=fontfile={FONT_PATH}:text='Like & Share for more'"
            f":fontsize=28:fontcolor=0xAAAAAA"
            f":x=(w-text_w)/2:y=(h/2)+110"
            f":alpha='if(lt(t,1.0),0,min(1,(t-1.0)/0.5))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest",
        output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Main Content Rendering ─────────────────────────────────

async def _render_main(
    clips: list[str],
    sections: list[ScriptSection],
    output_path: str,
    target_duration: int,
    w: int, h: int,
    font_size_overlay: int,
    captions: list[WordTimestamp] | None,
    font_size_caption: int,
) -> None:
    """Render main video: clips with zoom, color grade, transitions, text overlays, captions."""
    n = len(sections)
    inputs = []
    filter_parts = []

    # Upscale resolution for zoompan source
    src_w, src_h = int(w * 1.1), int(h * 1.1)

    # Step 1: Process each clip (trim, scale, color grade, Ken Burns zoom)
    for i, (clip, section) in enumerate(zip(clips, sections)):
        dur = section.duration
        inputs.extend(["-i", clip])

        # Ken Burns: random direction per clip
        zoom_dir = random.choice(["center", "left", "right"])
        if zoom_dir == "center":
            zx = f"iw/2-(iw/zoom/2)"
            zy = f"ih/2-(ih/zoom/2)"
        elif zoom_dir == "left":
            zx = f"(iw/zoom/4)"
            zy = f"ih/2-(ih/zoom/2)"
        else:
            zx = f"iw-(iw/zoom)-(iw/zoom/4)"
            zy = f"ih/2-(ih/zoom/2)"

        filter_parts.append(
            f"[{i}:v]trim=0:{dur},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
            f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            # Color grading
            f"eq=brightness=0.04:contrast=1.1:saturation=1.2,"
            # Ken Burns zoom
            f"zoompan=z='1+0.08*on/({dur}*25)'"
            f":x='{zx}':y='{zy}'"
            f":d={dur}*25:s={w}x{h}:fps=25,"
            f"settb=AVTB,setpts=N/25/TB,fps=25"
            f"[v{i}];"
        )

    # Step 2: Crossfade transitions with variety
    if n == 1:
        filter_parts.append(f"[v0]copy[base];")
    elif n == 2:
        trans = _pick_transition(sections[1].label)
        cf = CROSSFADE_DURATION
        filter_parts.append(
            f"[v0][v1]xfade=transition={trans}:duration={cf}"
            f":offset={sections[0].duration - cf}[base];"
        )
    else:
        cf = CROSSFADE_DURATION
        trans = _pick_transition(sections[1].label)
        filter_parts.append(
            f"[v0][v1]xfade=transition={trans}:duration={cf}"
            f":offset={sections[0].duration - cf}[xf1];"
        )
        accumulated = sections[0].duration + sections[1].duration - cf
        for i in range(2, n):
            prev = f"xf{i-1}"
            out = f"xf{i}" if i < n - 1 else "base"
            offset = accumulated - cf
            trans = _pick_transition(sections[i].label)
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition={trans}:duration={cf}"
                f":offset={offset}[{out}];"
            )
            accumulated += sections[i].duration - cf

    # Step 3: Section overlay text (slide-in with box)
    overlay_filters = _build_section_overlays(sections, font_size_overlay, h)

    # Step 4: Word-by-word captions
    caption_filters = _build_caption_filters(captions, font_size_caption, h) if captions else ""

    all_text_filters = ",".join(f for f in [overlay_filters, caption_filters] if f)
    if all_text_filters:
        filter_parts.append(f"[base]{all_text_filters}[outv]")
    else:
        filter_parts.append("[base]copy[outv]")

    filter_complex = "".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Audio Mixing ───────────────────────────────────────────

async def _mix_audio(
    video_path: str,
    voiceover_path: str,
    music_path: str | None,
    output_path: str,
    video_format: str,
) -> None:
    """Mix voiceover + background music with auto-ducking onto the video."""
    if music_path and os.path.exists(music_path):
        vol = settings.music_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voiceover_path,
            "-i", music_path,
            "-filter_complex", (
                f"[2:a]volume={vol},aloop=loop=-1:size=2e+09[music];"
                f"[music]atrim=0:duration=300[musictrim];"
                f"[1:a][musictrim]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", voiceover_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    await _run_ffmpeg(cmd)


# ── Concat Segments ────────────────────────────────────────

async def _concat_segments(segments: list[str], output_path: str) -> None:
    """Concatenate intro + main + outro using concat demuxer."""
    list_path = output_path + ".txt"
    with open(list_path, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        output_path,
    ]
    await _run_ffmpeg(cmd)
    _safe_remove(list_path)


# ── Text Overlay Builders ──────────────────────────────────

def _build_section_overlays(
    sections: list[ScriptSection],
    font_size: int,
    video_height: int,
) -> str:
    """Section label tags (upper left) + overlay text (lower center, slide-in)."""
    filters = []
    current_time = 0.0

    for section in sections:
        start = current_time
        end = current_time + section.duration

        if section.overlay_text:
            escaped = _esc(section.overlay_text)
            fade_in = 0.4
            # Slide-in from left with background box
            filters.append(
                f"drawtext=fontfile={FONT_PATH}"
                f":text='{escaped}'"
                f":fontsize={font_size}"
                f":fontcolor=white"
                f":box=1:boxcolor=black@0.6:boxborderw=16"
                f":x='if(lt(t-{start},{fade_in}),"
                f"(-text_w)+(w/2+text_w/2)*((t-{start})/{fade_in}),"
                f"(w-text_w)/2)'"
                f":y={video_height}-th-100"
                f":enable='between(t,{start},{end})'"
                f":alpha='if(gt(t,{end-0.3}),({end}-t)/0.3,1)'"
            )

        # Section label tag (upper left, colored)
        label_colors = {
            "HOOK": "0xFF4444", "PROBLEM": "0xFF8800", "STAT": "0x00AAFF",
            "STEP": "0x00CC66", "DEMO": "0x9966FF", "BENEFIT": "0x00CC66",
            "CTA": "0xFF4444", "TRANSITION": "0x888888",
        }
        color = label_colors.get(section.label, "0x0066FF")
        escaped_label = _esc(section.label)
        label_dur = min(2.5, section.duration - 0.3)

        filters.append(
            f"drawtext=fontfile={FONT_PATH}"
            f":text='{escaped_label}'"
            f":fontsize=22"
            f":fontcolor=white"
            f":box=1:boxcolor={color}@0.85:boxborderw=8"
            f":x=30:y=30"
            f":enable='between(t,{start},{start + label_dur})'"
            f":alpha='if(lt(t-{start},0.2),(t-{start})/0.2,"
            f"if(gt(t,{start + label_dur - 0.2}),({start + label_dur}-t)/0.2,1))'"
        )

        current_time += section.duration

    return ",".join(filters) if filters else ""


def _build_caption_filters(
    words: list[WordTimestamp],
    font_size: int,
    video_height: int,
) -> str:
    """Word-by-word animated captions — shows words as they're spoken.

    Groups words into lines of ~5 words. Current word highlighted in yellow,
    previous words in white, upcoming words invisible.
    """
    if not words:
        return ""

    filters = []
    # Group into chunks of 4-5 words for readability
    chunk_size = 4
    chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]

    y_pos = video_height - font_size - 180  # Above the section overlay

    for chunk in chunks:
        chunk_start = chunk[0].start
        chunk_end = chunk[-1].end

        # Show each word with timing
        for j, word in enumerate(chunk):
            escaped = _esc(word.word)
            # Calculate x position (center the whole chunk)
            # Use fixed-width approximation for positioning
            words_before = " ".join(w.word for w in chunk[:j])
            words_before_esc = _esc(words_before + " ") if words_before else ""

            # Active word: yellow, bold
            filters.append(
                f"drawtext=fontfile={FONT_PATH}"
                f":text='{escaped}'"
                f":fontsize={font_size}"
                f":fontcolor=yellow"
                f":borderw=3:bordercolor=black"
                f":x=(w-text_w)/2"
                f":y={y_pos}"
                f":enable='between(t,{word.start},{word.end})'"
            )

            # After spoken: white (stays visible until chunk ends)
            if word.end < chunk_end:
                filters.append(
                    f"drawtext=fontfile={FONT_PATH}"
                    f":text='{escaped}'"
                    f":fontsize={font_size}"
                    f":fontcolor=white"
                    f":borderw=3:bordercolor=black"
                    f":x=(w-text_w)/2"
                    f":y={y_pos}"
                    f":enable='between(t,{word.end},{chunk_end})'"
                )

    return ",".join(filters) if filters else ""


# ── Helpers ────────────────────────────────────────────────

def _pick_transition(label: str) -> str:
    """Pick a transition style based on scene type."""
    options = TRANSITION_MAP.get(label, DEFAULT_TRANSITIONS)
    return random.choice(options)


def _pick_music_track(mood: str) -> str | None:
    """Find a music track matching the mood in assets/music/."""
    music_dir = os.path.join(settings.assets_dir, "music")
    if not os.path.isdir(music_dir):
        return None

    # Look for files matching mood name
    patterns = [
        os.path.join(music_dir, f"{mood}.*"),
        os.path.join(music_dir, f"{mood}_*"),
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]

    # Fallback: any music file
    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        matches = glob.glob(os.path.join(music_dir, ext))
        if matches:
            return random.choice(matches)

    return None


def _esc(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\u2019")
        .replace(":", "\\:")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


async def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an FFmpeg command asynchronously."""
    logger.info("Running FFmpeg: %s ...", " ".join(cmd[:8]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-1500:] if stderr else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed (exit {proc.returncode}): {error_msg}")


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
