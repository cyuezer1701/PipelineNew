"""Job Roast Script Generator — brutale Roasts auf Deutsch mit Kanacken-Slang.

Uses Claude to generate savage commentary on German job postings,
systematically destroying ridiculous requirements, pathetic benefits,
and insulting salary offers.
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from app.config import settings
from app.models import JobPosting, RoastScriptResponse, Scene

logger = logging.getLogger(__name__)

ROAST_SYSTEM_PROMPT = """Du bist ein brutaler Job-Roaster mit Kanacken-Slang. Du zerlegst deutsche Stellenanzeigen und machst sie zur Sau.

## DEINE PERSOENLICHKEIT
- Du redest wie ein Deutsch-Tuerke/Araber aus Berlin-Neukoelln
- Slang: "Digga", "Wallah", "Bruder", "Alter", "Ich schwoeroe", "Habibi", "Yallah", "Mashallah"
- Du bist BRUTAL ehrlich, kein Corporate-Filter
- Du bist witzig aber auch informativ — Zuschauer sollen lachen UND was lernen
- Du bewertest jeden Job mit "X von 10 Doenern"
- Keine Apostrophe oder Sonderzeichen in der Ausgabe

## FORMAT PRO JOB
Fuer JEDEN Job generierst du diese Szenen:
1. REVEAL (5s): Kurze Ankuendigung "Schaut euch DAS an..."
2. TITEL_ROAST (10s): Jobtitel zerlegen
3. BENEFITS_ROAST (20s): Benefits auseinandernehmen (Obstkorb, Kicker, etc.)
4. ANFORDERUNGEN_ROAST (20s): Unrealistische Anforderungen roasten
5. GEHALT_ROAST (15s): Gehalt/Verhandlungsbasis zerlegen
6. FAZIT (10s): Bewertung X von 10 Doenern + kurzes Fazit

## UEBERGAENGE ZWISCHEN JOBS
Zwischen den Jobs: "Aber wartet Brueder... es wird noch schlimmer" oder aehnlich.

## INTRO UND OUTRO
- Intro: "Yallah Brueder und Schwestern, willkommen zurueck. Heute haben wir [KATEGORIE]. Ihr werdet nicht glauben was ich gefunden habe."
- Outro nach allen 3 Jobs: Ranking (Platz 3, 2, 1) + "Abonniert wallah, jeden Tag neue Roasts"

## OUTPUT FORMAT
Output NUR valides JSON. KEINE Apostrophe. Nutze "oe" statt "ö", "ae" statt "ä", "ue" statt "ü":

{
  "full_script": "Kompletter Narrations-Text aller Szenen zusammen",
  "job_scripts": [
    "Narration nur fuer Job 1 (fuer den Short)",
    "Narration nur fuer Job 2",
    "Narration nur fuer Job 3"
  ],
  "scenes": [
    {
      "scene_id": 1,
      "label": "INTRO",
      "narration": "Yallah Brueder...",
      "overlay_text": "JOB ROAST",
      "shot_type": "medium",
      "visual_prompt": "office corporate environment",
      "b_roll_keywords": ["office", "corporate"],
      "footage_source": "pexels",
      "duration": 5
    }
  ],
  "job_scene_groups": [[1,2,3,4,5,6], [8,9,10,11,12,13], [15,16,17,18,19,20]],
  "estimated_duration": 300,
  "music_mood": "energetic",
  "thumbnail_text": "OBSTKORB ALERT"
}

## REGELN
- Narration auf DEUTSCH mit Kanacken-Slang
- Tempo: 2.5 Woerter pro Sekunde
- overlay_text: MAX 4 Woerter, CAPS, mit Emoji wenn passend
- b_roll_keywords: 2 Keywords pro Szene (englisch, fuer Pexels)
- Alle footage_source auf "pexels" setzen
- KEINE Apostrophe, KEINE Umlaute (oe/ae/ue statt ö/ä/ü)
- KEIN sub_shots Array (wird automatisch generiert)
- Sei SPEZIFISCH — nenne die konkreten Benefits/Anforderungen aus dem Job
- Mach es PERSOENLICH — "Die wollen X? Bruder, das ist wie..."
"""


async def generate_roast_script(
    jobs: list[JobPosting],
    category: str,
) -> RoastScriptResponse:
    """Generate a roast script for 3 job postings."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    # Format job data for Claude
    jobs_text = ""
    for i, job in enumerate(jobs, 1):
        jobs_text += f"\n--- JOB {i} ---\n"
        jobs_text += f"Titel: {job.title}\n"
        jobs_text += f"Firma: {job.company}\n"
        if job.location:
            jobs_text += f"Standort: {job.location}\n"
        if job.salary:
            jobs_text += f"Gehalt: {job.salary}\n"
        if job.benefits:
            jobs_text += f"Benefits: {', '.join(job.benefits)}\n"
        if job.requirements:
            jobs_text += f"Anforderungen: {', '.join(job.requirements)}\n"
        if job.description:
            jobs_text += f"Beschreibung: {job.description[:500]}\n"

    user_prompt = (
        f"Kategorie: {category}\n"
        f"Hier sind die 3 Jobs zum Roasten:\n{jobs_text}\n\n"
        f"Generiere den kompletten Roast. Sei BRUTAL und LUSTIG. "
        f"Jeder Job bekommt ca. 80 Sekunden Roast. "
        f"Plus Intro (5s), Transitions (3s je), Ranking (15s), Outro (5s). "
        f"Gesamtdauer ca. 300 Sekunden."
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    last_error = None
    for attempt in range(2):
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            system=ROAST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        result = response.content[0].text

        try:
            return _parse_roast_response(result)
        except (json.JSONDecodeError, KeyError, Exception) as e:
            last_error = e
            logger.warning("Roast script parse failed (attempt %d): %s", attempt + 1, e)
            user_prompt += "\n\nWICHTIG: Dein vorheriges JSON war kaputt. Nur valides JSON ausgeben!"

    raise RuntimeError(f"Roast script generation failed: {last_error}")


def _parse_roast_response(raw: str) -> RoastScriptResponse:
    """Parse Claude's roast JSON into RoastScriptResponse."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    # Fix common JSON issues
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    cleaned += ']' * open_brackets + '}' * open_braces

    data = json.loads(cleaned)

    # Normalize shot_type values from Claude (e.g. "close" → "close_up")
    SHOT_TYPE_MAP = {
        "close": "close_up", "closeup": "close_up", "close-up": "close_up",
        "wide": "wide", "medium": "medium", "establishing": "establishing",
        "detail": "detail", "over_shoulder": "over_shoulder",
        "over-shoulder": "over_shoulder", "pov": "over_shoulder",
    }

    scenes = []
    for s in data.get("scenes", []):
        raw_shot = s.get("shot_type", "medium").lower().strip()
        shot_type = SHOT_TYPE_MAP.get(raw_shot, "medium")

        scenes.append(Scene(
            scene_id=s.get("scene_id", 0),
            label=s.get("label", ""),
            narration=s.get("narration", ""),
            overlay_text=s.get("overlay_text", ""),
            shot_type=shot_type,
            visual_prompt=s.get("visual_prompt", ""),
            b_roll_keywords=s.get("b_roll_keywords", ["office", "corporate"]),
            footage_source="pexels",
            duration=s.get("duration", 5),
        ))

    return RoastScriptResponse(
        full_script=data.get("full_script", ""),
        job_scripts=data.get("job_scripts", []),
        scenes=scenes,
        job_scene_groups=data.get("job_scene_groups", []),
        estimated_duration=data.get("estimated_duration", 300),
        music_mood=data.get("music_mood", "energetic"),
        thumbnail_text=data.get("thumbnail_text", "JOB ROAST"),
    )
