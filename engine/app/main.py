from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI

from app.models import (
    GenerateRequest,
    JobResponse,
    JobStatus,
    RoastRequest,
    ScriptRequest,
    ScriptResponse,
)
from app.services.caption_generator import generate_captions
from app.services.footage_orchestrator import orchestrate_footage
from app.services.mubert_generator import get_music_track
from app.services.script_generator import generate_script
from app.services.sound_effects import generate_sfx_track
from app.services.thumbnail_generator import generate_thumbnail
from app.services.video_renderer import render_video
from app.services.voiceover import generate_voiceover
from app.services.youtube_uploader import upload_to_youtube

jobs: dict[str, JobResponse] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    jobs.clear()


app = FastAPI(
    title="FlowStack Cinematic Engine",
    version="3.2.0",
    lifespan=lifespan,
)


async def _run_pipeline(job_id: str, req: GenerateRequest) -> None:
    try:
        jobs[job_id].status = JobStatus.PROCESSING

        # 1. Generate cinematic script
        jobs[job_id].message = "Generating script..."
        script = await generate_script(
            topic=req.topic,
            keywords=req.keywords,
            target_duration=req.target_duration,
            video_format=req.video_format,
            use_runway=req.use_runway,
        )

        # 2. Generate voiceover (TTS or STS)
        jobs[job_id].message = "Generating voiceover..."
        audio_path = await generate_voiceover(
            text=script.script,
            guide_audio_path=req.guide_audio_url,
        )

        # 3. Generate captions
        jobs[job_id].message = "Generating captions..."
        captions = await generate_captions(audio_path)

        # 4. Generate background music (Mubert AI or local files)
        jobs[job_id].message = "Generating background music..."
        music_path = await get_music_track(
            mood=script.music_mood,
            duration=req.target_duration,
        )

        # 5. Generate SFX track (ElevenLabs Sound Effects)
        jobs[job_id].message = "Generating sound effects..."
        sfx_path = await generate_sfx_track(
            scenes=script.scenes,
            target_duration=req.target_duration,
        )

        # 6. Orchestrate footage (Runway AI + Pexels stock)
        jobs[job_id].message = "Generating footage..."
        footage_paths = await orchestrate_footage(
            scenes=script.scenes,
            character_ref=req.runway_character_ref,
        )

        # 7. Render cinematic video
        jobs[job_id].message = "Rendering video..."
        output_path = await render_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            scenes=script.scenes,
            target_duration=req.target_duration,
            captions=captions,
            music_mood=script.music_mood,
            video_format=req.video_format,
            music_path=music_path,
            sfx_path=sfx_path,
        )

        # 8. Generate thumbnail (DALL-E 3 or frame extraction)
        jobs[job_id].message = "Generating thumbnail..."
        thumb_text = script.thumbnail_text or req.topic[:30]
        thumbnail_path = await generate_thumbnail(
            video_path=output_path,
            text=thumb_text,
            topic=req.topic,
        )

        result = {
            "video_path": output_path,
            "thumbnail_path": thumbnail_path,
            "script": script.script,
            "music_mood": script.music_mood,
            "has_music": music_path is not None,
            "has_sfx": sfx_path is not None,
            "captions_count": len(captions),
            "scenes_count": len(script.scenes),
        }

        # 9. Upload to YouTube (optional)
        if req.upload:
            jobs[job_id].message = "Uploading to YouTube..."
            video_id = await upload_to_youtube(
                video_path=output_path,
                title=req.youtube_title or req.topic,
                description=req.youtube_description or script.script,
                tags=req.youtube_tags or req.keywords,
            )
            result["youtube_video_id"] = video_id

        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].message = "Pipeline complete"
        jobs[job_id].result = result

    except Exception as e:
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].message = str(e)


@app.post("/api/generate", response_model=JobResponse)
async def generate(req: GenerateRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Queued")
    bg.add_task(_run_pipeline, job_id, req)
    return jobs[job_id]


@app.post("/api/script", response_model=ScriptResponse)
async def script(req: ScriptRequest):
    return await generate_script(
        topic=req.topic, keywords=req.keywords,
        target_duration=req.target_duration,
        video_format=req.video_format, use_runway=req.use_runway,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    if job_id not in jobs:
        return JobResponse(job_id=job_id, status=JobStatus.FAILED, message="Job not found")
    return jobs[job_id]


# ── Job Roast Pipeline ─────────────────────────────────────

async def _run_roast_pipeline(job_id: str, req: RoastRequest) -> None:
    """Execute the job roast video pipeline."""
    try:
        jobs[job_id].status = JobStatus.PROCESSING

        from app.services.job_card_renderer import render_job_card
        from app.services.job_roast_generator import generate_roast_script
        from app.services.stock_footage import download_footage_for_sections
        from app.services.video_renderer import render_roast_compilation, render_roast_scene

        # 1. Generate roast script (Claude — Deutsch, Kanacken-Slang)
        jobs[job_id].message = "Generating roast script..."
        roast = await generate_roast_script(req.jobs, req.category)

        # 2. Generate voiceover
        jobs[job_id].message = "Generating voiceover..."
        audio_path = await generate_voiceover(roast.full_script)

        # 3. Generate captions
        jobs[job_id].message = "Generating captions..."
        captions = await generate_captions(audio_path)

        # 4. Render job cards as PNGs
        jobs[job_id].message = "Rendering job cards..."
        card_images = []
        for job_posting in req.jobs:
            card_path = await render_job_card(job_posting)
            card_images.append(card_path)

        # 5. Download background footage
        jobs[job_id].message = "Downloading footage..."
        footage_paths = await download_footage_for_sections(roast.scenes)

        # 6. Generate music + SFX
        jobs[job_id].message = "Generating audio layers..."
        music_path = await get_music_track(roast.music_mood, roast.estimated_duration)
        sfx_path = await generate_sfx_track(roast.scenes, roast.estimated_duration)

        # 7. Render each scene (with job card overlay for REVEAL scenes)
        jobs[job_id].message = "Rendering scenes..."
        scene_files = []
        card_idx = 0
        for idx, scene in enumerate(roast.scenes):
            scene_path = os.path.join("/app/output", f"rs{idx}_{job_id}.mp4")
            clip = footage_paths[idx % len(footage_paths)]

            if "REVEAL" in scene.label.upper() and card_idx < len(card_images):
                await render_roast_scene(clip, card_images[card_idx], scene, scene_path)
                card_idx += 1
            else:
                from app.services.video_renderer import _render_single_scene
                await _render_single_scene(clip, scene, scene_path, 1920, 1080)

            scene_files.append(scene_path)

        # 8. Extract individual Shorts (one per job)
        jobs[job_id].message = "Extracting shorts..."
        short_files = []
        for i, group in enumerate(roast.job_scene_groups):
            if not group:
                continue
            group_scenes = [roast.scenes[j] for j in group if j < len(scene_files)]
            group_files = [scene_files[j] for j in group if j < len(scene_files)]
            if group_files:
                short_path = os.path.join("/app/output", f"short{i}_{job_id}.mp4")
                from app.services.video_renderer import _concat_segments
                await _concat_segments(group_files, short_path)
                short_files.append({
                    "path": short_path,
                    "title": req.jobs[i].title if i < len(req.jobs) else f"Job {i+1}",
                })

        # 9. Compile full video
        jobs[job_id].message = "Compiling final video..."
        output_path = await render_roast_compilation(
            scene_files=scene_files,
            scenes=roast.scenes,
            audio_path=audio_path,
            captions=captions,
            music_path=music_path,
            sfx_path=sfx_path,
            target_duration=roast.estimated_duration,
        )

        # 10. Generate thumbnail
        jobs[job_id].message = "Generating thumbnail..."
        thumb_text = roast.thumbnail_text or req.category
        thumbnail_path = await generate_thumbnail(
            video_path=output_path, text=thumb_text, topic=req.category,
        )

        result = {
            "video_path": output_path,
            "thumbnail_path": thumbnail_path,
            "shorts": short_files,
            "script": roast.full_script,
            "scenes_count": len(roast.scenes),
        }

        # 11. Upload
        if req.upload:
            jobs[job_id].message = "Uploading to YouTube..."
            yt_title = req.youtube_title or f"JOB ROAST: {req.category}"
            yt_desc = req.youtube_description or roast.full_script[:3000]
            video_id = await upload_to_youtube(
                video_path=output_path, title=yt_title,
                description=yt_desc, tags=req.youtube_tags or ["job roast", "stellenanzeige", "obstkorb"],
            )
            result["youtube_video_id"] = video_id

        if req.upload_shorts:
            jobs[job_id].message = "Uploading shorts..."
            result["shorts_video_ids"] = []
            for short in short_files:
                short_id = await upload_to_youtube(
                    video_path=short["path"],
                    title=f"ROAST: {short['title'][:80]}",
                    description=f"Job Roast Short\n\n#shorts #jobroast #stellenanzeige #obstkorb",
                    tags=["shorts", "job roast", "stellenanzeige"],
                )
                result["shorts_video_ids"].append(short_id)

        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].message = "Roast complete"
        jobs[job_id].result = result

    except Exception as e:
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].message = str(e)


@app.post("/api/roast", response_model=JobResponse)
async def roast(req: RoastRequest, bg: BackgroundTasks):
    """Generate a job roast video — 3 jobs roasted + individual Shorts."""
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Queued")
    bg.add_task(_run_roast_pipeline, job_id, req)
    return jobs[job_id]


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "flowstack-cinematic-engine", "version": "3.3.0"}
