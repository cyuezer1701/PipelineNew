"""Cinematic video renderer v3.2 — two-pass rendering for memory efficiency.

Two-pass approach prevents OOM on long videos:
  Pass 1: Render each scene individually (1-3 inputs, low RAM)
  Pass 2: Concat scenes + add text overlays + mix audio

All cinematic effects preserved: teal/orange grade, grain, vignette,
aggressive transforms, Hormozi captions, gradient intro/outro, J-cuts.
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

# ── Aggressive Transforms (20% zoom, 18% pan) ─────────────

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
        "zoompan=z=1.08:x='iw*0.18*(on/({dur}*25))'"
        ":y='ih/2-(ih/zoom/2)':d={dur}*25:s={w}x{h}:fps=25"
    ),
    "pan_right": (
        "zoompan=z=1.08:x='iw*(1-0.18*(on/({dur}*25)))-(iw/zoom)'"
        ":y='ih/2-(ih/zoom/2)':d={dur}*25:s={w}x{h}:fps=25"
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
    "HOOK": ["fade"], "PROBLEM": ["fadeblack", "smoothdown"],
    "STAT": ["circlecrop", "fade"], "STEP": ["slideright", "slideleft"],
    "DEMO": ["smoothup", "smoothdown"], "BENEFIT": ["fade", "circlecrop"],
    "TRANSITION": ["fadeblack"], "CTA": ["fade", "smoothup"],
}
DEFAULT_TRANSITIONS = ["fade", "fadeblack", "slideright", "slideleft", "smoothup"]

# Cinematic grade: teal/orange, lifted blacks, grain, vignette
COLOR_GRADE = (
    "curves=m='0/0.06 0.25/0.22 0.5/0.5 0.75/0.78 1/0.94'"
    ":r='0/0.06 0.5/0.52 1/0.95':b='0/0.08 0.5/0.48 1/0.92',"
    "eq=saturation=1.15:contrast=1.1:brightness=0.02,"
    "noise=alls=3:allf=t,vignette=PI/5"
)


async def render_video(
    footage_paths: list[str],
    audio_path: str,
    scenes: list[Scene],
    target_duration: int = 90,
    captions: list[WordTimestamp] | None = None,
    music_mood: str = "energetic",
    video_format: str = "landscape",
    music_path: str | None = None,
    sfx_path: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"final_{job_id}.mp4")

    if video_format == "shorts":
        w, h = 1080, 1920
        font_overlay, font_caption = 64, 88
    else:
        w, h = 1920, 1080
        font_overlay, font_caption = 56, 72

    matched_clips = _match_clips(footage_paths, scenes)
    tmp_files = []

    # ── Pass 1: Render each scene individually ─────────────
    scene_files = []
    for idx, (clip, scene) in enumerate(zip(matched_clips, scenes)):
        scene_path = os.path.join(settings.output_dir, f"s{idx}_{job_id}.mp4")
        await _render_single_scene(clip, scene, scene_path, w, h)
        scene_files.append(scene_path)
        tmp_files.append(scene_path)

    # ── Pass 2: Concat scenes with transitions ─────────────
    main_path = os.path.join(settings.output_dir, f"main_{job_id}.mp4")
    tmp_files.append(main_path)
    if len(scene_files) == 1:
        os.rename(scene_files[0], main_path)
        tmp_files.remove(scene_files[0])
    else:
        await _concat_with_transitions(scene_files, scenes, main_path, target_duration)

    # ── Pass 3: Add text overlays (captions + section labels) ──
    text_path = os.path.join(settings.output_dir, f"text_{job_id}.mp4")
    tmp_files.append(text_path)
    await _apply_text_overlays(main_path, scenes, captions, text_path,
                                target_duration, w, h, font_overlay, font_caption)

    # ── Intro + Outro ──────────────────────────────────────
    intro_path = os.path.join(settings.output_dir, f"intro_{job_id}.mp4")
    outro_path = os.path.join(settings.output_dir, f"outro_{job_id}.mp4")
    tmp_files.extend([intro_path, outro_path])
    await _render_intro(intro_path, w, h)
    await _render_outro(outro_path, w, h)

    concat_path = os.path.join(settings.output_dir, f"cat_{job_id}.mp4")
    tmp_files.append(concat_path)
    await _concat_segments([intro_path, text_path, outro_path], concat_path)

    # ── Audio mix with J-cut ───────────────────────────────
    await _mix_audio_jcut(concat_path, audio_path, music_path, sfx_path, output_path)

    for p in tmp_files:
        _safe_remove(p)

    logger.info("Video rendered: %s", output_path)
    return output_path


# ── Pass 1: Single Scene Rendering ─────────────────────────

async def _render_single_scene(
    clip: str, scene: Scene, output_path: str, w: int, h: int,
) -> None:
    """Render one scene with sub-shots, transforms, and color grade.
    Uses only 1 input file — low memory."""
    subshots = _get_subshots(scene)
    src_w, src_h = int(w * 1.25), int(h * 1.25)

    if len(subshots) == 1:
        # Simple: single shot, no internal transitions
        ss = subshots[0]
        tf = _get_transform(ss.transform, ss.duration, w, h)
        cmd = [
            "ffmpeg", "-y", "-i", clip,
            "-vf", (
                f"trim=0:{ss.duration},setpts=PTS-STARTPTS,"
                f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
                f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                f"{COLOR_GRADE},{tf},"
                f"settb=AVTB,setpts=N/25/TB,fps=25"
            ),
            "-t", str(ss.duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-an", output_path,
        ]
        await _run_ffmpeg(cmd)
    else:
        # Multiple sub-shots from same clip with internal transitions
        n = len(subshots)
        filter_parts = []
        for i, ss in enumerate(subshots):
            tf = _get_transform(ss.transform, ss.duration, w, h)
            filter_parts.append(
                f"[0:v]trim=0:{ss.duration},setpts=PTS-STARTPTS,"
                f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
                f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                f"{COLOR_GRADE},{tf},"
                f"settb=AVTB,setpts=N/25/TB,fps=25[ss{i}];"
            )

        # Quick-cut transitions within scene (0.15s fade)
        if n == 2:
            offset = subshots[0].duration - 0.15
            filter_parts.append(
                f"[ss0][ss1]xfade=transition=fade:duration=0.15:offset={offset}[outv]"
            )
        else:
            offset = subshots[0].duration - 0.15
            filter_parts.append(
                f"[ss0][ss1]xfade=transition=fade:duration=0.15:offset={offset}[xf1];"
            )
            acc = subshots[0].duration + subshots[1].duration - 0.15
            for i in range(2, n):
                prev = f"xf{i-1}"
                out = f"xf{i}" if i < n - 1 else "outv"
                offset = acc - 0.15
                filter_parts.append(
                    f"[{prev}][ss{i}]xfade=transition=fade:duration=0.15:offset={offset}[{out}];"
                )
                acc += subshots[i].duration - 0.15

        total_dur = sum(ss.duration for ss in subshots)
        cmd = [
            "ffmpeg", "-y", "-i", clip,
            "-filter_complex", "".join(filter_parts),
            "-map", "[outv]",
            "-t", str(total_dur),
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-an", output_path,
        ]
        await _run_ffmpeg(cmd)


# ── Pass 2: Concat Scenes with Transitions ─────────────────

async def _concat_with_transitions(
    scene_files: list[str], scenes: list[Scene],
    output_path: str, target_duration: int,
) -> None:
    """Concat pre-rendered scene files with varied xfade transitions."""
    n = len(scene_files)
    inputs = []
    filter_parts = []

    for i, sf in enumerate(scene_files):
        inputs.extend(["-i", sf])

    cf = CROSSFADE_DURATION

    if n == 2:
        trans = _pick_transition(scenes[1].label)
        offset = scenes[0].duration - cf
        filter_parts.append(
            f"[0:v][1:v]xfade=transition={trans}:duration={cf}:offset={offset}[outv]"
        )
    else:
        trans = _pick_transition(scenes[1].label)
        offset = scenes[0].duration - cf
        filter_parts.append(
            f"[0:v][1:v]xfade=transition={trans}:duration={cf}:offset={offset}[xf1];"
        )
        acc = scenes[0].duration + scenes[1].duration - cf
        for i in range(2, n):
            prev = f"xf{i-1}"
            out = f"xf{i}" if i < n - 1 else "outv"
            offset = acc - cf
            trans = _pick_transition(scenes[i].label)
            filter_parts.append(
                f"[{prev}][{i}:v]xfade=transition={trans}:duration={cf}:offset={offset}[{out}];"
            )
            acc += scenes[i].duration - cf

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", "".join(filter_parts),
        "-map", "[outv]",
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Pass 3: Text Overlays ─────────────────────────────────

async def _apply_text_overlays(
    video_path: str, scenes: list[Scene],
    captions: list[WordTimestamp] | None,
    output_path: str, target_duration: int,
    w: int, h: int, font_overlay: int, font_caption: int,
) -> None:
    """Apply section labels, overlay text, and captions to rendered video."""
    overlay_filters = _build_section_overlays(scenes, font_overlay, h)
    caption_filters = _build_caption_filters(captions, font_caption, w, h) if captions else ""

    all_text = ",".join(f for f in [overlay_filters, caption_filters] if f)
    if not all_text:
        # No text to add, just copy
        os.rename(video_path, output_path)
        return

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", all_text,
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Intro / Outro ──────────────────────────────────────────

async def _render_intro(output_path: str, w: int, h: int) -> None:
    name, tagline = _esc(settings.channel_name), _esc(settings.channel_tagline)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0a0a2e:s={w}x{h}:d=2.5:r=25",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "2.5",
        "-vf", (
            f"vignette=PI/3,"
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize='60+60*(t/2.5)':fontcolor=0x4466FF@0.4"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30:alpha='min(1,t/0.4)',"
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize='60+60*(t/2.5)':fontcolor=white"
            f":borderw=2:bordercolor=0x2233AA"
            f":x=(w-text_w)/2:y=(h-text_h)/2-30:alpha='min(1,t/0.3)',"
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
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=80:fontcolor=0xFF2222@0.3"
            f":x=(w-text_w)/2:y=(h/2)-70:alpha='min(1,t/0.3)',"
            f"drawtext=fontfile={FONT_PATH}:text='SUBSCRIBE'"
            f":fontsize=80:fontcolor=0xFF4444:borderw=2:bordercolor=0x880000"
            f":x=(w-text_w)/2:y=(h/2)-70:alpha='min(1,t/0.3)',"
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=44:fontcolor=white"
            f":x=(w-text_w)/2:y=(h/2)+30"
            f":alpha='if(lt(t,0.4),0,min(1,(t-0.4)/0.3))',"
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


# ── Audio Mix with J-Cut ───────────────────────────────────

async def _mix_audio_jcut(
    video_path: str, voiceover_path: str,
    music_path: str | None, sfx_path: str | None,
    output_path: str,
) -> None:
    """Mix audio layers: voiceover (J-cut) + background music + SFX track."""
    jcut = settings.jcut_offset
    has_music = music_path and os.path.exists(music_path)
    has_sfx = sfx_path and os.path.exists(sfx_path)

    if has_music and has_sfx:
        # Full mix: voice + music + SFX (3 audio layers)
        mvol = settings.music_volume
        svol = settings.sfx_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut), "-i", voiceover_path,
            "-i", music_path,
            "-i", sfx_path,
            "-filter_complex", (
                f"[2:a]volume={mvol},aloop=loop=-1:size=2e+09[music];"
                f"[music]atrim=0:duration=300[mt];"
                f"[3:a]volume={svol}[sfx];"
                f"[1:a][mt][sfx]amix=inputs=3:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path,
        ]
    elif has_music:
        mvol = settings.music_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut), "-i", voiceover_path,
            "-i", music_path,
            "-filter_complex", (
                f"[2:a]volume={mvol},aloop=loop=-1:size=2e+09[music];"
                f"[music]atrim=0:duration=300[mt];"
                f"[1:a][mt]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path,
        ]
    elif has_sfx:
        svol = settings.sfx_volume
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut), "-i", voiceover_path,
            "-i", sfx_path,
            "-filter_complex", (
                f"[2:a]volume={svol}[sfx];"
                f"[1:a][sfx]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut), "-i", voiceover_path,
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
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
           "-i", list_path, "-c", "copy", output_path]
    await _run_ffmpeg(cmd)
    _safe_remove(list_path)


# ── Pattern Interrupts ─────────────────────────────────────

# Variable pacing: scene type → max seconds before a visual change
PACING_MAP = {
    "HOOK": 2.0,       # Ultra fast cuts
    "PROBLEM": 4.0,    # Let the pain sink in
    "TRANSITION": 2.5, # Snap to attention
    "STEP": 5.0,       # Slow, give time to learn
    "DEMO": 5.0,       # Show the process
    "STAT": 3.0,       # Punch the numbers
    "BENEFIT": 4.0,    # Let the win feel real
    "CTA": 5.0,        # Calm conversational close
}


def _get_subshots(scene: Scene) -> list[SubShot]:
    if scene.sub_shots:
        return scene.sub_shots

    # Variable pacing based on scene type
    max_interval = PACING_MAP.get(scene.label, settings.pattern_interrupt_interval)

    if scene.duration <= max_interval + 0.5:
        transform = random.choice(SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in"]))
        return [SubShot(shot_type=scene.shot_type, visual_prompt=scene.visual_prompt,
                        duration=scene.duration, transform=transform)]

    remaining = scene.duration
    subshots = []
    transforms = SHOT_TRANSFORMS.get(scene.shot_type, ["zoom_in", "pan_left"])

    # HOOK/STAT: ultra short sub-shots (1.5-2.5s). STEP/DEMO: longer (3-5s)
    if scene.label in ("HOOK", "STAT", "TRANSITION"):
        min_dur, max_dur = 1.5, 2.5
    elif scene.label in ("STEP", "DEMO", "CTA"):
        min_dur, max_dur = 3.0, 5.0
    else:
        min_dur, max_dur = 2.5, 3.5

    while remaining > 0:
        dur = min(remaining, random.uniform(min_dur, max_dur))
        if remaining - dur < 1.0:
            dur = remaining
        subshots.append(SubShot(shot_type=scene.shot_type, visual_prompt=scene.visual_prompt,
                                duration=round(dur, 1), transform=random.choice(transforms)))
        remaining -= dur
    return subshots


# ── Text Overlay Builders ──────────────────────────────────

def _build_section_overlays(scenes: list[Scene], font_size: int, vh: int) -> str:
    filters = []
    current_time = 0.0
    for scene in scenes:
        start, end = current_time, current_time + scene.duration
        if scene.overlay_text:
            escaped = _esc(scene.overlay_text)
            filters.append(
                f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
                f":fontsize={font_size}:fontcolor=white:borderw=4:bordercolor=black"
                f":box=1:boxcolor=black@0.55:boxborderw=18"
                f":x='if(lt(t-{start},0.35),(-text_w)+(w/2+text_w/2)*((t-{start})/0.35),(w-text_w)/2)'"
                f":y={vh}-th-110:enable='between(t,{start},{end})'"
                f":alpha='if(gt(t,{end-0.25}),({end}-t)/0.25,1)'"
            )
        label_colors = {"HOOK": "0xFF4444", "PROBLEM": "0xFF8800", "STAT": "0x00AAFF",
                        "STEP": "0x00CC66", "DEMO": "0x9966FF", "BENEFIT": "0x00CC66",
                        "CTA": "0xFF4444", "TRANSITION": "0x888888"}
        color = label_colors.get(scene.label, "0x0066FF")
        ld = min(2.0, scene.duration - 0.3)
        filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{_esc(scene.label)}'"
            f":fontsize=20:fontcolor=white:box=1:boxcolor={color}@0.85:boxborderw=7"
            f":x=30:y=30:enable='between(t,{start},{start+ld})'"
            f":alpha='if(lt(t-{start},0.15),(t-{start})/0.15,"
            f"if(gt(t,{start+ld-0.15}),({start+ld}-t)/0.15,1))'"
        )
        current_time += scene.duration
    return ",".join(filters) if filters else ""


def _build_caption_filters(
    words: list[WordTimestamp], font_size: int, vw: int, vh: int,
) -> str:
    """Hormozi captions: full phrase + active word highlighted above."""
    if not words:
        return ""
    filters = []
    chunk_size = 3
    chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
    y_pos = vh - font_size - 200

    for chunk in chunks:
        chunk_start, chunk_end = chunk[0].start, chunk[-1].end
        phrase = " ".join(w.word for w in chunk)
        escaped_phrase = _esc(phrase)

        # Full phrase in white with box
        filters.append(
            f"drawtext=fontfile={FONT_PATH}:text='{escaped_phrase}'"
            f":fontsize={font_size}:fontcolor=white:borderw=4:bordercolor=black"
            f":box=1:boxcolor=black@0.55:boxborderw=14"
            f":x=(w-text_w)/2:y={y_pos}"
            f":enable='between(t,{chunk_start},{chunk_end})'"
        )
        # Active word highlighted yellow above phrase
        for word in chunk:
            escaped_word = _esc(word.word)
            filters.append(
                f"drawtext=fontfile={FONT_PATH}:text='{escaped_word}'"
                f":fontsize={font_size + 8}:fontcolor=0xFFDD00"
                f":borderw=4:bordercolor=black"
                f":x=(w-text_w)/2:y={y_pos - font_size - 10}"
                f":enable='between(t,{word.start},{word.end})'"
            )
    return ",".join(filters) if filters else ""


# ── Helpers ────────────────────────────────────────────────

def _match_clips(clips: list[str], scenes: list[Scene]) -> list[str]:
    if not clips:
        raise RuntimeError("No footage clips provided")
    return [clips[i % len(clips)] for i in range(len(scenes))]


def _get_transform(name: str, dur: float, w: int, h: int) -> str:
    tf = TRANSFORM_FILTERS.get(name, TRANSFORM_FILTERS["zoom_in"])
    return tf.replace("{dur}", str(dur)).replace("{w}", str(w)).replace("{h}", str(h))


def _pick_transition(label: str) -> str:
    return random.choice(TRANSITION_MAP.get(label, DEFAULT_TRANSITIONS))




def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\u2019")
            .replace(":", "\\:").replace("%", "\\%")
            .replace("[", "\\[").replace("]", "\\]").replace(";", "\\;"))


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
