"""Word-level caption generation using faster-whisper.

Transcribes voiceover audio and returns word-level timestamps
for animated subtitle rendering (MrBeast/Hormozi style).
"""
from __future__ import annotations

import logging

from app.models import WordTimestamp

logger = logging.getLogger(__name__)


async def generate_captions(audio_path: str) -> list[WordTimestamp]:
    """Transcribe audio and return word-level timestamps."""
    import asyncio

    # faster-whisper is CPU-bound, run in executor
    words = await asyncio.get_event_loop().run_in_executor(
        None, _transcribe_sync, audio_path
    )

    logger.info("Generated %d word timestamps from %s", len(words), audio_path)
    return words


def _transcribe_sync(audio_path: str) -> list[WordTimestamp]:
    """Synchronous transcription with faster-whisper."""
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")

    segments, _ = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
    )

    words: list[WordTimestamp] = []
    for segment in segments:
        if segment.words:
            for word_info in segment.words:
                words.append(WordTimestamp(
                    word=word_info.word.strip(),
                    start=round(word_info.start, 3),
                    end=round(word_info.end, 3),
                ))

    return words
