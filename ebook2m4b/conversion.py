from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .parsers import BookData, ChapterData, ParserOptions, prepare_text_source
from .settings import Settings, get_settings
from .storage import copy_if_exists, job_result_dir, job_work_dir, sanitize_filename
from .tts_providers import get_engine


class ConversionError(RuntimeError):
    pass


class ConversionDiscarded(ConversionError):
    pass


@dataclass(slots=True)
class ParseOutcome:
    local_source_path: Path
    parsed_text_path: Path
    parsed_cover_path: Path | None
    parsed_book_path: Path
    chapter_manifest: list[dict]
    chapter_total: int
    paragraph_total: int


StageCallback = Callable[[str, int, int], None]
CounterCallback = Callable[[int, int, int, int], None]
LogCallback = Callable[[str], None]

def _safe_name(path: Path) -> str:
    return sanitize_filename(path.name, default_stem="source")


def _build_parser_options(settings: Settings) -> ParserOptions:
    return ParserOptions(
        language=settings.parser_language,
        newline_mode=settings.parser_newline_mode,
        title_mode=settings.parser_title_mode,
        remove_endnotes=settings.parser_remove_endnotes,
        remove_reference_numbers=settings.parser_remove_reference_numbers,
        max_segment_chars=settings.parser_max_segment_chars,
        min_sentence_words=settings.parser_min_sentence_words,
    )


def _book_to_payload(book: BookData) -> dict:
    return {
        "title": book.title,
        "author": book.author,
        "chapters": [
            {
                "index": int(chapter.index),
                "title": chapter.title,
                "paragraphs": list(chapter.paragraphs),
                "level": max(1, int(getattr(chapter, "level", 1))),
            }
            for chapter in book.chapters
        ],
    }


def _book_from_payload(payload: dict) -> BookData:
    title = str(payload.get("title") or "Untitled")
    author = str(payload.get("author") or "Unknown")

    chapters: list[ChapterData] = []
    chapter_rows = payload.get("chapters")
    if not isinstance(chapter_rows, list):
        chapter_rows = []

    for idx, chapter_row in enumerate(chapter_rows, start=1):
        if not isinstance(chapter_row, dict):
            continue
        raw_paragraphs = chapter_row.get("paragraphs")
        if isinstance(raw_paragraphs, list):
            paragraphs = [str(item) for item in raw_paragraphs if str(item).strip()]
        else:
            paragraphs = []
        chapters.append(
            ChapterData(
                index=idx,
                title=str(chapter_row.get("title") or f"Chapter {idx}"),
                paragraphs=paragraphs,
                level=max(1, int(chapter_row.get("level") or 1)),
            )
        )

    return BookData(title=title, author=author, chapters=chapters)


def build_chapter_manifest(book: BookData) -> list[dict]:
    manifest: list[dict] = []
    for chapter in book.chapters:
        manifest.append(
            {
                "index": int(chapter.index),
                "title": chapter.title,
                "paragraph_count": chapter.paragraph_count,
                "level": max(1, int(getattr(chapter, "level", 1))),
            }
        )
    return manifest


def _normalize_selected_indexes(manifest: list[dict], selected_indexes: list[int]) -> list[int]:
    valid = {int(row.get("index") or 0) for row in manifest}
    normalized: list[int] = []
    for raw_value in selected_indexes:
        numeric = int(raw_value)
        if numeric in valid and numeric not in normalized:
            normalized.append(numeric)
    if normalized:
        return normalized
    return sorted(valid)


def _selected_paragraph_total(manifest: list[dict], selected_indexes: list[int]) -> int:
    selected = set(selected_indexes)
    total = 0
    for row in manifest:
        index = int(row.get("index") or 0)
        if index in selected:
            total += max(0, int(row.get("paragraph_count") or 0))
    return total


def _write_book_payload(path: Path, book: BookData) -> None:
    payload = _book_to_payload(book)
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def load_book_payload(path: Path) -> BookData:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConversionError("Parsed book payload is malformed.")
    return _book_from_payload(payload)


def parse_source_for_job(
    *,
    job_id: str,
    source_path: Path,
    source_kind: str,
    cover_path: Path | None,
    set_stage: StageCallback,
    set_counters: CounterCallback,
    append_log: LogCallback,
    should_stop: Callable[[], bool] | None = None,
    settings: Settings | None = None,
) -> ParseOutcome:
    active_settings = settings or get_settings()
    stop_check = should_stop or (lambda: False)

    def raise_if_discarded() -> None:
        if stop_check():
            raise ConversionDiscarded("Discarded by user.")

    work_dir = job_work_dir(job_id, active_settings)

    local_source = work_dir / _safe_name(source_path)
    if source_path.resolve() != local_source.resolve():
        shutil.copy2(source_path, local_source)

    local_cover: Path | None = None
    if cover_path is not None:
        local_cover = work_dir / _safe_name(cover_path)
        if cover_path.resolve() != local_cover.resolve():
            shutil.copy2(cover_path, local_cover)

    set_stage("extracting_text", 1, 0)
    raise_if_discarded()

    try:
        prepared = prepare_text_source(
            local_source,
            source_kind,
            append_log=append_log,
            options=_build_parser_options(active_settings),
        )
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Failed to parse source text: {exc}") from exc

    if prepared.book.paragraph_total <= 0:
        raise ConversionError("The source did not contain readable text paragraphs.")

    if local_cover is None and prepared.auto_cover_path is not None and prepared.auto_cover_path.exists():
        local_cover = prepared.auto_cover_path

    parsed_book_path = work_dir / "parsed_book.json"
    _write_book_payload(parsed_book_path, prepared.book)

    chapter_manifest = build_chapter_manifest(prepared.book)

    set_counters(0, prepared.book.chapter_total, 0, prepared.book.paragraph_total)
    set_stage("parsed", 100, 100)
    append_log(
        f"Parse complete. Chapters: {prepared.book.chapter_total}, text units: {prepared.book.paragraph_total}."
    )

    return ParseOutcome(
        local_source_path=local_source,
        parsed_text_path=prepared.text_path,
        parsed_cover_path=local_cover,
        parsed_book_path=parsed_book_path,
        chapter_manifest=chapter_manifest,
        chapter_total=prepared.book.chapter_total,
        paragraph_total=prepared.book.paragraph_total,
    )


def generate_from_parsed(
    *,
    job_id: str,
    source_path: Path,
    engine: str,
    speaker: str,
    speed: float,
    voice_rate: str,
    voice_volume: str,
    voice_pitch: str,
    paragraphpause: int,
    notitles: bool,
    parsed_text_path: Path,
    parsed_cover_path: Path | None,
    parsed_book_path: Path,
    chapter_manifest: list[dict],
    selected_chapter_indexes: list[int],
    set_stage: StageCallback,
    set_counters: CounterCallback,
    append_log: LogCallback,
    should_stop: Callable[[], bool] | None = None,
    settings: Settings | None = None,
) -> tuple[Path, list[int], int, int]:
    active_settings = settings or get_settings()
    try:
        tts_engine = get_engine(engine)
    except ValueError as exc:
        raise ConversionError(str(exc)) from exc

    speaker_profile = tts_engine.get_speaker(speaker)
    if speaker_profile is None:
        raise ConversionError(
            f"Speaker '{speaker}' is not available for engine '{engine}'."
        )

    stop_check = should_stop or (lambda: False)

    def raise_if_discarded() -> None:
        if stop_check():
            raise ConversionDiscarded("Discarded by user.")

    if not parsed_book_path.exists():
        raise ConversionError("Parsed book data is missing. Parse the source again.")
    if not parsed_text_path.exists():
        raise ConversionError("Parsed text source is missing. Parse the source again.")

    parsed_book = load_book_payload(parsed_book_path)
    selected_indexes = _normalize_selected_indexes(chapter_manifest, selected_chapter_indexes)
    selected_paragraph_total = _selected_paragraph_total(chapter_manifest, selected_indexes)

    selected = [
        chapter
        for chapter in parsed_book.chapters
        if int(chapter.index) in set(selected_indexes)
    ]
    if not selected:
        raise ConversionError("No chapters selected for generation.")

    selected_book = BookData(
        title=parsed_book.title,
        author=parsed_book.author,
        chapters=[
            ChapterData(
                index=i,
                title=chapter.title,
                paragraphs=list(chapter.paragraphs),
                level=max(1, int(getattr(chapter, "level", 1))),
            )
            for i, chapter in enumerate(selected, start=1)
        ],
    )

    if selected_book.paragraph_total <= 0:
        raise ConversionError("Selected chapters did not contain readable text units.")

    work_dir = job_work_dir(job_id, active_settings)
    result_dir = job_result_dir(job_id, active_settings)

    synth_start = 5
    synth_end = 95
    last_logged_percent = -1

    def on_synthesis_progress(
        chapter_index: int,
        chapter_total: int,
        paragraph_done: int,
        paragraph_total: int,
    ) -> None:
        nonlocal last_logged_percent

        raise_if_discarded()

        safe_total = max(1, paragraph_total)
        stage_progress = min(100, max(0, int((paragraph_done * 100) / safe_total)))
        if paragraph_done > 0 and stage_progress == 0:
            stage_progress = 1

        overall_progress = synth_start + int((synth_end - synth_start) * paragraph_done / safe_total)
        if paragraph_done > 0 and overall_progress <= synth_start:
            overall_progress = synth_start + 1
        overall_progress = min(synth_end, overall_progress)

        set_stage("synthesizing", overall_progress, stage_progress)
        set_counters(chapter_index, chapter_total, paragraph_done, paragraph_total)

        if chapter_index <= 0 and paragraph_done <= 0:
            return

        if stage_progress in {0, 100} or stage_progress // 2 != last_logged_percent // 2:
            append_log(
                "Synthesizing: chapter "
                f"{chapter_index}/{chapter_total}, text units {paragraph_done}/{paragraph_total} "
                f"({stage_progress}%)."
            )
            last_logged_percent = stage_progress

    set_stage("synthesizing", synth_start, 0)
    set_counters(0, selected_book.chapter_total, 0, selected_book.paragraph_total)
    raise_if_discarded()

    try:
        expected_output = tts_engine.synthesize(
            book=selected_book,
            source_txt=parsed_text_path,
            speaker=speaker_profile,
            speed=speed,
            voice_rate=voice_rate,
            voice_volume=voice_volume,
            voice_pitch=voice_pitch,
            paragraphpause=paragraphpause,
            notitles=notitles,
            cover_path=parsed_cover_path,
            work_dir=work_dir,
            progress_callback=on_synthesis_progress,
            log_callback=append_log,
            cancel_check=stop_check,
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ConversionDiscarded):
            raise
        if stop_check():
            raise ConversionDiscarded("Discarded by user.") from exc
        raise ConversionError(f"Engine synthesis failed: {exc}") from exc

    if not expected_output.exists():
        raise ConversionError("Audio synthesis finished but no M4B output was found.")

    raise_if_discarded()

    set_stage("packaging", 97, 0)
    final_output = result_dir / expected_output.name
    shutil.copy2(expected_output, final_output)

    copy_if_exists(source_path, result_dir / source_path.name)
    copy_if_exists(parsed_text_path, result_dir / parsed_text_path.name)
    if parsed_cover_path is not None:
        copy_if_exists(parsed_cover_path, result_dir / parsed_cover_path.name)

    set_counters(
        selected_book.chapter_total,
        selected_book.chapter_total,
        selected_book.paragraph_total,
        selected_book.paragraph_total,
    )
    set_stage("completed", 100, 100)
    return (
        final_output,
        selected_indexes,
        selected_book.chapter_total,
        selected_paragraph_total,
    )


def run_one_click(
    *,
    job_id: str,
    source_path: Path,
    source_kind: str,
    engine: str,
    speaker: str,
    cover_path: Path | None,
    speed: float,
    voice_rate: str,
    voice_volume: str,
    voice_pitch: str,
    paragraphpause: int,
    notitles: bool,
    set_stage: StageCallback,
    set_counters: CounterCallback,
    append_log: LogCallback,
    should_stop: Callable[[], bool] | None = None,
    settings: Settings | None = None,
) -> Path:
    active_settings = settings or get_settings()
    try:
        tts_engine = get_engine(engine)
    except ValueError as exc:
        raise ConversionError(str(exc)) from exc

    speaker_profile = tts_engine.get_speaker(speaker)
    if speaker_profile is None:
        raise ConversionError(
            f"Speaker '{speaker}' is not available for engine '{engine}'."
        )

    stop_check = should_stop or (lambda: False)

    def raise_if_discarded() -> None:
        if stop_check():
            raise ConversionDiscarded("Discarded by user.")

    work_dir = job_work_dir(job_id, active_settings)
    result_dir = job_result_dir(job_id, active_settings)

    local_source = work_dir / _safe_name(source_path)
    if source_path.resolve() != local_source.resolve():
        shutil.copy2(source_path, local_source)

    local_cover: Path | None = None
    if cover_path is not None:
        local_cover = work_dir / _safe_name(cover_path)
        if cover_path.resolve() != local_cover.resolve():
            shutil.copy2(cover_path, local_cover)

    prep_start = 1
    prep_end = 20 if source_kind.lower() == "epub" else 8
    synth_start = prep_end
    synth_end = 95

    set_stage("extracting_text", prep_start, 0)
    raise_if_discarded()
    parser_options = _build_parser_options(active_settings)
    try:
        prepared = prepare_text_source(
            local_source,
            source_kind,
            append_log=append_log,
            options=parser_options,
        )
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Failed to prepare source text: {exc}") from exc

    source_for_audio = prepared.text_path
    if local_cover is None and prepared.auto_cover_path is not None and prepared.auto_cover_path.exists():
        local_cover = prepared.auto_cover_path

    set_counters(0, prepared.book.chapter_total, 0, prepared.book.paragraph_total)
    set_stage("extracting_text", prep_end, 100)

    if prepared.book.paragraph_total <= 0:
        raise ConversionError("The source did not contain readable text paragraphs.")

    last_logged_percent = -1

    def on_synthesis_progress(
        chapter_index: int,
        chapter_total: int,
        paragraph_done: int,
        paragraph_total: int,
    ) -> None:
        nonlocal last_logged_percent

        raise_if_discarded()

        safe_total = max(1, paragraph_total)
        stage_progress = min(100, max(0, int((paragraph_done * 100) / safe_total)))
        if paragraph_done > 0 and stage_progress == 0:
            stage_progress = 1

        overall_progress = synth_start + int((synth_end - synth_start) * paragraph_done / safe_total)
        if paragraph_done > 0 and overall_progress <= synth_start:
            overall_progress = synth_start + 1
        overall_progress = min(synth_end, overall_progress)

        set_stage("synthesizing", overall_progress, stage_progress)
        set_counters(chapter_index, chapter_total, paragraph_done, paragraph_total)

        if chapter_index <= 0 and paragraph_done <= 0:
            return

        if stage_progress in {0, 100} or stage_progress // 2 != last_logged_percent // 2:
            append_log(
                "Synthesizing: chapter "
                f"{chapter_index}/{chapter_total}, text units {paragraph_done}/{paragraph_total} "
                f"({stage_progress}%)."
            )
            last_logged_percent = stage_progress

    set_stage("synthesizing", synth_start, 0)
    raise_if_discarded()
    try:
        expected_output = tts_engine.synthesize(
            book=prepared.book,
            source_txt=source_for_audio,
            speaker=speaker_profile,
            speed=speed,
            voice_rate=voice_rate,
            voice_volume=voice_volume,
            voice_pitch=voice_pitch,
            paragraphpause=paragraphpause,
            notitles=notitles,
            cover_path=local_cover,
            work_dir=work_dir,
            progress_callback=on_synthesis_progress,
            log_callback=append_log,
            cancel_check=stop_check,
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ConversionDiscarded):
            raise
        if stop_check():
            raise ConversionDiscarded("Discarded by user.") from exc
        raise ConversionError(f"Engine synthesis failed: {exc}") from exc

    if not expected_output.exists():
        raise ConversionError("Audio synthesis finished but no M4B output was found.")

    raise_if_discarded()

    set_stage("packaging", 97, 0)
    final_output = result_dir / expected_output.name
    shutil.copy2(expected_output, final_output)

    # Keep useful artifacts in results for easy browsing/download.
    copy_if_exists(local_source, result_dir / local_source.name)
    copy_if_exists(source_for_audio, result_dir / source_for_audio.name)
    if local_cover is not None:
        copy_if_exists(local_cover, result_dir / local_cover.name)

    set_counters(
        prepared.book.chapter_total,
        prepared.book.chapter_total,
        prepared.book.paragraph_total,
        prepared.book.paragraph_total,
    )
    set_stage("completed", 100, 100)
    return final_output
