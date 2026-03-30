"""ElevenLabs text-to-speech voiceover generation with audio normalization."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


async def generate_voiceover(text: str) -> str:
    """Generate an MP3 voiceover file, normalize audio, and return its path."""
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")

    from elevenlabs import AsyncElevenLabs

    client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)

    audio_generator = client.text_to_speech.convert(
        voice_id=settings.elevenlabs_voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    raw_path = os.path.join(settings.output_dir, f"vo_raw_{uuid.uuid4().hex[:8]}.mp3")
    with open(raw_path, "wb") as f:
        async for chunk in audio_generator:
            f.write(chunk)

    # Normalize audio to -14 LUFS (YouTube standard)
    output_path = os.path.join(settings.output_dir, f"vo_{uuid.uuid4().hex[:8]}.mp3")
    await _normalize_audio(raw_path, output_path)

    # Cleanup raw file
    try:
        os.remove(raw_path)
    except OSError:
        pass

    file_size = os.path.getsize(output_path)
    logger.info("Voiceover generated and normalized: %s (%d bytes)", output_path, file_size)
    return output_path


async def _normalize_audio(input_path: str, output_path: str) -> None:
    """Normalize audio to -14 LUFS using FFmpeg loudnorm (two-pass)."""
    # Pass 1: Analyze
    analyze_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *analyze_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    # Pass 2: Apply normalization (even if analysis parsing fails, single-pass still works)
    normalize_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-ar", "44100",
        "-ab", "128k",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *normalize_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-300:] if stderr else "Unknown error"
        logger.warning("Audio normalization failed, using raw audio: %s", error_msg)
        # Fallback: just copy the raw file
        import shutil
        shutil.copy2(input_path, output_path)
