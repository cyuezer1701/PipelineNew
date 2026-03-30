from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI

from app.models import (
    GenerateRequest,
    JobResponse,
    JobStatus,
    ScriptRequest,
    ScriptResponse,
)
from app.services.caption_generator import generate_captions
from app.services.footage_orchestrator import orchestrate_footage
from app.services.script_generator import generate_script
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
    version="3.0.0",
    lifespan=lifespan,
)


# ── Full Pipeline ──────────────────────────────────────────

async def _run_pipeline(job_id: str, req: GenerateRequest) -> None:
    """Execute the cinematic content generation pipeline."""
    try:
        jobs[job_id].status = JobStatus.PROCESSING

        # 1. Generate cinematic script with Scene objects
        jobs[job_id].message = "Generating cinematic script..."
        script = await generate_script(
            topic=req.topic,
            keywords=req.keywords,
            target_duration=req.target_duration,
            video_format=req.video_format,
            use_runway=req.use_runway,
        )

        # 2. Generate voiceover (TTS or STS mode)
        jobs[job_id].message = "Generating voiceover..."
        audio_path = await generate_voiceover(
            text=script.script,
            guide_audio_path=req.guide_audio_url,
        )

        # 3. Generate word-level captions
        jobs[job_id].message = "Generating captions..."
        captions = await generate_captions(audio_path)

        # 4. Orchestrate footage (Runway AI + Pexels stock, 70/30 mix)
        jobs[job_id].message = "Generating footage (AI + stock)..."
        footage_paths = await orchestrate_footage(
            scenes=script.scenes,
            character_ref=req.runway_character_ref,
        )

        # 5. Render cinematic video (retention editing, J-cuts, pattern interrupts)
        jobs[job_id].message = "Rendering cinematic video..."
        output_path = await render_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            scenes=script.scenes,
            target_duration=req.target_duration,
            captions=captions,
            music_mood=script.music_mood,
            video_format=req.video_format,
        )

        # 6. Generate thumbnail
        jobs[job_id].message = "Generating thumbnail..."
        thumb_text = script.thumbnail_text or req.topic[:30]
        thumbnail_path = await generate_thumbnail(
            video_path=output_path,
            text=thumb_text,
        )

        result = {
            "video_path": output_path,
            "thumbnail_path": thumbnail_path,
            "script": script.script,
            "music_mood": script.music_mood,
            "captions_count": len(captions),
            "scenes_count": len(script.scenes),
            "character_description": script.character_description,
        }

        # 7. Upload to YouTube (optional)
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
    """Kick off the cinematic video generation pipeline."""
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Queued")
    bg.add_task(_run_pipeline, job_id, req)
    return jobs[job_id]


@app.post("/api/script", response_model=ScriptResponse)
async def script(req: ScriptRequest):
    """Generate a cinematic script with Scene objects."""
    return await generate_script(
        topic=req.topic,
        keywords=req.keywords,
        target_duration=req.target_duration,
        video_format=req.video_format,
        use_runway=req.use_runway,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    if job_id not in jobs:
        return JobResponse(job_id=job_id, status=JobStatus.FAILED, message="Job not found")
    return jobs[job_id]


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "flowstack-cinematic-engine", "version": "3.0.0"}
