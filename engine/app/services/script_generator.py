"""Script generation using Anthropic Claude — v3.0 cinematic edition.

Produces Scene objects with cinematic shot types, visual prompts enriched
with lens data, pattern interrupt sub-shots, and footage source routing.
"""
from __future__ import annotations

import json
import logging

import anthropic

from app.config import settings
from app.models import Scene, ScriptResponse, SubShot

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite YouTube video director and script writer for the channel "FlowStack" — specializing in B2B SaaS & AI Automation tutorials.

You think like a CINEMATOGRAPHER: every scene has a specific shot type, camera lens, and lighting setup. You think like an EDITOR: fast cuts, pattern interrupts, visual variety.

STRUCTURE: Create 8-15 scenes for landscape, 5-8 for shorts. Each scene 3-8 seconds.

SCENE TYPES (mix for variety, never consecutive):
- HOOK: Attention-grabbing opener (3-5 sec)
- PROBLEM: Pain point with relatable visuals (4-6 sec)
- STAT: Data/statistic with impactful number overlay (3-4 sec)
- STEP: Tutorial step with action-oriented overlay (5-8 sec)
- DEMO: Show tool/process in action (5-8 sec)
- BENEFIT: Result/outcome highlight (4-6 sec)
- TRANSITION: Brief bridge between ideas (2-3 sec)
- CTA: Call to action (4-5 sec)

SHOT TYPES (vary per scene):
- "establishing": Wide environment shot (24mm lens, f/8)
- "wide": Full scene view (16mm lens, f/5.6)
- "medium": Waist-up or mid-range (50mm lens, f/2.8)
- "close_up": Face or detail focus (85mm lens, f/1.8)
- "detail": Extreme close-up on object (100mm macro, f/2.0)
- "over_shoulder": POV-style shot (35mm lens, f/2.0)

FOOTAGE SOURCE per scene:
- "runway": Narrative scenes, character-driven, demos (AI-generated)
- "pexels": Stats, transitions, generic B-roll (real stock footage)
- "mixed": Let the system decide

PATTERN INTERRUPTS: For scenes >5 seconds, include "sub_shots" — 2-3 sub-shots of 2.5-3.5s each with different shot types and transforms. Transforms: "zoom_in", "zoom_out", "pan_left", "pan_right", "dolly".

Output ONLY valid JSON:
{
  "script": "Full narration text",
  "scenes": [
    {
      "scene_id": 1,
      "label": "HOOK",
      "narration": "Narration for this scene",
      "overlay_text": "3-5 WORD TEXT",
      "shot_type": "close_up",
      "visual_prompt": "Professional person looking at camera with surprised expression, modern office, warm lighting",
      "b_roll_keywords": ["surprised person", "office reaction"],
      "footage_source": "runway",
      "duration": 5,
      "sub_shots": [
        {"shot_type": "close_up", "visual_prompt": "Face reaction close-up, dramatic lighting", "duration": 2.5, "transform": "zoom_in"},
        {"shot_type": "medium", "visual_prompt": "Person gesturing at screen, soft key light", "duration": 2.5, "transform": "pan_left"}
      ]
    }
  ],
  "estimated_duration": 90,
  "character_description": "Professional man, 30s, dark hair, wearing navy blazer, modern office setting",
  "music_mood": "energetic",
  "thumbnail_text": "THIS CHANGES EVERYTHING"
}

RULES:
- Total duration within 5 seconds of target.
- visual_prompt: ALWAYS include lighting, environment, and action details. Be specific and visual.
- overlay_text: MAX 5 words (3 for shorts), punchy, like a YouTube thumbnail.
- b_roll_keywords: 2 specific visual keywords per scene (for Pexels fallback).
- Narration pace: ~2.5 words per second.
- Never use same scene type twice in a row.
- character_description: Describe ONE consistent character for the entire video.
- music_mood: "energetic", "chill", or "corporate".
- thumbnail_text: 3-5 word CLICKBAIT in ALL CAPS.
- HOOK/PROBLEM/DEMO → footage_source "runway" (character-driven).
- STAT/TRANSITION → footage_source "pexels" (real footage).
- STEP/BENEFIT/CTA → footage_source "mixed".
- sub_shots: Only for scenes >5 seconds. Vary shot_type and transform.
"""

SHORTS_ADDON = """
SHORTS FORMAT (9:16 vertical):
- Target: 30-60 seconds MAX, 5-8 scenes, 3-5s each.
- overlay_text: MAX 3 words.
- Hook in first 2 seconds. CTA in last 3 seconds.
- Every word counts — be extremely concise.
- sub_shots: Only for scenes >4 seconds.
"""


async def generate_script(
    topic: str,
    keywords: list[str],
    target_duration: int = 90,
    video_format: str = "landscape",
    use_runway: bool = False,
) -> ScriptResponse:
    """Generate a cinematic video script with Scene objects."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    system = SYSTEM_PROMPT
    if video_format == "shorts":
        system += SHORTS_ADDON
        target_duration = min(target_duration, 60)

    if not use_runway:
        system += "\nIMPORTANT: Set ALL footage_source to 'pexels' (Runway not available).\n"

    scene_min = 5 if video_format == "shorts" else max(8, target_duration // 8)
    scene_max = 8 if video_format == "shorts" else target_duration // 5

    user_prompt = (
        f"Topic: {topic}\n"
        f"Keywords: {', '.join(keywords) if keywords else topic}\n"
        f"Target duration: {target_duration} seconds\n"
        f"Format: {video_format}\n"
        f"Create {scene_min}-{scene_max} scenes.\n"
        f"Write the script now."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Try up to 2 times if JSON parsing fails
    last_error = None
    for attempt in range(2):
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=6000,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = response.content[0].text

        try:
            return _parse_response(result)
        except (json.JSONDecodeError, KeyError) as e:
            last_error = e
            logger.warning("Script parse failed (attempt %d): %s", attempt + 1, e)
            user_prompt += "\n\nIMPORTANT: Your previous response had invalid JSON. Output ONLY valid JSON, no trailing commas, no comments."

    raise RuntimeError(f"Script generation failed after 2 attempts: {last_error}")


def _parse_response(raw: str) -> ScriptResponse:
    """Parse LLM JSON output into ScriptResponse with Scene objects."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    # Fix common JSON issues from LLMs
    # Remove trailing commas before } or ]
    import re
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    # If JSON is truncated (no closing brackets), try to fix
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    cleaned += ']' * open_brackets + '}' * open_braces

    data = json.loads(cleaned)

    scenes = []
    for s in data["scenes"]:
        sub_shots = [SubShot(**ss) for ss in s.get("sub_shots", [])]
        scene = Scene(
            scene_id=s.get("scene_id", 0),
            label=s.get("label", ""),
            narration=s.get("narration", s.get("text", "")),  # backward compat
            overlay_text=s.get("overlay_text", ""),
            shot_type=s.get("shot_type", "medium"),
            visual_prompt=s.get("visual_prompt", ""),
            b_roll_keywords=s.get("b_roll_keywords", []),
            footage_source=s.get("footage_source", "mixed"),
            duration=s.get("duration", 5),
            sub_shots=sub_shots,
        )
        scenes.append(scene)

    return ScriptResponse(
        script=data["script"],
        scenes=scenes,
        estimated_duration=data.get("estimated_duration", sum(s.duration for s in scenes)),
        music_mood=data.get("music_mood", "energetic"),
        thumbnail_text=data.get("thumbnail_text", ""),
        character_description=data.get("character_description", ""),
    )
