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
