"""Cinematic video renderer v3.1 — senior creator quality.

Upgrades from v3.0:
- Hormozi-style captions: full phrase visible, active word highlighted yellow
- Cinematic teal/orange color grade with lifted blacks
- Film grain + vignette for anti-AI look
- Aggressive transforms (20% zoom, 18% pan)
- Gradient intro with glow text effect
- Safe sub-shot trimming (no crash on short clips)
- Larger caption fonts (72pt landscape, 88pt shorts)
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import random
import uuid

from app.config import settings
from app.models import Scene, ShotType, SubShot, WordTimestamp

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CROSSFADE_DURATION = 0.3

# ── Aggressive Transform Templates (20% zoom, 18% pan) ────

TRANSFORM_FILTERS = {
    "zoom_in": (
        "zoompan=z='1+0.20*on/({dur}*25)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "zoom_out": (
        "zoompan=z='1.20-0.20*on/({dur}*25)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "pan_left": (
        "zoompan=z=1.08"
        ":x='iw*0.18*(on/({dur}*25))'"
        ":y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "pan_right": (
        "zoompan=z=1.08"
        ":x='iw*(1-0.18*(on/({dur}*25)))-(iw/zoom)'"
        ":y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
    "dolly": (
        "zoompan=z='1.03+0.10*sin(on/({dur}*25)*PI)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*25:s={w}x{h}:fps=25"
    ),
}

SHOT_TRANSFORMS = {
    ShotType.CLOSE_UP: ["zoom_in", "zoom_out"],
    ShotType.WIDE: ["pan_left", "pan_right"],
    ShotType.ESTABLISHING: ["pan_left", "pan_right", "zoom_out"],
    ShotType.DETAIL: ["zoom_in"],
    ShotType.MEDIUM: ["dolly", "zoom_in"],
    ShotType.OVER_SHOULDER: ["zoom_in", "pan_left"],
}

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

# ── Cinematic Color Grade (teal/orange, lifted blacks) ─────
# Lifts blacks to ~6%, warm highlights, cool shadows
COLOR_GRADE = (
    "curves=m='0/0.06 0.25/0.22 0.5/0.5 0.75/0.78 1/0.94'"
    ":r='0/0.06 0.5/0.52 1/0.95'"
    ":b='0/0.08 0.5/0.48 1/0.92',"
    "eq=saturation=1.15:contrast=1.1:brightness=0.02,"
    "noise=alls=3:allf=t,"
    "vignette=PI/5"
)


async def render_video(
    footage_paths: list[str],
    audio_path: str,
    scenes: list[Scene],
    target_duration: int = 90,
    captions: list[WordTimestamp] | None = None,
    music_mood: str = "energetic",
    video_format: str = "landscape",
) -> str:
    """Render a cinematic video with senior-creator-quality editing."""
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    if video_format == "shorts":
        w, h = 1080, 1920
        font_overlay, font_caption = 64, 88
    else:
        w, h = 1920, 1080
        font_overlay, font_caption = 56, 72

    matched_clips = _match_clips(footage_paths, scenes)

    intro_path = os.path.join(settings.output_dir, f"intro_{job_id}.mp4")
    await _render_intro(intro_path, w, h)

    main_path = os.path.join(settings.output_dir, f"main_{job_id}.mp4")
    await _render_main(matched_clips, scenes, main_path, target_duration,
                       w, h, font_overlay, captions, font_caption)

    outro_path = os.path.join(settings.output_dir, f"outro_{job_id}.mp4")
    await _render_outro(outro_path, w, h)

    concat_path = os.path.join(settings.output_dir, f"concat_{job_id}.mp4")
    await _concat_segments([intro_path, main_path, outro_path], concat_path)

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


# ── Pattern Interrupts ─────────────────────────────────────

def _get_subshots(scene: Scene) -> list[SubShot]:
    if scene.sub_shots:
        return scene.sub_shots

    interval = settings.pattern_interrupt_interval
    if scene.duration <= interval + 1.0:
        transform = random.choice(SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in"]))
        return [SubShot(shot_type=scene.shot_type, visual_prompt=scene.visual_prompt,
                        duration=scene.duration, transform=transform)]

    remaining = scene.duration
    subshots = []
    transforms = SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in", "pan_left"])
    while remaining > 0:
        dur = min(remaining, random.uniform(2.5, 3.5))
        if remaining - dur < 1.5:
            dur = remaining
        subshots.append(SubShot(shot_type=scene.shot_type, visual_prompt=scene.visual_prompt,
                                duration=round(dur, 1), transform=random.choice(transforms)))
        remaining -= dur
    return subshots


# ── Cinematic Intro (gradient + glow) ──────────────────────

async def _render_intro(output_path: str, w: int, h: int) -> None:
    name = _esc(settings.channel_name)
    tagline = _esc(settings.channel_tagline)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0a0a2e:s={w}x{h}:d=2.5:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "2.5",
        "-vf", (
            # Vignette on dark navy background
            f"vignette=PI/3,"
            # Glow layer: blurred white text behind sharp text
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize='60+60*(t/2.5)':fontcolor=0x4466FF@0.4"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30"
            f":alpha='min(1,t/0.4)',"
            # Sharp channel name
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize='60+60*(t/2.5)':fontcolor=white"
            f":borderw=2:bordercolor=0x2233AA"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30"
            f":alpha='min(1,t/0.3)',"
            # Tagline fades in
            f"drawtext=fontfile={FONT_PATH}:text='{tagline}'"
            f":fontsize=30:fontcolor=0x8899DD"
            f":x=(w-text_w)/2:y=(h/2)+50"
            f":alpha='if(lt(t,0.6),0,min(1,(t-0.6)/0.4))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_outro(output_path: str, w: int, h: int) -> None:
    name = _esc(settings.channel_name)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0a0a2e:s={w}x{h}:d=4:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "4",
        "-vf", (
            f"vignette=PI/3,"
            # SUBSCRIBE in red with glow
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=80:fontcolor=0xFF2222@0.3"
            f":x=(w-text_w)/2:y=(h/2)-70:alpha='min(1,t/0.3)',"
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=80:fontcolor=0xFF4444"
            f":borderw=2:bordercolor=0x880000"
            f":x=(w-text_w)/2:y=(h/2)-70:alpha='min(1,t/0.3)',"
            # Channel name
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=44:fontcolor=white"
            f":x=(w-text_w)/2:y=(h/2)+30"
            f":alpha='if(lt(t,0.4),0,min(1,(t-0.4)/0.3))',"
            # CTA
            f"drawtext=fontfile={FONT_PATH}:text='Hit the bell \\: never miss a video'"
            f":fontsize=24:fontcolor=0x8899CC"
            f":x=(w-text_w)/2:y=(h/2)+95"
            f":alpha='if(lt(t,0.8),0,min(1,(t-0.8)/0.4))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Main Content ───────────────────────────────────────────

async def _render_main(
    clips: list[str], scenes: list[Scene], output_path: str,
    target_duration: int, w: int, h: int,
    font_overlay: int, captions: list[WordTimestamp] | None, font_caption: int,
) -> None:
    src_w, src_h = int(w * 1.25), int(h * 1.25)  # 25% overscan for aggressive zoom

    flat_subshots: list[tuple[str, SubShot, Scene]] = []
    for clip, scene in zip(clips, scenes):
        for ss in _get_subshots(scene):
            flat_subshots.append((clip, ss, scene))

    n = len(flat_subshots)
    if n == 0:
        raise RuntimeError("No sub-shots to render")

    inputs = []
    filter_parts = []

    for i, (clip, ss, scene) in enumerate(flat_subshots):
        dur = ss.duration
        inputs.extend(["-i", clip])

        # SAFE trim: always start from 0, vary transform instead
        # This prevents crashes when clip is shorter than offset
        transform = ss.transform or "zoom_in"
        tf_filter = TRANSFORM_FILTERS.get(transform, TRANSFORM_FILTERS["zoom_in"])
        tf_filter = tf_filter.replace("{dur}", str(dur)).replace("{w}", str(w)).replace("{h}", str(h))

        filter_parts.append(
            f"[{i}:v]trim=0:{dur},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
            f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            # Cinematic color grade + grain + vignette
            f"{COLOR_GRADE},"
            f"{tf_filter},"
            f"settb=AVTB,setpts=N/25/TB,fps=25"
            f"[v{i}];"
        )

    # Crossfade transitions
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
            if flat_subshots[i][2].scene_id == flat_subshots[i-1][2].scene_id:
                trans = "fade"
                this_cf = 0.15
            else:
                trans = _pick_transition(flat_subshots[i][2].label)
                this_cf = cf
            filter_parts.append(
                f"[{prev}][v{i}]xfade=transition={trans}:duration={this_cf}:offset={offset}[{out}];"
            )
            accumulated += flat_subshots[i][1].duration - this_cf

    # Section overlays + Hormozi captions
    overlay_filters = _build_section_overlays(scenes, font_overlay, h)
    caption_filters = _build_caption_filters(captions, font_caption, w, h) if captions else ""

    all_text = ",".join(f for f in [overlay_filters, caption_filters] if f)
    if all_text:
        filter_parts.append(f"[base]{all_text}[outv]")
    else:
        filter_parts.append("[base]copy[outv]")

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", "".join(filter_parts),
        "-map", "[outv]",
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── J-Cut Audio Mixing ────────────────────────────────────

async def _mix_audio_jcut(
    video_path: str, voiceover_path: str,
    music_path: str | None, output_path: str,
) -> None:
    jcut = settings.jcut_offset

    if music_path and os.path.exists(music_path):
        vol = settings.music_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut),
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


# ── Section Overlays ───────────────────────────────────────

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
                f":borderw=4:bordercolor=black"
                f":box=1:boxcolor=black@0.55:boxborderw=18"
                f":x='if(lt(t-{start},0.35),(-text_w)+(w/2+text_w/2)*((t-{start})/0.35),(w-text_w)/2)'"
                f":y={vh}-th-110"
                f":enable='between(t,{start},{end})'"
                f":alpha='if(gt(t,{end-0.25}),({end}-t)/0.25,1)'"
            )

        label_colors = {
            "HOOK": "0xFF4444", "PROBLEM": "0xFF8800", "STAT": "0x00AAFF",
            "STEP": "0x00CC66", "DEMO": "0x9966FF", "BENEFIT": "0x00CC66",
            "CTA": "0xFF4444", "TRANSITION": "0x888888",
        }
        color = label_colors.get(scene.label, "0x0066FF")
        label_dur = min(2.0, scene.duration - 0.3)
        filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{_esc(scene.label)}'"
            f":fontsize=20:fontcolor=white:box=1:boxcolor={color}@0.85:boxborderw=7"
            f":x=30:y=30"
            f":enable='between(t,{start},{start + label_dur})'"
            f":alpha='if(lt(t-{start},0.15),(t-{start})/0.15,"
            f"if(gt(t,{start + label_dur - 0.15}),({start + label_dur}-t)/0.15,1))'"
        )
        current_time += scene.duration
    return ",".join(filters) if filters else ""


# ── Hormozi-Style Captions ─────────────────────────────────

def _build_caption_filters(
    words: list[WordTimestamp], font_size: int, vw: int, vh: int,
) -> str:
    """Hormozi-style captions: full phrase visible, active word highlighted.

    Shows 3-4 word phrase in white with black box.
    The currently spoken word is overlaid in yellow at the same position.
    Creates the effect of word-by-word highlighting within a phrase.
    """
    if not words:
        return ""

    filters = []
    chunk_size = 3
    chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
    y_pos = vh - font_size - 200

    for chunk in chunks:
        chunk_start = chunk[0].start
        chunk_end = chunk[-1].end

        # Build the full phrase string
        phrase = " ".join(w.word for w in chunk)
        escaped_phrase = _esc(phrase)

        # Layer 1: Full phrase in white with black box (visible entire chunk duration)
        filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{escaped_phrase}'"
            f":fontsize={font_size}:fontcolor=white"
            f":borderw=4:bordercolor=black"
            f":box=1:boxcolor=black@0.55:boxborderw=14"
            f":x=(w-text_w)/2:y={y_pos}"
            f":enable='between(t,{chunk_start},{chunk_end})'"
        )

        # Layer 2: Each word highlighted in yellow when spoken
        # We show the full phrase again but only the active word is visible (yellow)
        # by overlaying just that word. Since exact positioning per-word is hard in FFmpeg,
        # we overlay the active word centered — it won't perfectly align with the phrase
        # but visually it creates a strong "current word" indicator
        for word in chunk:
            escaped_word = _esc(word.word)
            # Active word: larger yellow text, centered, on top of phrase
            filters.append(
                f"drawtext=fontfile={FONT_PATH}:text='{escaped_word}'"
                f":fontsize={font_size + 8}:fontcolor=0xFFDD00"
                f":borderw=4:bordercolor=black"
                f":x=(w-text_w)/2:y={y_pos - font_size - 10}"
                f":enable='between(t,{word.start},{word.end})'"
            )

    return ",".join(filters) if filters else ""


# ── Helpers ────────────────────────────────────────────────

def _pick_transition(label: str) -> str:
    return random.choice(TRANSITION_MAP.get(label, DEFAULT_TRANSITIONS))


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
