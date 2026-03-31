from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ShotType(str, Enum):
    ESTABLISHING = "establishing"
    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE_UP = "close_up"
    DETAIL = "detail"
    OVER_SHOULDER = "over_shoulder"


class FootageSource(str, Enum):
    RUNWAY = "runway"
    PEXELS = "pexels"
    MIXED = "mixed"


# ── Sub-shot (Pattern Interrupt unit) ──────────────────────

class SubShot(BaseModel):
    """A 2.5-3.5 second sub-shot within a scene for pattern interrupts."""
    shot_type: ShotType = ShotType.MEDIUM
    visual_prompt: str = ""
    duration: float = 3.0
    transform: str = "zoom_in"  # zoom_in, zoom_out, pan_left, pan_right, dolly


# ── Scene (replaces ScriptSection) ─────────────────────────

class Scene(BaseModel):
    """A single scene in the video with cinematic metadata."""
    scene_id: int = 0
    label: str = ""
    narration: str = ""
    overlay_text: str = ""
    shot_type: ShotType = ShotType.MEDIUM
    visual_prompt: str = ""
    b_roll_keywords: list[str] = Field(default_factory=list)
    footage_source: FootageSource = FootageSource.MIXED
    duration: float = 5.0
    sub_shots: list[SubShot] = Field(default_factory=list)


# Backward compatibility alias
ScriptSection = Scene


# ── Requests ───────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = Field(..., description="Video topic / title")
    keywords: list[str] = Field(default_factory=list, description="SEO keywords")
    target_duration: int = Field(default=90, description="Target video length in seconds")
    video_format: Literal["landscape", "shorts"] = Field(default="landscape")
    upload: bool = Field(default=False, description="Auto-upload to YouTube")
    youtube_title: Optional[str] = None
    youtube_description: Optional[str] = None
    youtube_tags: list[str] = Field(default_factory=list)
    # v3.0 additions
    guide_audio_url: Optional[str] = Field(default=None, description="Guide audio for STS mode")
    use_runway: bool = Field(default=True, description="Use Runway Gen-4.5 for AI footage")
    runway_character_ref: Optional[str] = Field(default=None, description="Character reference image URL")


class ScriptRequest(BaseModel):
    topic: str
    keywords: list[str] = Field(default_factory=list)
    target_duration: int = Field(default=90)
    video_format: Literal["landscape", "shorts"] = "landscape"
    use_runway: bool = False


# ── Responses ──────────────────────────────────────────────

class ScriptResponse(BaseModel):
    script: str
    scenes: list[Scene]
    estimated_duration: int
    music_mood: str = "energetic"
    thumbnail_text: str = ""
    character_description: str = ""

    @property
    def sections(self) -> list[Scene]:
        """Backward compatibility alias."""
        return self.scenes


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class RenderRequest(BaseModel):
    script: ScriptResponse
    audio_path: str
    footage_paths: list[str]


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = ""
    result: Optional[dict] = None


# ── Job Roast Models ──────────────────────────────────────

class RoastSceneType(str, Enum):
    COLD_OPEN = "COLD_OPEN"
    BRANDED_INTRO = "BRANDED_INTRO"
    JOB_REVEAL = "JOB_REVEAL"
    TITEL_ROAST = "TITEL_ROAST"
    BENEFITS_ROAST = "BENEFITS_ROAST"
    ANFORDERUNGEN_ROAST = "ANFORDERUNGEN_ROAST"
    GEHALT_ROAST = "GEHALT_ROAST"
    RATING = "RATING"
    TRANSITION = "TRANSITION"
    FINAL_RANKING = "FINAL_RANKING"
    OUTRO = "OUTRO"


class JobPosting(BaseModel):
    """A single job posting to be roasted."""
    title: str = Field(..., description="Job title, e.g. 'Senior Full-Stack Developer (m/w/d)'")
    company: str = Field(..., description="Company name")
    location: str = ""
    salary: str = ""
    benefits: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    description: str = ""


class RoastScene(BaseModel):
    """A single scene in the roast video with typed metadata."""
    scene_id: int = 0
    scene_type: RoastSceneType = RoastSceneType.TRANSITION
    job_index: int = -1  # Which job (0,1,2) or -1 for non-job scenes
    narration: str = ""
    overlay_quote: str = ""  # Big roast quote overlay (max 6 words, CAPS)
    highlight_section: str = ""  # "title", "benefits", "requirements", "salary", ""
    rating: int = 0  # X/10 doener rating (only for RATING scenes)
    duration: float = 5.0
    b_roll_keywords: list[str] = Field(default_factory=list)


class RoastRequest(BaseModel):
    """Request to generate a job roast video."""
    jobs: list[JobPosting] = Field(..., description="3 job postings to roast")
    category: str = Field(default="Die schlimmsten Stellenanzeigen", description="Video category/theme")
    upload: bool = False
    youtube_title: Optional[str] = None
    youtube_description: Optional[str] = None
    youtube_tags: list[str] = Field(default_factory=list)


class RoastScriptResponse(BaseModel):
    """Roast script with scene structure for V4 pipeline."""
    full_script: str
    cold_open_quote: str = ""  # Most shocking quote for hook
    scenes: list[RoastScene]
    job_ratings: list[int] = Field(default_factory=list)  # [7, 3, 5] per job
    final_ranking: list[int] = Field(default_factory=list)  # Job indices ranked [2, 0, 1]
    estimated_duration: int = 300
    music_mood: str = "energetic"
    thumbnail_text: str = ""

