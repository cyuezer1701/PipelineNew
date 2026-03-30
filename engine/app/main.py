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
from app.services.script_generator import generate_script
from app.services.stock_footage import download_footage
from app.services.video_renderer import render_video
from app.services.voiceover import generate_voiceover
from app.services.youtube_uploader import upload_to_youtube

# In-memory job store (sufficient for single-VPS workload)
jobs: dict[str, JobResponse] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    jobs.clear()


app = FastAPI(
    title="YouTube Content Engine",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Full Pipeline ──────────────────────────────────────────

async def _run_pipeline(job_id: str, req: GenerateRequest) -> None:
    """Execute the full content generation pipeline."""
    try:
        jobs[job_id].status = JobStatus.PROCESSING

        # 1. Generate script
        jobs[job_id].message = "Generating script..."
        script = await generate_script(
            topic=req.topic,
            keywords=req.keywords,
            target_duration=req.target_duration,
        )

        # 2. Generate voiceover from script
        jobs[job_id].message = "Generating voiceover..."
        audio_path = await generate_voiceover(script.script)

        # 3. Download stock footage
        jobs[job_id].message = "Downloading stock footage..."
        search_terms = req.keywords or [req.topic]
        footage_paths = await download_footage(
            queries=search_terms,
            target_duration=req.target_duration,
        )

        # 4. Render video
        jobs[job_id].message = "Rendering video..."
        output_path = await render_video(
            footage_paths=footage_paths,
            audio_path=audio_path,
            sections=script.sections,
            target_duration=req.target_duration,
        )

        result = {"video_path": output_path, "script": script.script}

        # 5. Upload to YouTube (optional)
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
    """Kick off the full video generation pipeline (async)."""
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Queued")
    bg.add_task(_run_pipeline, job_id, req)
    return jobs[job_id]


# ── Individual Endpoints ───────────────────────────────────

@app.post("/api/script", response_model=ScriptResponse)
async def script(req: ScriptRequest):
    """Generate an AIDA-structured script."""
    return await generate_script(
        topic=req.topic,
        keywords=req.keywords,
        target_duration=req.target_duration,
    )


# ── Job Status ─────────────────────────────────────────────

@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    if job_id not in jobs:
        return JobResponse(job_id=job_id, status=JobStatus.FAILED, message="Job not found")
    return jobs[job_id]


# ── Health Check ───────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "youtube-content-engine"}
