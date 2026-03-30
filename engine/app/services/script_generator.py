"""Script generation using Anthropic Claude.

Produces AIDA-structured scripts optimized for 60-second tutorial videos.
"""
from __future__ import annotations

import json
import logging

import anthropic

from app.config import settings
from app.models import ScriptResponse, ScriptSection

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a YouTube script writer specializing in B2B SaaS & AI Automation tutorials.
Write scripts using the AIDA framework:
- Attention (hook, 5-8 seconds)
- Interest (problem statement, 10-15 seconds)
- Desire (solution walkthrough, 30-35 seconds)
- Action (CTA, 5-8 seconds)

Output ONLY valid JSON with this structure:
{
  "script": "Full narration text",
  "sections": [
    {"label": "ATTENTION", "text": "narration text", "overlay_text": "Short overlay", "duration": 7},
    {"label": "INTEREST", "text": "narration text", "overlay_text": "Short overlay", "duration": 13},
    {"label": "DESIRE", "text": "narration text", "overlay_text": "Short overlay", "duration": 33},
    {"label": "ACTION", "text": "narration text", "overlay_text": "Short overlay", "duration": 7}
  ],
  "estimated_duration": 60
}

Rules:
- Total duration must match the target.
- Keep language conversational and concise.
- overlay_text should be 3-6 words max (displayed on screen).
- Approximately 2.5 words per second for narration pacing.
"""


async def generate_script(
    topic: str,
    keywords: list[str],
    target_duration: int = 60,
) -> ScriptResponse:
    """Generate an AIDA-structured video script using Claude."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    user_prompt = (
        f"Topic: {topic}\n"
        f"Keywords: {', '.join(keywords) if keywords else topic}\n"
        f"Target duration: {target_duration} seconds\n"
        f"Write the script now."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    result = response.content[0].text

    return _parse_response(result)


def _parse_response(raw: str) -> ScriptResponse:
    """Parse LLM JSON output into a ScriptResponse."""
    # Strip markdown code fences if present
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
    )
