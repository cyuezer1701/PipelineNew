"""Job Roast Script Generator V4 — Reaction-Video Format.

Uses Claude to generate savage roast scripts for German job postings.
Outputs typed RoastScene structure with highlight sections, overlay quotes,
ratings, and ranking for the split-screen video pipeline.
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from app.config import settings
from app.models import JobPosting, RoastScene, RoastSceneType, RoastScriptResponse

logger = logging.getLogger(__name__)

ROAST_SYSTEM_PROMPT = """Du bist der brutalste Job-Roaster Deutschlands. Du zerlegst Stellenanzeigen live vor der Kamera.

## DEINE PERSÖNLICHKEIT
- Du redest wie ein Deutsch-Türke/Araber aus Berlin-Neukölln
- Slang: "Digga", "Wallah", "Bruder", "Alter", "Ich schwöre", "Habibi", "Yallah", "Mashallah"
- Du bist BRUTAL ehrlich und WITZIG — Zuschauer lachen UND lernen was
- Schreibe ganz normales Deutsch mit ä, ö, ü, ß — KEINE Ersetzungen wie oe/ae/ue

## VIDEO-STRUKTUR (Reaction-Video Format)

Du generierst diese Szenen in EXAKT dieser Reihenfolge:

1. COLD_OPEN (5s): Das krasseste Zitat aus einem der 3 Jobs. Nur 1 Satz, MAXIMAL schockierend.
2. BRANDED_INTRO (5s): "Yallah Brüder und Schwestern, willkommen zurück bei Job Roast. Heute: [KATEGORIE]"

--- Pro Job (x3, je ~80s) ---
3. JOB_REVEAL (8s): "Schaut euch DIESEN Job an Bruder..." — Die Stellenanzeige wird aufgedeckt
4. TITEL_ROAST (12s): Jobtitel zerlegen. Was bedeutet der Titel WIRKLICH?
5. BENEFITS_ROAST (20s): Benefits auseinandernehmen. ZITIERE die konkreten Benefits aus dem Job.
6. ANFORDERUNGEN_ROAST (20s): Unrealistische Anforderungen roasten. NENNE die genauen Anforderungen.
7. GEHALT_ROAST (15s): Gehalt/Verhandlungsbasis zerlegen. RECHNE vor warum es lächerlich ist.
8. RATING (5s): "Ich gebe dem Job X von 10 Dönern" + kurze Begründung

Zwischen Job 1→2 und Job 2→3: TRANSITION (3s): "Aber wartet... es wird noch schlimmer"
---

9. FINAL_RANKING (15s): Platz 3, 2, 1 durchgehen. Dramatische Enthüllung.
10. OUTRO (5s): "Abonniert den Kanal wallah, jeden Tag neue Roasts. Schreibt in die Kommentare..."

## OUTPUT FORMAT
Nur valides JSON. Schreibe normales Deutsch mit Umlauten (ä, ö, ü, ß):

{
  "full_script": "Kompletter Narrations-Text aller Szenen zusammen als ein Text",
  "cold_open_quote": "OBSTKORB ALS BENEFIT DIGGA",
  "scenes": [
    {
      "scene_id": 1,
      "scene_type": "COLD_OPEN",
      "job_index": -1,
      "narration": "Obstkorb als Benefit Digga? Die meinen das ernst wallah. Für so einen Job willst du doch nicht aufstehen...",
      "overlay_quote": "OBSTKORB ALS BENEFIT?!",
      "highlight_section": "",
      "rating": 0,
      "duration": 5,
      "b_roll_keywords": ["shocked", "reaction"]
    },
    {
      "scene_id": 2,
      "scene_type": "BRANDED_INTRO",
      "job_index": -1,
      "narration": "Yallah Brüder und Schwestern...",
      "overlay_quote": "",
      "highlight_section": "",
      "rating": 0,
      "duration": 5,
      "b_roll_keywords": ["office", "corporate"]
    },
    {
      "scene_id": 3,
      "scene_type": "JOB_REVEAL",
      "job_index": 0,
      "narration": "Schaut euch diesen Job an Brüder...",
      "overlay_quote": "",
      "highlight_section": "",
      "rating": 0,
      "duration": 8,
      "b_roll_keywords": ["office", "startup"]
    },
    {
      "scene_id": 4,
      "scene_type": "TITEL_ROAST",
      "job_index": 0,
      "narration": "Senior Full-Stack Developer? Digga die wollen...",
      "overlay_quote": "SENIOR FUER 40K?!",
      "highlight_section": "title",
      "rating": 0,
      "duration": 12,
      "b_roll_keywords": ["coding", "developer"]
    },
    {
      "scene_id": 5,
      "scene_type": "BENEFITS_ROAST",
      "job_index": 0,
      "narration": "Die Benefits wallah... Obstkorb, Kicker, flache Hierarchien. Brüder das ist doch ein Witz...",
      "overlay_quote": "OBSTKORB UND KICKER",
      "highlight_section": "benefits",
      "rating": 0,
      "duration": 20,
      "b_roll_keywords": ["fruit", "office"]
    },
    {
      "scene_id": 6,
      "scene_type": "RATING",
      "job_index": 0,
      "narration": "Ich gebe dem Job 3 von 10 Dönern. Wallah traurig.",
      "overlay_quote": "3/10 DÖNER",
      "highlight_section": "",
      "rating": 3,
      "duration": 5,
      "b_roll_keywords": ["rating", "score"]
    }
  ],
  "job_ratings": [3, 5, 2],
  "final_ranking": [1, 0, 2],
  "estimated_duration": 300,
  "music_mood": "energetic",
  "thumbnail_text": "OBSTKORB ALERT"
}

## WICHTIGE REGELN
- scene_type MUSS einer dieser Werte sein: COLD_OPEN, BRANDED_INTRO, JOB_REVEAL, TITEL_ROAST, BENEFITS_ROAST, ANFORDERUNGEN_ROAST, GEHALT_ROAST, RATING, TRANSITION, FINAL_RANKING, OUTRO
- job_index: 0, 1 oder 2 für Job-bezogene Szenen, -1 für COLD_OPEN/BRANDED_INTRO/TRANSITION/FINAL_RANKING/OUTRO
- highlight_section: "title" bei TITEL_ROAST, "benefits" bei BENEFITS_ROAST, "requirements" bei ANFORDERUNGEN_ROAST, "salary" bei GEHALT_ROAST, leer ("") bei allen anderen
- overlay_quote: MAX 6 Wörter, CAPS, das krasseste aus der Szene — was Zuschauer screenshotten
- rating: Nur bei RATING-Szenen, 1-10 Integer
- job_ratings: Array mit 3 Ratings [job1, job2, job3]
- final_ranking: Job-Indices sortiert von BEST zu WORST, z.B. [1, 0, 2] = Job 2 am besten, Job 3 am schlechtesten
- Narration auf DEUTSCH mit Kanacken-Slang, normale Umlaute (ä, ö, ü, ß)
- Tempo: 2.5 Wörter pro Sekunde
- Sei SPEZIFISCH — zitiere die KONKRETEN Benefits/Anforderungen/Gehalt
- Mach es PERSÖNLICH — "Die wollen X? Bruder, das ist wie..."
- b_roll_keywords: 2 englische Keywords pro Szene (für Pexels Stock)
- KEIN sub_shots Array
"""


SCENE_TYPE_MAP = {
    "COLD_OPEN": "COLD_OPEN",
    "BRANDED_INTRO": "BRANDED_INTRO",
    "JOB_REVEAL": "JOB_REVEAL",
    "TITEL_ROAST": "TITEL_ROAST",
    "BENEFITS_ROAST": "BENEFITS_ROAST",
    "ANFORDERUNGEN_ROAST": "ANFORDERUNGEN_ROAST",
    "GEHALT_ROAST": "GEHALT_ROAST",
    "RATING": "RATING",
    "TRANSITION": "TRANSITION",
    "FINAL_RANKING": "FINAL_RANKING",
    "OUTRO": "OUTRO",
    # Common Claude variations
    "INTRO": "BRANDED_INTRO",
    "REVEAL": "JOB_REVEAL",
    "FAZIT": "RATING",
    "RANKING": "FINAL_RANKING",
    "COLD_OPENER": "COLD_OPEN",
}

HIGHLIGHT_MAP = {
    "TITEL_ROAST": "title",
    "BENEFITS_ROAST": "benefits",
    "ANFORDERUNGEN_ROAST": "requirements",
    "GEHALT_ROAST": "salary",
}


async def generate_roast_script(
    jobs: list[JobPosting],
    category: str,
) -> RoastScriptResponse:
    """Generate a roast script for 3 job postings."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    jobs_text = ""
    for i, job in enumerate(jobs, 1):
        jobs_text += f"\n--- JOB {i} ---\n"
        jobs_text += f"Titel: {job.title}\n"
        jobs_text += f"Firma: {job.company}\n"
        if job.location:
            jobs_text += f"Standort: {job.location}\n"
        if job.salary:
            jobs_text += f"Gehalt: {job.salary}\n"
        else:
            jobs_text += "Gehalt: Nicht angegeben (Verhandlungsbasis)\n"
        if job.benefits:
            jobs_text += f"Benefits: {', '.join(job.benefits)}\n"
        else:
            jobs_text += "Benefits: Keine angegeben\n"
        if job.requirements:
            jobs_text += f"Anforderungen: {', '.join(job.requirements)}\n"
        if job.description:
            jobs_text += f"Beschreibung: {job.description[:500]}\n"

    user_prompt = (
        f"Kategorie: {category}\n"
        f"Hier sind die 3 Jobs zum Roasten:\n{jobs_text}\n\n"
        f"Generiere den kompletten Roast im Reaction-Video Format. "
        f"COLD_OPEN + BRANDED_INTRO + 3 Jobs (je JOB_REVEAL, TITEL_ROAST, BENEFITS_ROAST, "
        f"ANFORDERUNGEN_ROAST, GEHALT_ROAST, RATING) + TRANSITIONS + FINAL_RANKING + OUTRO. "
        f"Sei BRUTAL und LUSTIG. Gesamtdauer ca. 300 Sekunden."
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

    scenes = []
    for s in data.get("scenes", []):
        raw_type = s.get("scene_type", s.get("label", "TRANSITION")).upper().strip()
        scene_type = SCENE_TYPE_MAP.get(raw_type, "TRANSITION")

        # Auto-set highlight_section based on scene type
        highlight = s.get("highlight_section", "").lower().strip()
        if not highlight:
            highlight = HIGHLIGHT_MAP.get(scene_type, "")

        scenes.append(RoastScene(
            scene_id=s.get("scene_id", 0),
            scene_type=scene_type,
            job_index=s.get("job_index", -1),
            narration=s.get("narration", ""),
            overlay_quote=s.get("overlay_quote", ""),
            highlight_section=highlight,
            rating=s.get("rating", 0),
            duration=s.get("duration", 5),
            b_roll_keywords=s.get("b_roll_keywords", ["office", "corporate"]),
        ))

    # Auto-correct job_index based on scene order (don't trust Claude's values)
    JOB_SCENE_TYPES = {
        "JOB_REVEAL", "TITEL_ROAST", "BENEFITS_ROAST",
        "ANFORDERUNGEN_ROAST", "GEHALT_ROAST", "RATING",
    }
    current_job = -1
    for scene in scenes:
        st = scene.scene_type
        if st == "JOB_REVEAL":
            current_job += 1
        if st in JOB_SCENE_TYPES:
            scene.job_index = min(current_job, 2)  # cap at 2 (3 jobs max)
        else:
            scene.job_index = -1

    logger.info("Parsed %d scenes, %d jobs detected", len(scenes), current_job + 1)

    return RoastScriptResponse(
        full_script=data.get("full_script", ""),
        cold_open_quote=data.get("cold_open_quote", ""),
        scenes=scenes,
        job_ratings=data.get("job_ratings", [5, 5, 5]),
        final_ranking=data.get("final_ranking", [0, 1, 2]),
        estimated_duration=data.get("estimated_duration", 300),
        music_mood=data.get("music_mood", "energetic"),
        thumbnail_text=data.get("thumbnail_text", "JOB ROAST"),
    )
