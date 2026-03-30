"""Cinematic video renderer v3.0 — high-retention editing engine.

Features:
- Pattern interrupts: visual change every 2.5-3.5s via sub-shots
- Dynamic transforms: zoom_in, zoom_out, pan_left, pan_right, dolly per sub-shot
- J-Cuts: audio leads video by 0.5s for seamless transitions
- Varied xfade transitions per scene type
- Color grading per clip
- Word-by-word animated captions (Hormozi style)
- Section overlay text with slide-in animation
- FlowStack branded intro/outro
- Background music with auto-ducking
- YouTube Shorts (9:16) support
"""
from __future__ import annotations

import asyncio
import glob
import logging
import math
import os
import random
import uuid

from app.config import settings
from app.models import Scene, ShotType, SubShot, WordTimestamp

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CROSSFADE_DURATION = 0.3

# ── Transform Templates ───────────────────────────────────
# {dur} is replaced with actual duration at render time

TRANSFORM_FILTERS = {
    "zoom_in": (
        "zoompan=z='1+0.12*on/({dur}*25)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "zoom_out": (
        "zoompan=z='1.12-0.12*on/({dur}*25)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "pan_left": (
        "zoompan=z=1.05"
        ":x='iw*0.12*(on/({dur}*25))'"
        ":y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "pan_right": (
        "zoompan=z=1.05"
        ":x='iw*(1-0.12*(on/({dur}*25)))-(iw/zoom)'"
        ":y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "dolly": (
        "zoompan=z='1.02+0.06*sin(on/({dur}*25)*PI)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
}

# Shot type → preferred transforms
SHOT_TRANSFORMS = {
    ShotType.CLOSE_UP: ["zoom_in", "zoom_out"],
    ShotType.WIDE: ["pan_left", "pan_right"],
    ShotType.ESTABLISHING: ["pan_left", "pan_right", "zoom_out"],
    ShotType.DETAIL: ["zoom_in"],
    ShotType.MEDIUM: ["dolly", "zoom_in"],
    ShotType.OVER_SHOULDER: ["zoom_in", "pan_left"],
}

# Scene type → transition pool
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
    scenes: list[Scene],
    target_duration: int = 90,
    captions: list[WordTimestamp] | None = None,
    music_mood: str = "energetic",
    video_format: str = "landscape",
) -> str:
    """Render a cinematic video with retention editing."""
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    if video_format == "shorts":
        w, h = 1080, 1920
        font_overlay, font_caption = 60, 64
    else:
        w, h = 1920, 1080
        font_overlay, font_caption = 52, 52

    matched_clips = _match_clips(footage_paths, scenes)

    # Step 1: Render intro
    intro_path = os.path.join(settings.output_dir, f"intro_{job_id}.mp4")
    await _render_intro(intro_path, w, h)

    # Step 2: Render main content with sub-shots and pattern interrupts
    main_path = os.path.join(settings.output_dir, f"main_{job_id}.mp4")
    await _render_main(matched_clips, scenes, main_path, target_duration,
                       w, h, font_overlay, captions, font_caption)

    # Step 3: Render outro
    outro_path = os.path.join(settings.output_dir, f"outro_{job_id}.mp4")
    await _render_outro(outro_path, w, h)

    # Step 4: Concat intro + main + outro
    concat_path = os.path.join(settings.output_dir, f"concat_{job_id}.mp4")
    await _concat_segments([intro_path, main_path, outro_path], concat_path)

    # Step 5: Mix audio with J-cut offset + background music
    music_path = _pick_music(music_mood)
    await _mix_audio_jcut(concat_path, audio_path, music_path, output_path)

    for p in [intro_path, main_path, outro_path, concat_path]:
        _safe_remove(p)

    logger.info("Cinematic video rendered: %s", output_path)
    return output_path


def _match_clips(clips: list[str], scenes: list[Scene]) -> list[str]:
    if not clips:
        raise RuntimeError("No footage clips provided")
    return [clips[i % len(clips)] for i in range(len(scenes))]


# ── Pattern Interrupt Logic ────────────────────────────────

def _get_subshots(scene: Scene) -> list[SubShot]:
    """Get or auto-generate sub-shots for pattern interrupts."""
    if scene.sub_shots:
        return scene.sub_shots

    interval = settings.pattern_interrupt_interval
    if scene.duration <= interval + 1.0:
        # Scene is short enough — single shot
        transform = random.choice(SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in"]))
        return [SubShot(
            shot_type=scene.shot_type,
            visual_prompt=scene.visual_prompt,
            duration=scene.duration,
            transform=transform,
        )]

    # Auto-split into sub-shots of 2.5-3.5s
    remaining = scene.duration
    subshots = []
    transforms = SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in", "pan_left"])
    while remaining > 0:
        dur = min(remaining, random.uniform(2.5, 3.5))
        if remaining - dur < 1.5:
            dur = remaining  # don't leave a tiny remainder
        subshots.append(SubShot(
            shot_type=scene.shot_type,
            visual_prompt=scene.visual_prompt,
            duration=round(dur, 1),
            transform=random.choice(transforms),
        ))
        remaining -= dur
    return subshots


# ── Intro/Outro ────────────────────────────────────────────

async def _render_intro(output_path: str, w: int, h: int) -> None:
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
        "-pix_fmt", "yuv420p", "-shortest", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_outro(output_path: str, w: int, h: int) -> None:
    name = _esc(settings.channel_name)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d=5:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "5",
        "-vf", (
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=72:fontcolor=red"
            f":x=(w-text_w)/2:y=(h/2)-60:alpha='min(1,t/0.5)',"
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=48:fontcolor=white"
            f":x=(w-text_w)/2:y=(h/2)+40:alpha='if(lt(t,0.5),0,min(1,(t-0.5)/0.5))',"
            f"drawtext=fontfile={FONT_PATH}:text='Like & Share for more'"
            f":fontsize=28:fontcolor=0xAAAAAA"
            f":x=(w-text_w)/2:y=(h/2)+110:alpha='if(lt(t,1.0),0,min(1,(t-1.0)/0.5))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Main Content (Sub-shots + Transitions) ─────────────────

async def _render_main(
    clips: list[str], scenes: list[Scene], output_path: str,
    target_duration: int, w: int, h: int,
    font_overlay: int, captions: list[WordTimestamp] | None, font_caption: int,
) -> None:
    """Render main content: each scene split into sub-shots with different transforms."""
    src_w, src_h = int(w * 1.15), int(h * 1.15)

    # Flatten scenes into sub-shots, each mapped to its parent clip
    flat_subshots: list[tuple[str, SubShot, Scene]] = []
    for clip, scene in zip(clips, scenes):
        for ss in _get_subshots(scene):
            flat_subshots.append((clip, ss, scene))

    n = len(flat_subshots)
    if n == 0:
        raise RuntimeError("No sub-shots to render")

    inputs = []
    filter_parts = []

    # Process each sub-shot
    for i, (clip, ss, scene) in enumerate(flat_subshots):
        dur = ss.duration
        inputs.extend(["-i", clip])

        # Trim a different part of the source clip per sub-shot within same scene
        # This simulates different angles from same footage
        scene_subshots = _get_subshots(scene)
        ss_idx = scene_subshots.index(ss) if ss in scene_subshots else 0
        trim_start = ss_idx * dur

        transform = ss.transform or "zoom_in"
        tf_filter = TRANSFORM_FILTERS.get(transform, TRANSFORM_FILTERS["zoom_in"])
        tf_filter = tf_filter.replace("{dur}", str(dur)).replace("{w}", str(w)).replace("{h}", str(h))

        filter_parts.append(
            f"[{i}:v]trim={trim_start}:{trim_start + dur},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
            f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"eq=brightness=0.04:contrast=1.1:saturation=1.2,"
            f"{tf_filter},"
            f"settb=AVTB,setpts=N/25/TB,fps=25"
            f"[v{i}];"
        )

    # Crossfade transitions between sub-shots
    if n == 1:
        filter_parts.append("[v0]copy[base];")
    elif n == 2:
        trans = _pick_transition(flat_subshots[1][2].label)
        cf = CROSSFADE_DURATION
        offset = flat_subshots[0][1].duration - cf
        filter_parts.append(
            f"[v0][v1]xfade=transition={trans}:duration={cf}:offset={offset}[base];"
        )
    else:
        cf = CROSSFADE_DURATION
        trans = _pick_transition(flat_subshots[1][2].label)
        offset = flat_subshots[0][1].duration - cf
        filter_parts.append(
            f"[v0][v1]xfade=transition={trans}:duration={cf}:offset={offset}[xf1];"
        )
        accumulated = flat_subshots[0][1].duration + flat_subshots[1][1].duration - cf
        for i in range(2, n):
            prev = f"xf{i-1}"
            out = f"xf{i}" if i < n - 1 else "base"
            offset = accumulated - cf
            # Alternate: use quick cut (no transition) within same scene, transition between scenes
            if flat_subshots[i][2].scene_id == flat_subshots[i-1][2].scene_id:
                trans = "fade"  # Quick cut within scene
                this_cf = 0.15
            else:
                trans = _pick_transition(flat_subshots[i][2].label)
                this_cf = cf
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition={trans}:duration={this_cf}:offset={offset}[{out}];"
            )
            accumulated += flat_subshots[i][1].duration - this_cf

    # Text overlays (section labels + overlay text)
    overlay_filters = _build_section_overlays(scenes, font_overlay, h)

    # Captions
    caption_filters = _build_caption_filters(captions, font_caption, h) if captions else ""

    all_text = ",".join(f for f in [overlay_filters, caption_filters] if f)
    if all_text:
        filter_parts.append(f"[base]{all_text}[outv]")
    else:
        filter_parts.append("[base]copy[outv]")

    filter_complex = "".join(filter_parts)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── J-Cut Audio Mixing ────────────────────────────────────

async def _mix_audio_jcut(
    video_path: str, voiceover_path: str,
    music_path: str | None, output_path: str,
) -> None:
    """Mix audio with J-cut: voiceover starts 0.5s before its visual."""
    jcut = settings.jcut_offset

    if music_path and os.path.exists(music_path):
        vol = settings.music_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut),  # J-cut: audio leads video
            "-i", voiceover_path,
            "-i", music_path,
            "-filter_complex", (
                f"[2:a]volume={vol},aloop=loop=-1:size=2e+09[music];"
                f"[music]atrim=0:duration=300[musictrim];"
                f"[1:a][musictrim]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut),
            "-i", voiceover_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path,
        ]
    await _run_ffmpeg(cmd)


# ── Concat ─────────────────────────────────────────────────

async def _concat_segments(segments: list[str], output_path: str) -> None:
    list_path = output_path + ".txt"
    with open(list_path, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path]
    await _run_ffmpeg(cmd)
    _safe_remove(list_path)


# ── Text Overlays ──────────────────────────────────────────

def _build_section_overlays(scenes: list[Scene], font_size: int, vh: int) -> str:
    filters = []
    current_time = 0.0
    for scene in scenes:
        start = current_time
        end = current_time + scene.duration

        if scene.overlay_text:
            escaped = _esc(scene.overlay_text)
            filters.append(
                f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
                f":fontsize={font_size}:fontcolor=white"
                f":box=1:boxcolor=black@0.6:boxborderw=16"
                f":x='if(lt(t-{start},0.4),(-text_w)+(w/2+text_w/2)*((t-{start})/0.4),(w-text_w)/2)'"
                f":y={vh}-th-100"
                f":enable='between(t,{start},{end})'"
                f":alpha='if(gt(t,{end-0.3}),({end}-t)/0.3,1)'"
            )

        label_colors = {
            "HOOK": "0xFF4444", "PROBLEM": "0xFF8800", "STAT": "0x00AAFF",
            "STEP": "0x00CC66", "DEMO": "0x9966FF", "BENEFIT": "0x00CC66",
            "CTA": "0xFF4444", "TRANSITION": "0x888888",
        }
        color = label_colors.get(scene.label, "0x0066FF")
        label_dur = min(2.5, scene.duration - 0.3)
        filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{_esc(scene.label)}'"
            f":fontsize=22:fontcolor=white:box=1:boxcolor={color}@0.85:boxborderw=8"
            f":x=30:y=30"
            f":enable='between(t,{start},{start + label_dur})'"
            f":alpha='if(lt(t-{start},0.2),(t-{start})/0.2,"
            f"if(gt(t,{start + label_dur - 0.2}),({start + label_dur}-t)/0.2,1))'"
        )
        current_time += scene.duration
    return ",".join(filters) if filters else ""


def _build_caption_filters(words: list[WordTimestamp], font_size: int, vh: int) -> str:
    if not words:
        return ""
    filters = []
    chunk_size = 4
    chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
    y_pos = vh - font_size - 180

    for chunk in chunks:
        chunk_end = chunk[-1].end
        for word in chunk:
            escaped = _esc(word.word)
            # Active word: yellow
            filters.append(
                f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
                f":fontsize={font_size}:fontcolor=yellow:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y={y_pos}"
                f":enable='between(t,{word.start},{word.end})'"
            )
            # After spoken: white until chunk ends
            if word.end < chunk_end:
                filters.append(
                    f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
                    f":fontsize={font_size}:fontcolor=white:borderw=3:bordercolor=black"
                    f":x=(w-text_w)/2:y={y_pos}"
                    f":enable='between(t,{word.end},{chunk_end})'"
                )
    return ",".join(filters) if filters else ""


# ── Helpers ────────────────────────────────────────────────

def _pick_transition(label: str) -> str:
    options = TRANSITION_MAP.get(label, DEFAULT_TRANSITIONS)
    return random.choice(options)


def _pick_music(mood: str) -> str | None:
    music_dir = os.path.join(settings.assets_dir, "music")
    if not os.path.isdir(music_dir):
        return None
    for pattern in [f"{mood}.*", f"{mood}_*"]:
        matches = glob.glob(os.path.join(music_dir, pattern))
        if matches:
            return matches[0]
    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        matches = glob.glob(os.path.join(music_dir, ext))
        if matches:
            return random.choice(matches)
    return None


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace("'", "\u2019")
        .replace(":", "\\:").replace("%", "\\%")
        .replace("[", "\\[").replace("]", "\\]").replace(";", "\\;")
    )


async def _run_ffmpeg(cmd: list[str]) -> None:
    logger.info("FFmpeg: %s ...", " ".join(cmd[:8]))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
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
