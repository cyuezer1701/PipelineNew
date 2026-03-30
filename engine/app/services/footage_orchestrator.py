"""Footage orchestrator — routes scenes to Runway or Pexels.

Implements the 70/30 AI-to-real footage mixing ratio to break the
AI visual fingerprint while maintaining cinematic quality.
"""
from __future__ import annotations

import logging
import random

from app.config import settings
from app.models import FootageSource, Scene
from app.services.runway_generator import generate_runway_footage
from app.services.stock_footage import download_footage_for_sections

logger = logging.getLogger(__name__)


async def orchestrate_footage(
    scenes: list[Scene],
    character_ref: str | None = None,
) -> list[str]:
    """Route each scene to Runway or Pexels based on footage_source.

    Returns: Ordered list of local video paths (one per scene).
    Fallback: If Runway fails for a scene, falls back to Pexels.
    """
    # Resolve 'mixed' sources based on runway_footage_ratio
    resolved_scenes = _resolve_mixed_sources(scenes)

    runway_scenes = [s for s in resolved_scenes if s.footage_source == FootageSource.RUNWAY]
    pexels_scenes = [s for s in resolved_scenes if s.footage_source == FootageSource.PEXELS]

    # Generate footage from both sources
    runway_results: dict[int, str] = {}
    pexels_results: dict[int, str] = {}

    # Runway footage (if API key configured and scenes need it)
    if runway_scenes and settings.runway_api_key:
        try:
            runway_results = await generate_runway_footage(
                scenes=runway_scenes,
                character_ref=character_ref,
            )
        except Exception as e:
            logger.warning("Runway generation failed, falling back to Pexels: %s", e)
            pexels_scenes.extend(runway_scenes)
            runway_scenes = []

    # Fallback: any Runway scene that failed goes to Pexels
    failed_runway = [s for s in runway_scenes if s.scene_id not in runway_results]
    if failed_runway:
        logger.info("Falling back to Pexels for %d failed Runway scenes", len(failed_runway))
        pexels_scenes.extend(failed_runway)

    # Pexels footage for remaining scenes
    if pexels_scenes:
        pexels_paths = await download_footage_for_sections(pexels_scenes)
        for scene, path in zip(pexels_scenes, pexels_paths):
            pexels_results[scene.scene_id] = path

    # Assemble in scene order
    all_results = {**runway_results, **pexels_results}
    ordered_paths: list[str] = []
    fallback_path: str | None = None

    for scene in scenes:
        path = all_results.get(scene.scene_id)
        if path:
            ordered_paths.append(path)
            fallback_path = path
        elif fallback_path:
            ordered_paths.append(fallback_path)  # reuse last successful clip
        else:
            raise RuntimeError(f"No footage available for scene {scene.scene_id}")

    runway_count = sum(1 for s in resolved_scenes if s.footage_source == FootageSource.RUNWAY and s.scene_id in runway_results)
    pexels_count = len(ordered_paths) - runway_count
    logger.info("Footage mix: %d Runway / %d Pexels (%.0f%% AI)",
                runway_count, pexels_count,
                runway_count / max(1, len(ordered_paths)) * 100)

    return ordered_paths


def _resolve_mixed_sources(scenes: list[Scene]) -> list[Scene]:
    """Resolve MIXED footage sources to either RUNWAY or PEXELS."""
    resolved = []
    for scene in scenes:
        if scene.footage_source == FootageSource.MIXED:
            if settings.runway_api_key and random.random() < settings.runway_footage_ratio:
                scene = scene.model_copy(update={"footage_source": FootageSource.RUNWAY})
            else:
                scene = scene.model_copy(update={"footage_source": FootageSource.PEXELS})
        resolved.append(scene)
    return resolved
