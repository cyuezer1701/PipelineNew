"""Script generation using Anthropic Claude.

Produces richly-structured scripts with 8-15 scenes, music mood selection,
thumbnail text, and support for both landscape and shorts formats.
"""
from __future__ import annotations

import json
import logging

import anthropic

from app.config import settings
from app.models import ScriptResponse, ScriptSection

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite YouTube script writer and video director for the channel "FlowStack" — specializing in B2B SaaS & AI Automation tutorials.

You write scripts that feel like a human editor cut them — fast-paced, visually dynamic, and engaging.
Think MrBeast pacing meets tech tutorial value.

STRUCTURE: Create 8-15 short scenes (3-8 seconds each). Each scene gets its own b-roll footage.
Quick cuts, variety, and visual storytelling.

Scene types to mix:
- HOOK: Attention-grabbing opener (3-5 sec)
- PROBLEM: Pain point with relatable visuals (4-6 sec)
- STAT: Data/statistic with impactful number overlay (3-4 sec)
- STEP: Tutorial step with action-oriented overlay (5-8 sec)
- DEMO: Show the tool/process in action (5-8 sec)
- BENEFIT: Result/outcome highlight (4-6 sec)
- TRANSITION: Brief bridge between ideas (2-3 sec)
- CTA: Call to action (4-5 sec)

Output ONLY valid JSON with this exact structure:
{
  "script": "Full narration text (all scenes combined)",
  "sections": [
    {
      "label": "HOOK",
      "text": "What you'll narrate for this scene",
      "overlay_text": "3-5 word text shown on screen",
      "b_roll_keywords": ["keyword1", "keyword2"],
      "duration": 5
    }
  ],
  "estimated_duration": 90,
  "music_mood": "energetic",
  "thumbnail_text": "3-5 WORD THUMBNAIL TEXT"
}

RULES:
- Total duration must be close to the target (within 5 seconds).
- Each scene MUST have 2 different b_roll_keywords for stock footage search.
- overlay_text: MAX 5 words, punchy, like a YouTube thumbnail.
- Narration pace: ~2.5 words per second.
- Mix scene types for visual variety — never use the same type twice in a row.
- b_roll_keywords should be specific and visual (e.g. "person typing laptop" not "technology").
- Make it sound natural, energetic, like a real YouTuber — not corporate.
- Include at least one surprising stat or counterintuitive insight.
- music_mood: choose ONE from "energetic", "chill", "corporate" — match the video vibe.
- thumbnail_text: Write a 3-5 word CLICKBAIT thumbnail text in ALL CAPS. Must create curiosity.
  Examples: "THIS CHANGES EVERYTHING", "STOP DOING THIS", "5X FASTER WITH AI"
"""

SHORTS_PROMPT_ADDON = """
SHORTS FORMAT: This is a YouTube Short (vertical 9:16 video).
- Target duration: 30-60 seconds MAX
- Create 5-8 scenes (shorter, punchier)
- Each scene 3-5 seconds max
- overlay_text: MAX 3 words (bigger text on mobile)
- Hook MUST grab attention in first 2 seconds
- End with strong CTA in last 3 seconds
- Be extremely concise — every word counts
"""


async def generate_script(
    topic: str,
    keywords: list[str],
    target_duration: int = 90,
    video_format: str = "landscape",
) -> ScriptResponse:
    """Generate a richly-structured video script using Claude."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    system = SYSTEM_PROMPT
    if video_format == "shorts":
        system += SHORTS_PROMPT_ADDON
        target_duration = min(target_duration, 60)

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
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    result = response.content[0].text

    return _parse_response(result)


def _parse_response(raw: str) -> ScriptResponse:
    """Parse LLM JSON output into a ScriptResponse."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    sections = [ScriptSection(**s) for s in data["sections"]]
    return ScriptResponse(
        script=data["script"],
        sections=sections,
        estimated_duration=data.get("estimated_duration", sum(s.duration for s in sections)),
        music_mood=data.get("music_mood", "energetic"),
        thumbnail_text=data.get("thumbnail_text", ""),
    )
