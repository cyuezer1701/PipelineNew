from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerateRequest(BaseModel):
    topic: str = Field(..., description="Video topic / title")
    keywords: list[str] = Field(default_factory=list, description="SEO keywords for footage search")
    target_duration: int = Field(default=60, description="Target video length in seconds")
    upload: bool = Field(default=False, description="Auto-upload to YouTube after rendering")
    youtube_title: Optional[str] = None
    youtube_description: Optional[str] = None
    youtube_tags: list[str] = Field(default_factory=list)


class ScriptRequest(BaseModel):
    topic: str
    keywords: list[str] = Field(default_factory=list)
    target_duration: int = Field(default=60)


class ScriptResponse(BaseModel):
    script: str
    sections: list[ScriptSection]
    estimated_duration: int


class ScriptSection(BaseModel):
    label: str
    text: str
    overlay_text: str = ""
    duration: int = 10


class RenderRequest(BaseModel):
    script: ScriptResponse
    audio_path: str
    footage_paths: list[str]


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = ""
    result: Optional[dict] = None
