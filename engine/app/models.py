from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerateRequest(BaseModel):
    topic: str = Field(..., description="Video topic / title")
    keywords: list[str] = Field(default_factory=list, description="SEO keywords for footage search")
    target_duration: int = Field(default=90, description="Target video length in seconds")
    video_format: Literal["landscape", "shorts"] = Field(default="landscape", description="landscape (16:9) or shorts (9:16)")
    upload: bool = Field(default=False, description="Auto-upload to YouTube after rendering")
    youtube_title: Optional[str] = None
    youtube_description: Optional[str] = None
    youtube_tags: list[str] = Field(default_factory=list)


class ScriptRequest(BaseModel):
    topic: str
    keywords: list[str] = Field(default_factory=list)
    target_duration: int = Field(default=90)
    video_format: Literal["landscape", "shorts"] = "landscape"


class ScriptSection(BaseModel):
    label: str
    text: str
    overlay_text: str = ""
    b_roll_keywords: list[str] = Field(default_factory=list)
    duration: int = 5


class ScriptResponse(BaseModel):
    script: str
    sections: list[ScriptSection]
    estimated_duration: int
    music_mood: str = "energetic"
    thumbnail_text: str = ""


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
