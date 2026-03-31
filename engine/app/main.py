from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from fastapi import BackgroundTasks, FastAPI

from app.config import settings
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


# ── Job Roast Pipeline V4 ─────────────────────────────────

async def _run_roast_pipeline(job_id: str, req: RoastRequest) -> None:
    """Execute the V4 job roast video pipeline — single video, split-screen, German."""
    try:
        jobs[job_id].status = JobStatus.PROCESSING

        from app.models import RoastSceneType
        from app.services.job_card_renderer import (
            render_job_posting,
            render_ranking_leaderboard,
            render_rating_card,
        )
        from app.services.job_roast_generator import generate_roast_script
        from app.services.runway_generator import generate_runway_footage
        from app.services.stock_footage import download_footage_for_sections
        from app.services.video_renderer import (
            _render_roast_cold_open,
            _render_roast_intro,
            _render_roast_outro,
            _render_single_scene,
            render_roast_clip_scene,
            render_roast_compilation_v2,
            render_roast_fullscreen,
            render_roast_posting_scene,
        )

        # 1. Generate roast script (Claude — Deutsch, Kanacken-Slang)
        jobs[job_id].message = "Step 1/10: Generating roast script..."
        roast = await generate_roast_script(req.jobs, req.category)

        # 2. Generate voiceover
        jobs[job_id].message = "Step 2/10: Generating voiceover..."
        audio_path = await generate_voiceover(
            roast.full_script,
            guide_audio_path=req.guide_audio_url,
        )

        # 3. Skip captions (not needed — overlay quotes are baked into scenes)
        captions = None

        # 4. Pre-render job postings + rating cards + ranking
        jobs[job_id].message = "Step 4/10: Rendering job postings..."
        posting_assets: dict[int, dict] = {}
        for i, job_posting in enumerate(req.jobs):
            # Full posting (no highlight) — used for JOB_REVEAL
            full_png, full_bounds = await render_job_posting(job_posting, "")
            # Highlighted variants — used for TITEL/BENEFITS/ANFORDERUNGEN/GEHALT roasts
            title_png, _ = await render_job_posting(job_posting, "title")
            benefits_png, _ = await render_job_posting(job_posting, "benefits")
            requirements_png, _ = await render_job_posting(job_posting, "requirements")
            salary_png, _ = await render_job_posting(job_posting, "salary")

            rating = roast.job_ratings[i] if i < len(roast.job_ratings) else 5
            rating_png = await render_rating_card(job_posting, rating)

            posting_assets[i] = {
                "full": full_png,
                "title": title_png,
                "benefits": benefits_png,
                "requirements": requirements_png,
                "salary": salary_png,
                "rating": rating_png,
                "bounds": full_bounds,  # Section Y-positions for scroll targeting
            }

        ranking_png = await render_ranking_leaderboard(
            req.jobs, roast.job_ratings, roast.final_ranking,
        )

        # 5. Download background footage (Pexels) + generate Runway clips for fullscreen scenes
        jobs[job_id].message = "Step 5/10: Downloading footage + Runway AI clips..."
        from app.models import Scene
        footage_scenes = [Scene(
            b_roll_keywords=s.b_roll_keywords,
            duration=s.duration,
        ) for s in roast.scenes]
        footage_paths = await download_footage_for_sections(footage_scenes)

        # Generate Runway clips for fullscreen scenes (COLD_OPEN, TRANSITION, FINAL_RANKING)
        runway_clips: dict[int, str] = {}
        if settings.runway_api_key:
            runway_scenes = []
            for s in roast.scenes:
                if s.scene_type in (RoastSceneType.COLD_OPEN, RoastSceneType.TRANSITION, RoastSceneType.FINAL_RANKING):
                    # Build visual prompt for Runway
                    keywords = " ".join(s.b_roll_keywords) if s.b_roll_keywords else "dramatic office"
                    runway_scene = Scene(
                        scene_id=s.scene_id,
                        visual_prompt=f"Cinematic {keywords}, moody lighting, dark atmosphere, slow motion",
                        shot_type="medium",
                        duration=min(s.duration, 10),
                        b_roll_keywords=s.b_roll_keywords,
                    )
                    runway_scenes.append(runway_scene)
            if runway_scenes:
                try:
                    jobs[job_id].message = f"Step 5/10: Generating {len(runway_scenes)} Runway AI clips..."
                    runway_clips = await generate_runway_footage(runway_scenes)
                    logger.info("Runway generated %d clips for fullscreen scenes", len(runway_clips))
                except Exception as e:
                    logger.warning("Runway generation failed, falling back to Pexels: %s", e)

        # 6. Generate music + SFX
        jobs[job_id].message = "Step 6/10: Generating audio layers..."
        music_path = await get_music_track(roast.music_mood, roast.estimated_duration)
        sfx_path = await generate_sfx_track(footage_scenes, roast.estimated_duration)

        # 7. Render cold open + branded intro (use scene durations from Claude)
        jobs[job_id].message = "Step 7/10: Rendering intro..."
        scene_files = []
        cold_open_scene = next((s for s in roast.scenes if s.scene_type == RoastSceneType.COLD_OPEN), None)
        intro_scene = next((s for s in roast.scenes if s.scene_type == RoastSceneType.BRANDED_INTRO), None)
        outro_scene = next((s for s in roast.scenes if s.scene_type == RoastSceneType.OUTRO), None)

        # Cold open: use Runway clip if available, else text-on-black
        cold_open_path = os.path.join("/app/output", f"coldopen_{job_id}.mp4")
        cold_open_dur = cold_open_scene.duration if cold_open_scene else 5.0
        if cold_open_scene and cold_open_scene.scene_id in runway_clips:
            # Runway clip with quote overlay
            await render_roast_clip_scene(
                runway_clips[cold_open_scene.scene_id], cold_open_scene, cold_open_path,
            )
        else:
            await _render_roast_cold_open(
                roast.cold_open_quote or roast.thumbnail_text, cold_open_path,
                duration=cold_open_dur,
            )

        intro_path = os.path.join("/app/output", f"intro_{job_id}.mp4")
        await _render_roast_intro(
            intro_path,
            duration=intro_scene.duration if intro_scene else 5.0,
        )
        scene_files.extend([cold_open_path, intro_path])

        # 8. Render each scene (with per-scene error handling)
        jobs[job_id].message = "Step 8/10: Rendering scenes..."
        total_scenes = len(roast.scenes)
        for idx, scene in enumerate(roast.scenes):
            scene_path = os.path.join("/app/output", f"rs{idx}_{job_id}.mp4")
            clip = footage_paths[idx % len(footage_paths)]
            st = scene.scene_type

            if st in (RoastSceneType.COLD_OPEN, RoastSceneType.BRANDED_INTRO, RoastSceneType.OUTRO):
                continue

            jobs[job_id].message = f"Step 8/10: Rendering scene {idx+1}/{total_scenes} ({st.value})..."

            try:
                if st == RoastSceneType.RATING and 0 <= scene.job_index < len(req.jobs):
                    await render_roast_fullscreen(
                        posting_assets[scene.job_index]["rating"], scene, scene_path,
                    )
                elif st == RoastSceneType.FINAL_RANKING:
                    await render_roast_fullscreen(ranking_png, scene, scene_path)
                elif st == RoastSceneType.TRANSITION:
                    if scene.scene_id in runway_clips:
                        await render_roast_clip_scene(
                            runway_clips[scene.scene_id], scene, scene_path,
                        )
                    else:
                        transition_scene = Scene(
                            duration=scene.duration,
                            b_roll_keywords=scene.b_roll_keywords,
                        )
                        await _render_single_scene(clip, transition_scene, scene_path, 1920, 1080)
                elif 0 <= scene.job_index < len(req.jobs):
                    ji = scene.job_index
                    hl = scene.highlight_section
                    if hl and hl in posting_assets[ji]:
                        posting_png = posting_assets[ji][hl]
                    else:
                        posting_png = posting_assets[ji]["full"]
                    await render_roast_posting_scene(
                        clip, posting_png,
                        posting_assets[ji]["bounds"],
                        scene, scene_path,
                    )
                else:
                    fallback_scene = Scene(
                        duration=scene.duration,
                        b_roll_keywords=scene.b_roll_keywords,
                    )
                    await _render_single_scene(clip, fallback_scene, scene_path, 1920, 1080)

                scene_files.append(scene_path)
            except Exception as e:
                logger.error("Scene %d (%s) failed, skipping: %s", idx, st.value, e)
                continue

        # 9. Render outro
        jobs[job_id].message = "Step 9/10: Rendering outro..."
        outro_path = os.path.join("/app/output", f"outro_{job_id}.mp4")
        await _render_roast_outro(
            outro_path,
            duration=outro_scene.duration if outro_scene else 5.0,
        )
        scene_files.append(outro_path)

        # 10. Compile final video (concat + captions + audio mix)
        jobs[job_id].message = "Step 10/10: Compiling final video..."
        output_path = await render_roast_compilation_v2(
            scene_files=scene_files,
            scenes=roast.scenes,
            audio_path=audio_path,
            captions=captions,
            music_path=music_path,
            sfx_path=sfx_path,
            target_duration=roast.estimated_duration,
        )

        # 11. Generate thumbnail
        jobs[job_id].message = "Generating thumbnail..."
        thumb_text = roast.thumbnail_text or req.category
        thumbnail_path = await generate_thumbnail(
            video_path=output_path, text=thumb_text, topic=req.category,
        )

        result = {
            "video_path": output_path,
            "thumbnail_path": thumbnail_path,
            "script": roast.full_script,
            "scenes_count": len(roast.scenes),
        }

        # 12. Upload single video (no shorts)
        if req.upload:
            jobs[job_id].message = "Uploading to YouTube..."
            yt_title = req.youtube_title or f"JOB ROAST: {req.category}"
            yt_desc = req.youtube_description or roast.full_script[:3000]
            video_id = await upload_to_youtube(
                video_path=output_path, title=yt_title,
                description=yt_desc, tags=req.youtube_tags or ["job roast", "stellenanzeige", "obstkorb"],
            )
            result["youtube_video_id"] = video_id

        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].message = "Roast complete"
        jobs[job_id].result = result

    except Exception as e:
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].message = str(e)


@app.post("/api/roast", response_model=JobResponse)
async def roast(req: RoastRequest, bg: BackgroundTasks):
    """Generate a V4 job roast video — single split-screen video, German."""
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = JobResponse(job_id=job_id, status=JobStatus.PENDING, message="Queued")
    bg.add_task(_run_roast_pipeline, job_id, req)
    return jobs[job_id]


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "flowstack-cinematic-engine", "version": "4.0.0"}
