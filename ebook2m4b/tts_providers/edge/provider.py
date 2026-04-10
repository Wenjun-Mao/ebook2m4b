from __future__ import annotations

import asyncio
import io
import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from edge_tts import Communicate, list_voices
from pydub import AudioSegment
from sentencex import segment
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ...parsers.processing import BookData
from ..base import EngineInfo, LogCallback, SpeakerProfile, SynthesisProgressCallback, TTSEngine
from .fallback_catalog import fallback_voice_rows
from ..kokoro.synthesis import add_cover, generate_metadata, make_m4b

DEFAULT_EDGE_VOICE = "en-US-GuyNeural"
logger = logging.getLogger(__name__)


@contextmanager
def _pushd(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _locale_language(locale_code: str) -> str:
    if not locale_code:
        return "Unknown"
    primary = locale_code.split("-", 1)[0].strip().lower()
    labels = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "it": "Italian",
        "pt": "Portuguese",
        "de": "German",
        "ja": "Japanese",
        "zh": "Chinese",
        "hi": "Hindi",
    }
    return labels.get(primary, locale_code)


def _is_meaningful_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(char.isalnum() for char in stripped)


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]

    punctuations = [
        "。",
        "！",
        "？",
        ". ",
        "! ",
        "? ",
        ";",
        "；",
        ",",
        "，",
        ":",
        "：",
        " ",
    ]

    parts: list[str] = []
    remaining = sentence
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break

        split_index = -1
        for mark in punctuations:
            candidate = remaining[:max_chars].rfind(mark)
            if candidate >= 0:
                split_index = candidate + len(mark)
                break

        if split_index < 0:
            split_index = max_chars

        parts.append(remaining[:split_index].strip())
        remaining = remaining[split_index:].strip()

    return [part for part in parts if part]


def _split_text_chunks(text: str, language: str, max_chars: int = 3000) -> list[str]:
    if not text.strip():
        return []

    sentence_rows = [segment_text.strip() for segment_text in segment(language, text) if _is_meaningful_text(segment_text)]
    if not sentence_rows:
        sentence_rows = [text.strip()]

    chunks: list[str] = []
    current = ""
    for sentence_text in sentence_rows:
        if len(sentence_text) > max_chars:
            expanded = _split_long_sentence(sentence_text, max_chars)
        else:
            expanded = [sentence_text]

        for item in expanded:
            space = " " if current else ""
            if len(current) + len(space) + len(item) <= max_chars:
                current += f"{space}{item}"
            else:
                if current:
                    chunks.append(current)
                current = item

    if current:
        chunks.append(current)

    return chunks


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
)
def _render_edge_chunk(
    text: str,
    voice_id: str,
    voice_rate: str,
    voice_volume: str,
    voice_pitch: str,
) -> AudioSegment:
    async def _run() -> bytes:
        stream = Communicate(
            text=text,
            voice=voice_id,
            rate=voice_rate,
            volume=voice_volume,
            pitch=voice_pitch,
        )
        chunks = bytearray()
        async for payload in stream.stream():
            if payload.get("type") == "audio":
                chunks.extend(payload.get("data", b""))
        if not chunks:
            raise RuntimeError("Edge TTS returned no audio data.")
        return bytes(chunks)

    audio_bytes = asyncio.run(_run())
    return AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")


@lru_cache(maxsize=1)
@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(Exception),
)
def _live_voice_rows() -> tuple[dict, ...]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Live Edge voice fetch is not available in an active event loop context.")

    rows = tuple(asyncio.run(list_voices()))
    if not rows:
        raise RuntimeError("Edge voice listing returned no voices.")
    return rows


def _voice_rows() -> tuple[dict, ...]:
    try:
        return _live_voice_rows()
    except Exception as exc:  # noqa: BLE001
        # Keep retries available on next request by not caching fallback results.
        _live_voice_rows.cache_clear()
        logger.warning("Falling back to static Edge voice catalog: %s", exc)
        return fallback_voice_rows()


class EdgeTTSProvider(TTSEngine):
    info = EngineInfo(
        id="edge",
        label="Edge TTS",
        description="Microsoft Edge neural voices over network.",
    )

    def list_speakers(self) -> list[SpeakerProfile]:
        speakers: list[SpeakerProfile] = []
        for voice in _voice_rows():
            short_name = str(voice.get("ShortName") or "").strip()
            if not short_name:
                continue
            locale = str(voice.get("Locale") or "").strip()
            locale_name = str(voice.get("LocaleName") or "").strip()
            display_name = str(voice.get("FriendlyName") or short_name)
            language_label = _locale_language(locale)
            if locale_name and locale_name.lower() != locale.lower():
                language_label = locale_name
            speakers.append(
                SpeakerProfile(
                    id=short_name,
                    display_name=display_name,
                    language=language_label,
                    language_code=locale,
                    gender=str(voice.get("Gender") or "").title() or None,
                    target_quality="Neural",
                    training_duration=None,
                    overall_grade=None,
                )
            )

        if not speakers:
            speakers.append(
                SpeakerProfile(
                    id=DEFAULT_EDGE_VOICE,
                    display_name=DEFAULT_EDGE_VOICE,
                    language="English",
                    language_code="en-US",
                    gender="Male",
                    target_quality="Neural",
                    training_duration=None,
                    overall_grade=None,
                )
            )

        speakers.sort(key=lambda row: row.id.lower())
        return speakers

    def synthesize(
        self,
        *,
        book: BookData,
        source_txt: Path,
        speaker: SpeakerProfile,
        speed: float,
        voice_rate: str,
        voice_volume: str,
        voice_pitch: str,
        paragraphpause: int,
        notitles: bool,
        cover_path: Path | None,
        work_dir: Path,
        progress_callback: SynthesisProgressCallback,
        log_callback: LogCallback,
        cancel_check,
    ) -> Path:
        if cancel_check():
            raise RuntimeError("Discarded by user.")

        effective_rate = voice_rate.strip() if voice_rate.strip() else f"{int(round((speed - 1.0) * 100)):+d}%"
        effective_volume = voice_volume.strip() if voice_volume.strip() else "+0%"
        effective_pitch = voice_pitch.strip() if voice_pitch.strip() else "+0Hz"

        language_hint = (speaker.language_code or "en-US").split("-", 1)[0].lower() or "en"
        chapter_total = max(1, book.chapter_total)
        paragraph_total = max(1, book.paragraph_total)
        paragraph_done = 0

        files: list[str] = []
        chapter_titles: list[str] = []

        with _pushd(work_dir):
            log_callback(
                "Edge synthesis started with "
                f"speaker={speaker.id}, rate={effective_rate}, volume={effective_volume}, "
                f"pitch={effective_pitch}, paragraphpause={paragraphpause}ms."
            )

            progress_callback(0, chapter_total, paragraph_done, paragraph_total)

            for chapter_index, chapter in enumerate(book.chapters, start=1):
                if cancel_check():
                    raise RuntimeError("Discarded by user.")

                chapter_audio = AudioSegment.empty()
                if not notitles and chapter.title and chapter.title.strip() and chapter.title != "Title":
                    title_chunks = _split_text_chunks(f"{chapter.title.strip()}.", language_hint, max_chars=600)
                    for title_chunk in title_chunks:
                        if cancel_check():
                            raise RuntimeError("Discarded by user.")
                        chapter_audio += _render_edge_chunk(
                            title_chunk,
                            speaker.id,
                            effective_rate,
                            effective_volume,
                            effective_pitch,
                        )
                    if paragraphpause > 0:
                        chapter_audio += AudioSegment.silent(duration=paragraphpause)

                for paragraph in chapter.paragraphs:
                    if cancel_check():
                        raise RuntimeError("Discarded by user.")

                    chunks = _split_text_chunks(paragraph, language_hint, max_chars=3000)
                    for chunk in chunks:
                        chapter_audio += _render_edge_chunk(
                            chunk,
                            speaker.id,
                            effective_rate,
                            effective_volume,
                            effective_pitch,
                        )

                    if paragraphpause > 0:
                        chapter_audio += AudioSegment.silent(duration=paragraphpause)

                    paragraph_done += 1
                    progress_callback(chapter_index, chapter_total, paragraph_done, paragraph_total)

                if len(chapter_audio) == 0:
                    continue

                chapter_audio += AudioSegment.silent(duration=2000)
                part_name = f"part{chapter_index}.flac"
                chapter_audio.export(part_name, format="flac")
                files.append(part_name)
                chapter_titles.append(chapter.title or f"Chapter {chapter_index}")

            if not files:
                raise RuntimeError("Edge synthesis produced no audio segments.")

            generate_metadata(files, book.author, book.title, chapter_titles)
            output_name = make_m4b(files, source_txt.name, speaker.id)
            if cover_path is not None and cover_path.exists():
                add_cover(str(cover_path), output_name)

        output_path = (work_dir / output_name).resolve()
        log_callback(f"Edge synthesis completed: {output_path.name}")
        return output_path
