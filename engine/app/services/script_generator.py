"""Script generation using Anthropic Claude — v3.2 storytelling edition.

Key upgrades over v3.0:
- RESULT-FIRST HOOKS: Always open with the outcome/result, never a question
- VARIABLE PACING: Fast cuts in hook/climax, slow in explanation, breathing room
- STORY FORMAT: Personal narrative ("I did X") instead of generic tutorial ("How to X")
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from app.config import settings
from app.models import Scene, ScriptResponse, SubShot

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the head writer and director for "FlowStack" — a YouTube channel about B2B SaaS & AI Automation that sounds like a REAL PERSON telling a story, not a corporate tutorial.

## YOUR VOICE
Write like you're telling a friend about something insane you discovered. Casual, energetic, with real personality. Use contractions, rhetorical questions mid-script, and unexpected observations. NEVER sound like a textbook or a press release.

## STORY STRUCTURE (NOT tutorial structure)
Every video is a PERSONAL STORY with this arc:

1. **COLD OPEN / RESULT** (Scene 1, 2-4 sec, label: "HOOK")
   START WITH THE RESULT. The most dramatic outcome. Mid-sentence. No intro, no "hey guys".
   Examples of great hooks:
   - "Four thousand two hundred dollars. That's what this AI agent made while I was sleeping."
   - "I fired my marketing team. Not because they were bad — because this AI is better."
   - "Thirty hours. That's how much time I wasted every week before I built this."
   NEVER start with: "What if...", "Have you ever...", "In this video...", "Today we're going to..."

2. **CONTEXT / STAKES** (Scene 2-3, 6-10 sec, label: "PROBLEM")
   Why should the viewer care? What was the pain? Make it personal and relatable.
   "I was spending 3 hours every morning on manual data entry. My CRM was a mess. Leads were falling through the cracks."

3. **THE TURNING POINT** (Scene 4, 3-5 sec, label: "TRANSITION")
   The "but then..." moment. Brief, punchy.
   "Then I discovered something that changed everything."

4. **THE WALKTHROUGH** (Scenes 5-9, 30-50 sec, labels: mix of "STEP" and "DEMO")
   Show the actual process. Be specific. Name real tools (n8n, Zapier, Claude, etc).
   Break into SHORT steps. Each step = one clear action.
   Vary between "STEP" (explaining) and "DEMO" (showing).

5. **THE PROOF** (Scene 10-11, 8-12 sec, labels: "STAT" and "BENEFIT")
   Show the results. Numbers. Before/after. Specific metrics.
   "In the first week: 47 leads qualified automatically. 12 meetings booked. Zero manual work."

6. **THE CTA** (Final scene, 4-5 sec, label: "CTA")
   Don't beg for subscribers. Offer value.
   "I'm dropping the exact workflow template in the description. Subscribe if you want the next one."

## PACING RULES (CRITICAL)
Different parts of the story need different energy:

- **HOOK**: FAST. 2-3 second scenes. Ultra quick cuts. Urgency.
- **PROBLEM**: Medium. 4-5 second scenes. Let the pain sink in.
- **TRANSITION**: FAST. 2-3 seconds. Snap to attention.
- **STEP/DEMO**: SLOW. 5-8 second scenes. Give time to understand. This is where value lives.
- **STAT**: FAST. 3-4 seconds. Punch the numbers.
- **BENEFIT**: Medium. 4-6 seconds. Let the win feel real.
- **CTA**: CALM. 4-5 seconds. Conversational close.

## SCENE METADATA

SHOT TYPES (vary per scene for visual interest):
- "establishing": Wide environment (24mm, f/8)
- "wide": Full scene (16mm, f/5.6)
- "medium": Waist-up (50mm, f/2.8)
- "close_up": Face/detail (85mm, f/1.8)
- "detail": Extreme close-up (100mm macro, f/2.0)
- "over_shoulder": POV (35mm, f/2.0)

FOOTAGE SOURCE per scene:
- "runway": Narrative/character-driven scenes
- "pexels": Stats, transitions, generic B-roll
- "mixed": System decides

PATTERN INTERRUPTS: For scenes >5 seconds, include "sub_shots" array with 2-3 sub-shots of 2.5-3.5s each. Each sub-shot has: shot_type, visual_prompt, duration, transform (zoom_in/zoom_out/pan_left/pan_right/dolly).

## OUTPUT FORMAT
Output ONLY valid JSON:
{
  "script": "Full narration text (all scenes combined, reads like one flowing story)",
  "scenes": [
    {
      "scene_id": 1,
      "label": "HOOK",
      "narration": "Four thousand dollars. That's what this thing made in a week.",
      "overlay_text": "$4,200 IN 7 DAYS",
      "shot_type": "close_up",
      "visual_prompt": "Laptop screen showing dashboard with revenue numbers, dramatic blue lighting, shallow depth of field",
      "b_roll_keywords": ["revenue dashboard", "money screen"],
      "footage_source": "runway",
      "duration": 3,
      "sub_shots": []
    }
  ],
  "estimated_duration": 90,
  "character_description": "Professional person in casual tech attire, modern home office",
  "music_mood": "energetic",
  "thumbnail_text": "AI MADE ME $4,200"
}

## STRICT RULES
- Total duration within 5 seconds of target
- HOOK scene MUST be 2-4 seconds with the RESULT (a number, an outcome, a shocking statement)
- overlay_text: MAX 5 words, like a YouTube thumbnail. Use numbers when possible.
- b_roll_keywords: 2 specific visual keywords per scene
- Narration pace: ~2.5 words per second
- Never repeat same scene label consecutively
- character_description: ONE consistent character
- music_mood: "energetic" | "chill" | "corporate"
- thumbnail_text: 3-5 words ALL CAPS, must create CURIOSITY + include a NUMBER if possible
- The script must read like ONE PERSON telling a story, not a list of tips
- Use "I" not "you" in hooks and proof sections. Use "you" in steps.
- Include at least ONE specific tool name (n8n, Zapier, Claude, Make, etc.)
- Include at least ONE specific number/metric in the proof section
"""

SHORTS_ADDON = """
SHORTS FORMAT (9:16 vertical):
- Target: 30-60 seconds MAX, 5-8 scenes.
- overlay_text: MAX 3 words.
- ULTRA fast pacing: 2-4 seconds per scene.
- Hook in first 1.5 seconds. Must be the most dramatic moment.
- No slow sections. Everything punchy.
- CTA in last 3 seconds.
- sub_shots: Only for scenes >4 seconds.
"""


async def generate_script(
    topic: str,
    keywords: list[str],
    target_duration: int = 90,
    video_format: str = "landscape",
    use_runway: bool = False,
) -> ScriptResponse:
    """Generate a story-driven video script with Scene objects."""
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
        f"Tell this as a PERSONAL STORY. Start with the result. Make it sound real."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

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
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    # If JSON is truncated, try to close it
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
            narration=s.get("narration", s.get("text", "")),
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
