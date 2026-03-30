"""ElevenLabs text-to-speech voiceover generation."""
from __future__ import annotations

import logging
import os
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


async def generate_voiceover(text: str) -> str:
    """Generate an MP3 voiceover file and return its path."""
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")

    from elevenlabs import AsyncElevenLabs

    client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)

    audio_generator = await client.text_to_speech.convert(
        voice_id=settings.elevenlabs_voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    # Collect audio chunks
    output_path = os.path.join(settings.output_dir, f"vo_{uuid.uuid4().hex[:8]}.mp3")
    with open(output_path, "wb") as f:
        async for chunk in audio_generator:
            f.write(chunk)

    file_size = os.path.getsize(output_path)
    logger.info("Voiceover generated: %s (%d bytes)", output_path, file_size)
    return output_path
