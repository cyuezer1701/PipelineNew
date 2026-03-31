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
from app.models import RoastScene, RoastSceneType, Scene, ShotType, SubShot, WordTimestamp

logger = logging.getLogger(__name__)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
CROSSFADE_DURATION = 0.3
FPS = 24  # Cinematic framerate

# JOB ROAST logo watermark — appended to every roast scene filter
# Glass pill logo watermark
LOGO_FILTER = (
    f"drawbox=x=20:y=18:w=185:h=40:color=black@0.45:t=fill,"
    f"drawtext=fontfile={FONT_PATH}:text='JOB ROAST'"
    f":fontsize=24:fontcolor=0xFF2D55:borderw=1:bordercolor=0xFF2D55@0.25"
    f":x=38:y=26:alpha=0.92"
)

# ── Aggressive Transforms (20% zoom, 18% pan) ─────────────

TRANSFORM_FILTERS = {
    "zoom_in": (
        "zoompan=z='1+0.20*on/({dur}*{fps})'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*{fps}:s={w}x{h}:fps={fps}"
    ),
    "zoom_out": (
        "zoompan=z='1.20-0.20*on/({dur}*{fps})'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*{fps}:s={w}x{h}:fps={fps}"
    ),
    "pan_left": (
        "zoompan=z=1.08:x='iw*0.18*(on/({dur}*{fps}))'"
        ":y='ih/2-(ih/zoom/2)':d={dur}*{fps}:s={w}x{h}:fps={fps}"
    ),
    "pan_right": (
        "zoompan=z=1.08:x='iw*(1-0.18*(on/({dur}*{fps})))-(iw/zoom)'"
        ":y='ih/2-(ih/zoom/2)':d={dur}*{fps}:s={w}x{h}:fps={fps}"
    ),
    "dolly": (
        "zoompan=z='1.03+0.10*sin(on/({dur}*{fps})*PI)'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d={dur}*{fps}:s={w}x{h}:fps={fps}"
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
# 2027 cinematic grade — cleaner, less orange, subtler
COLOR_GRADE = (
    "curves=m='0/0.05 0.25/0.20 0.5/0.50 0.75/0.80 1/0.95'"
    ":r='0/0.05 0.5/0.52 1/0.96':b='0/0.07 0.5/0.47 1/0.93',"
    "eq=saturation=1.12:contrast=1.08:brightness=0.01,"
    "noise=alls=3:allf=t,vignette=PI/4.5"
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
                f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS}"
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
                f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS}[ss{i}];"
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

    # Write filter to file to avoid "Argument list too long" on videos with many scenes
    filter_file = output_path + ".filter"
    try:
        with open(filter_file, "w") as f:
            f.write("".join(filter_parts))
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex_script", filter_file,
            "-map", "[outv]",
            "-t", str(target_duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-an", output_path,
        ]
        await _run_ffmpeg(cmd)
    finally:
        _safe_remove(filter_file)


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

    # Write filter to file to avoid "Argument list too long" on long videos
    filter_file = output_path + ".vf"
    try:
        with open(filter_file, "w") as f:
            f.write(all_text)
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_script:v", filter_file,
            "-t", str(target_duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-pix_fmt", "yuv420p", "-an", output_path,
        ]
        await _run_ffmpeg(cmd)
    finally:
        _safe_remove(filter_file)


# ── Intro / Outro ──────────────────────────────────────────

async def _render_intro(output_path: str, w: int, h: int) -> None:
    name, tagline = _esc(settings.channel_name), _esc(settings.channel_tagline)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0a0a2e:s={w}x{h}:d=2.5:r={FPS}",
        "-t", "2.5",
        "-vf", (
            f"fps={FPS},vignette=PI/3,"
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
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_outro(output_path: str, w: int, h: int) -> None:
    name = _esc(settings.channel_name)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0a0a2e:s={w}x{h}:d=4:r={FPS}",
        "-t", "4",
        "-vf", (
            f"fps={FPS},vignette=PI/3,"
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
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


# ── Audio Mix with J-Cut ───────────────────────────────────

async def _mix_audio_jcut(
    video_path: str, voiceover_path: str,
    music_path: str | None, sfx_path: str | None,
    output_path: str,
) -> None:
    """Mix audio layers: voiceover (J-cut) + background music + SFX track.

    Video duration is the master — audio is padded/trimmed to match.
    No -shortest flag to prevent premature truncation.
    """
    jcut = settings.jcut_offset
    has_music = music_path and os.path.exists(music_path)
    has_sfx = sfx_path and os.path.exists(sfx_path)

    # Use the LONGER of video/audio duration to avoid cutting off narration
    vid_dur = await _probe_duration(video_path)
    audio_dur = await _probe_duration(voiceover_path)
    max_dur = max(vid_dur, audio_dur)
    t_flag = ["-t", str(int(max_dur) + 2)] if max_dur > 0 else []

    if has_music and has_sfx:
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
                f"[music]atrim=0:duration={int(vid_dur) + 10 if vid_dur > 0 else 600}[mt];"
                f"[3:a]volume={svol}[sfx];"
                f"[1:a][mt][sfx]amix=inputs=3:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            *t_flag, "-movflags", "+faststart", output_path,
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
                f"[music]atrim=0:duration={int(vid_dur) + 10 if vid_dur > 0 else 600}[mt];"
                f"[1:a][mt]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            *t_flag, "-movflags", "+faststart", output_path,
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
            *t_flag, "-movflags", "+faststart", output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-itsoffset", str(-jcut), "-i", voiceover_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            *t_flag, "-movflags", "+faststart", output_path,
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
    return (tf.replace("{dur}", str(dur)).replace("{w}", str(w))
            .replace("{h}", str(h)).replace("{fps}", str(FPS)))


def _pick_transition(label: str) -> str:
    return random.choice(TRANSITION_MAP.get(label, DEFAULT_TRANSITIONS))




def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\u2019")
            .replace(":", "\\:").replace("%", "\\%")
            .replace("[", "\\[").replace("]", "\\]").replace(";", "\\;"))


async def _run_ffmpeg(cmd: list[str]) -> None:
    logger.info("FFmpeg: %s", " ".join(cmd[:12]))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        error_msg = stderr.decode()[-2000:] if stderr else "Unknown FFmpeg error"
        logger.error("FFmpeg FAILED: %s\nCmd: %s", error_msg[-500:], " ".join(cmd))
        raise RuntimeError(f"FFmpeg failed (exit {proc.returncode}): {error_msg}")


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


async def _probe_duration(path: str) -> float:
    """Get media file duration in seconds via ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except (ValueError, Exception):
        return 0.0


# ══════════════════════════════════════════════════════════
# ══ ROAST V4 — Split-Screen Reaction-Video Pipeline ══════
# ══════════════════════════════════════════════════════════

ROAST_TRANSITION_MAP = {
    "JOB_REVEAL": ["fade", "fadeblack"],
    "TITEL_ROAST": ["smoothdown", "fade"],
    "BENEFITS_ROAST": ["slideright", "fade"],
    "ANFORDERUNGEN_ROAST": ["slideleft", "fade"],
    "GEHALT_ROAST": ["smoothup", "fade"],
    "RATING": ["circlecrop", "fade"],
    "TRANSITION": ["fadeblack"],
    "FINAL_RANKING": ["fadeblack"],
    "COLD_OPEN": ["fade"],
    "BRANDED_INTRO": ["fade"],
    "OUTRO": ["fade"],
}


async def render_roast_scene_v2(
    clip: str,
    card_png: str,
    scene: RoastScene,
    output_path: str,
    w: int = 1920,
    h: int = 1080,
) -> None:
    """Render a split-screen roast scene: card left 55%, footage right 45%.

    The job card is the primary visual element. Stock footage is atmosphere only.
    Overlay quote appears as big yellow text on the footage side.
    """
    dur = scene.duration
    card_w = int(w * 0.55)
    footage_w = w - card_w
    src_w, src_h = int(footage_w * 1.3), int(h * 1.3)

    transform = random.choice(["zoom_in", "pan_left", "pan_right", "dolly"])
    tf = _get_transform(transform, dur, footage_w, h)

    # Build filter_complex
    quote = _esc(scene.overlay_quote) if scene.overlay_quote else ""
    quote_x = card_w + 40
    quote_max_w = footage_w - 80

    if quote:
        # With overlay quote: compose → [composed] → drawtext → [outv]
        filters = (
            f"[0:v]trim=0:{dur},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
            f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"{COLOR_GRADE},{tf},"
            f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS},"
            f"crop={footage_w}:{h}:(iw-{footage_w})/2:0,"
            f"eq=brightness=-0.15[footage];"
            f"[1:v]scale={card_w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={card_w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0D0D0D,format=rgba,"
            f"fade=t=in:st=0:d=0.5:alpha=1[card];"
            f"color=c=0x0D0D0D:s={w}x{h}:d={dur}:r={FPS}[base];"
            f"[base][card]overlay=0:0[wcard];"
            f"[wcard][footage]overlay={card_w}:0[composed];"
            f"[composed]drawtext=fontfile={FONT_PATH}:text='{quote}'"
            f":fontsize=54:fontcolor=0xFFDD00:borderw=5:bordercolor=0xFF1744"
            f":x={quote_x}+(({quote_max_w}-text_w)/2)"
            f":y=(h-text_h)/2"
            f":enable='between(t,0.8,{max(0.9, dur - 0.3)})'"
            f":alpha='if(lt(t,1.1),(t-0.8)/0.3,if(gt(t,{max(1.0, dur - 0.6)}),({max(1.0, dur - 0.3)}-t)/0.3,1))'"
            f"[outv]"
        )
    else:
        # No quote: compose → [outv] directly
        filters = (
            f"[0:v]trim=0:{dur},setpts=PTS-STARTPTS,"
            f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
            f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"{COLOR_GRADE},{tf},"
            f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS},"
            f"crop={footage_w}:{h}:(iw-{footage_w})/2:0,"
            f"eq=brightness=-0.15[footage];"
            f"[1:v]scale={card_w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={card_w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0D0D0D,format=rgba,"
            f"fade=t=in:st=0:d=0.5:alpha=1[card];"
            f"color=c=0x0D0D0D:s={w}x{h}:d={dur}:r={FPS}[base];"
            f"[base][card]overlay=0:0[wcard];"
            f"[wcard][footage]overlay={card_w}:0[outv]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", clip,
        "-i", card_png,
        "-filter_complex", filters,
        "-map", "[outv]",
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_roast_posting_scene(
    posting_png: str,
    section_bounds: dict[str, tuple[int, int]],
    scene: RoastScene,
    output_path: str,
    w: int = 1920,
    h: int = 1080,
) -> None:
    """Render a FULLSCREEN job posting with focus-scroll to the active section.

    The posting PNG (1920px wide, 2400+ tall) fills the entire screen.
    FFmpeg crops a 1080px viewport and scrolls to the section being discussed.
    No B-roll — the job text IS the content.
    """
    dur = scene.duration

    # Determine scroll target Y based on highlight_section
    hl = scene.highlight_section
    if hl and hl in section_bounds:
        target_y = max(0, section_bounds[hl][0] - 100)
    elif scene.scene_type == RoastSceneType.JOB_REVEAL:
        target_y = 0
    else:
        target_y = 0

    # Scroll expression
    if scene.scene_type == RoastSceneType.JOB_REVEAL:
        # Smooth scroll from top to bottom during reveal
        scroll_expr = f"min(max(0,ih-{h}), max(0,ih-{h})*t/{max(1, dur)})"
    else:
        # Static hold at target section
        scroll_expr = f"min(max(0,ih-{h}), {target_y})"

    # Build vf filter — single input (PNG), no clip needed
    vf = (
        f"scale={w}:-1,"
        f"pad={w}:max(ih+{h},{h}+1):0:{h // 2}:color=0x08080C,"
        f"crop={w}:{h}:0:'{scroll_expr}',"
        f"fps={FPS}"
    )

    # Overlay quote at bottom center with dark pill bg
    if scene.overlay_quote:
        quote = _esc(scene.overlay_quote)
        vf += (
            f",drawbox=x='(w-text_w)/2-15':y=h-90:w='text_w+30':h=50"
            f":color=black@0.5:t=fill,"
            f"drawtext=fontfile={FONT_PATH}:text='{quote}'"
            f":fontsize=36:fontcolor=0xFFC828"
            f":borderw=2:bordercolor=0xFF2D55"
            f":x=(w-text_w)/2:y=h-82"
            f":enable='between(t,0.8,{max(0.9, dur - 0.3)})'"
            f":alpha='if(lt(t,1.1),(t-0.8)/0.3,if(gt(t,{max(1.0, dur - 0.6)}),({max(1.0, dur - 0.3)}-t)/0.3,1))'"
        )

    # Logo watermark
    vf += f",{LOGO_FILTER}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(dur), "-i", posting_png,
        "-vf", vf,
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_roast_image_scene(
    image_path: str,
    scene: RoastScene,
    output_path: str,
    w: int = 1920,
    h: int = 1080,
) -> None:
    """Render a fullscreen scene from a still image with Ken Burns zoom/pan.
    Used for COLD_OPEN, TRANSITION, FINAL_RANKING with Ideogram backgrounds."""
    dur = scene.duration
    src_w, src_h = int(w * 1.25), int(h * 1.25)
    transform = random.choice(["zoom_in", "pan_left", "pan_right", "dolly"])
    tf = _get_transform(transform, dur, w, h)

    vf = (
        f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
        f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"{COLOR_GRADE},{tf},"
        f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS}"
    )

    # Add overlay quote text
    if scene.overlay_quote:
        escaped = _esc(scene.overlay_quote)
        vf += (
            f",drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=72:fontcolor=0xF0F0F5"
            f":borderw=3:bordercolor=0xFF2D55"
            f":x='min(w-text_w-20,(w-text_w)/2)':y=(h-text_h)/2"
            f":alpha='if(lt(t,0.3),t/0.3,if(gt(t,{max(1.0, dur - 0.5)}),({dur}-t)/0.5,1))'"
        )

    vf += f",{LOGO_FILTER}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(dur), "-i", image_path,
        "-vf", vf,
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_roast_clip_scene(
    clip: str,
    scene: RoastScene,
    output_path: str,
    w: int = 1920,
    h: int = 1080,
) -> None:
    """Render a fullscreen scene with a Runway/Pexels clip + optional overlay text.
    Used for COLD_OPEN (with quote) and TRANSITION scenes."""
    dur = scene.duration
    src_w, src_h = int(w * 1.25), int(h * 1.25)
    transform = random.choice(["zoom_in", "pan_left", "dolly"])
    tf = _get_transform(transform, dur, w, h)

    vf = (
        f"trim=0:{dur},setpts=PTS-STARTPTS,"
        f"scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,"
        f"pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"{COLOR_GRADE},{tf},"
        f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS}"
    )

    # Add overlay quote for COLD_OPEN scenes
    if scene.overlay_quote:
        escaped = _esc(scene.overlay_quote)
        vf += (
            f",drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=72:fontcolor=white"
            f":borderw=4:bordercolor=0xFF1744"
            f":x='min(w-text_w-20,(w-text_w)/2)':y=(h-text_h)/2"
            f":alpha='if(lt(t,0.3),t/0.3,if(gt(t,{max(1.0, dur - 0.5)}),({dur}-t)/0.5,1))'"
        )

    # Logo watermark
    vf += f",{LOGO_FILTER}"

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", clip,
        "-vf", vf,
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_roast_fullscreen(
    image_png: str,
    scene: RoastScene,
    output_path: str,
    w: int = 1920,
    h: int = 1080,
) -> None:
    """Render a full-screen scene from a single PNG (rating, ranking)."""
    dur = scene.duration
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(dur), "-i", image_png,
        "-vf", (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0D0D0D,"
            f"format=yuv420p,"
            f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, dur - 0.4)}:d=0.4,"
            f"settb=AVTB,setpts=N/{FPS}/TB,fps={FPS},"
            f"{LOGO_FILTER}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_roast_cold_open(
    quote: str, output_path: str, w: int = 1920, h: int = 1080,
    duration: float = 5.0,
) -> None:
    """Cold open: glitch-style quote slam on deep black."""
    dur = duration
    escaped = _esc(quote)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x08080C:s={w}x{h}:d={dur}:r={FPS}",
        "-t", str(dur),
        "-vf", (
            f"fps={FPS},vignette=PI/4,"
            # Red-shifted glitch layer (offset +3px right, -2px up)
            f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=80:fontcolor=0xFF2D55@0.35"
            f":borderw=0"
            f":x=(w-text_w)/2+3:y=(h-text_h)/2-2"
            f":alpha='if(lt(t,0.4),t/0.4,0.7+0.3*sin(t*4))',"
            # Cyan-shifted glitch layer (offset -2px left, +1px down)
            f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=80:fontcolor=0x00D2FF@0.2"
            f":borderw=0"
            f":x=(w-text_w)/2-2:y=(h-text_h)/2+1"
            f":alpha='if(lt(t,0.4),t/0.4,0.5+0.2*sin(t*6))',"
            # Main white text
            f"drawtext=fontfile={FONT_PATH}:text='{escaped}'"
            f":fontsize=80:fontcolor=0xF0F0F5"
            f":borderw=2:bordercolor=0xFF2D55"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":alpha='if(lt(t,0.3),t/0.3,if(gt(t,{max(1.0, dur - 0.5)}),({dur}-t)/0.5,1))',"
            f"{LOGO_FILTER}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_roast_intro(
    output_path: str, w: int = 1920, h: int = 1080, duration: float = 5.0,
) -> None:
    """Branded intro: 2027 glass aesthetic with accent line."""
    dur = duration
    name = _esc(settings.roast_channel_name)
    tagline = _esc("Die schlimmsten Stellenanzeigen \\\\u00B7 Deutschlands")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x08080C:s={w}x{h}:d={dur}:r={FPS}",
        "-t", str(dur),
        "-vf", (
            f"fps={FPS},vignette=PI/3.5,"
            # Glow layer
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=96:fontcolor=0xFF2D55@0.3"
            f":borderw=10:bordercolor=0xFF2D55@0.1"
            f":x=(w-text_w)/2:y=(h-text_h)/2-35"
            f":alpha='min(1,t/0.3)',"
            # Main title
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=96:fontcolor=0xF0F0F5"
            f":borderw=2:bordercolor=0xFF2D55"
            f":x=(w-text_w)/2:y=(h-text_h)/2-35"
            f":alpha='min(1,t/0.25)',"
            # Accent line (expanding from center)
            f"drawbox=x='w/2-150*min(1,(t-0.3)/0.4)':y=h/2+20"
            f":w='300*min(1,(t-0.3)/0.4)':h=2"
            f":color=0xFF2D55@0.6:t=fill"
            f":enable='gte(t,0.3)',"
            # Tagline
            f"drawtext=fontfile={FONT_PATH}:text='{tagline}'"
            f":fontsize=26:fontcolor=0x8C8CA0"
            f":x=(w-text_w)/2:y=(h/2)+45"
            f":alpha='if(lt(t,0.6),0,min(1,(t-0.6)/0.3))'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def _render_roast_outro(
    output_path: str, w: int = 1920, h: int = 1080, duration: float = 5.0,
) -> None:
    """Outro: clean 2027 CTA with glass aesthetic."""
    dur = duration
    name = _esc(settings.roast_channel_name)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x08080C:s={w}x{h}:d={dur}:r={FPS}",
        "-t", str(dur),
        "-vf", (
            f"fps={FPS},vignette=PI/3.5,"
            # ABONNIERT with glow
            f"drawtext=fontfile={FONT_PATH}:text='ABONNIERT'"
            f":fontsize=76:fontcolor=0xFF2D55"
            f":borderw=2:bordercolor=0xFF2D55@0.3"
            f":x=(w-text_w)/2:y=(h/2)-55:alpha='min(1,t/0.3)',"
            # Channel name
            f"drawtext=fontfile={FONT_PATH}:text='{name}'"
            f":fontsize=38:fontcolor=0xF0F0F5"
            f":x=(w-text_w)/2:y=(h/2)+35"
            f":alpha='if(lt(t,0.4),0,min(1,(t-0.4)/0.3))',"
            # Accent line
            f"drawbox=x='w/2-120*min(1,(t-0.6)/0.3)':y=h/2+82"
            f":w='240*min(1,(t-0.6)/0.3)':h=1"
            f":color=0xFF2D55@0.5:t=fill:enable='gte(t,0.6)',"
            # Sub-CTA
            f"drawtext=fontfile={FONT_PATH}:text='Jeden Tag neue Roasts'"
            f":fontsize=22:fontcolor=0x8C8CA0"
            f":x=(w-text_w)/2:y=(h/2)+95"
            f":alpha='if(lt(t,0.8),0,min(1,(t-0.8)/0.3))',"
            f"{LOGO_FILTER}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_roast_compilation_v2(
    scene_files: list[str],
    scenes: list[RoastScene],
    audio_path: str,
    captions: list[WordTimestamp] | None,
    music_path: str | None,
    sfx_path: str | None,
    target_duration: int,
    w: int = 1920,
    h: int = 1080,
) -> str:
    """Assemble V5 roast: concat all pre-rendered scenes + audio (no captions)."""
    job_id = uuid.uuid4().hex[:8]
    output_path = os.path.join(settings.output_dir, f"roast_{job_id}.mp4")
    tmp_files = []

    # Concat all scene files
    if len(scene_files) == 1:
        main_path = scene_files[0]
    else:
        main_path = os.path.join(settings.output_dir, f"rmain_{job_id}.mp4")
        tmp_files.append(main_path)
        await _concat_segments(scene_files, main_path)

    # No caption overlay — yellow overlay quotes are baked into scene renders

    # Duration sanity check before audio mix
    video_dur = await _probe_duration(main_path)
    audio_dur = await _probe_duration(audio_path)
    if video_dur > 0 and audio_dur > 0 and abs(video_dur - audio_dur) > 10.0:
        logger.warning(
            "Duration mismatch: video=%.1fs, voiceover=%.1fs (delta=%.1fs)",
            video_dur, audio_dur, video_dur - audio_dur,
        )

    # Audio mix with J-cut
    await _mix_audio_jcut(main_path, audio_path, music_path, sfx_path, output_path)

    for p in tmp_files:
        _safe_remove(p)

    logger.info("Roast V4 rendered: %s (%.1fs video, %.1fs audio)", output_path, video_dur, audio_dur)
    return output_path
