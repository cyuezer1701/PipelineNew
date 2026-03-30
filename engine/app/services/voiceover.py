"""ElevenLabs voiceover — Text-to-Speech and Speech-to-Speech modes.

TTS: Standard text-to-speech (default when no guide audio provided).
STS: Speech-to-Speech — takes a human guide recording and re-voices it
     with a professional AI voice, preserving micro-rhythms and emotion.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


async def generate_voiceover(
    text: str,
    guide_audio_path: str | None = None,
) -> str:
    """Generate voiceover using TTS or STS mode, then normalize audio.

    Args:
        text: Script text for TTS mode.
        guide_audio_path: Path to guide audio for STS mode.
            If provided, uses Speech-to-Speech API instead of TTS.
    """
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not configured")

    from elevenlabs import AsyncElevenLabs

    client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)

    raw_path = os.path.join(settings.output_dir, f"vo_raw_{uuid.uuid4().hex[:8]}.mp3")

    if guide_audio_path and os.path.exists(guide_audio_path):
        # Speech-to-Speech mode: re-voice guide audio with AI voice
        logger.info("Using STS mode with guide: %s", guide_audio_path)
        audio_generator = client.speech_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            audio=open(guide_audio_path, "rb"),
            model_id=settings.elevenlabs_sts_model,
            output_format="mp3_44100_128",
        )
    else:
        # Standard TTS mode
        logger.info("Using TTS mode")
        audio_generator = client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

    with open(raw_path, "wb") as f:
        async for chunk in audio_generator:
            f.write(chunk)

    # Normalize audio to -14 LUFS (YouTube standard)
    output_path = os.path.join(settings.output_dir, f"vo_{uuid.uuid4().hex[:8]}.mp3")
    await _normalize_audio(raw_path, output_path)

    _safe_remove(raw_path)

    file_size = os.path.getsize(output_path)
    logger.info("Voiceover generated and normalized: %s (%d bytes)", output_path, file_size)
    return output_path


async def _normalize_audio(input_path: str, output_path: str) -> None:
    """Normalize audio to -14 LUFS using FFmpeg loudnorm."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-ar", "44100", "-ab", "128k",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode()[-300:] if stderr else "Unknown error"
        logger.warning("Audio normalization failed, using raw audio: %s", error_msg)
        import shutil
        shutil.copy2(input_path, output_path)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
