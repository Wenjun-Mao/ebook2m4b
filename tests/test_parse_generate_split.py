from __future__ import annotations

from pathlib import Path

from ebook2m4b.conversion import generate_from_parsed, parse_source_for_job
from ebook2m4b.settings import Settings
from ebook2m4b.tts_providers.base import SpeakerProfile


class DummyEngine:
    def get_speaker(self, speaker_id: str) -> SpeakerProfile:
        return SpeakerProfile(
            id=speaker_id,
            display_name=speaker_id,
            language="English",
            language_code="en-US",
            gender="Unknown",
        )

    def synthesize(self, **kwargs):
        book = kwargs["book"]
        work_dir = kwargs["work_dir"]
        progress_callback = kwargs["progress_callback"]

        progress_callback(0, book.chapter_total, 0, book.paragraph_total)
        progress_callback(book.chapter_total, book.chapter_total, book.paragraph_total, book.paragraph_total)

        output_path = work_dir / "dummy-output.m4b"
        output_path.write_bytes(b"dummy")
        return output_path


def test_parse_then_generate_selected_chapters(
    monkeypatch,
    test_settings: Settings,
    sample_text_source: Path,
) -> None:
    stage_events: list[tuple[str, int, int]] = []
    counter_events: list[tuple[int, int, int, int]] = []
    logs: list[str] = []

    def set_stage(stage: str, progress: int, stage_progress: int) -> None:
        stage_events.append((stage, progress, stage_progress))

    def set_counters(chapter_index: int, chapter_total: int, paragraph_done: int, paragraph_total: int) -> None:
        counter_events.append((chapter_index, chapter_total, paragraph_done, paragraph_total))

    def append_log(line: str) -> None:
        logs.append(line)

    parse_outcome = parse_source_for_job(
        job_id="job-parse-generate",
        source_path=sample_text_source,
        source_kind="txt",
        cover_path=None,
        set_stage=set_stage,
        set_counters=set_counters,
        append_log=append_log,
        settings=test_settings,
    )

    assert parse_outcome.parsed_book_path.exists()
    assert parse_outcome.parsed_text_path.exists()
    assert parse_outcome.chapter_total >= 3

    selected_index = parse_outcome.chapter_manifest[1]["index"]

    monkeypatch.setattr("ebook2m4b.conversion.get_engine", lambda _engine_id: DummyEngine())

    output_path, normalized_selection, selected_chapters, selected_paragraph_total = generate_from_parsed(
        job_id="job-parse-generate",
        source_path=parse_outcome.local_source_path,
        engine="edge",
        speaker="en-US-GuyNeural",
        speed=1.0,
        voice_rate="+0%",
        voice_volume="+0%",
        voice_pitch="+0Hz",
        paragraphpause=0,
        notitles=False,
        parsed_text_path=parse_outcome.parsed_text_path,
        parsed_cover_path=parse_outcome.parsed_cover_path,
        parsed_book_path=parse_outcome.parsed_book_path,
        chapter_manifest=parse_outcome.chapter_manifest,
        selected_chapter_indexes=[selected_index],
        set_stage=set_stage,
        set_counters=set_counters,
        append_log=append_log,
        settings=test_settings,
    )

    assert output_path.exists()
    assert normalized_selection == [selected_index]
    assert selected_chapters == 1
    assert selected_paragraph_total > 0
    assert any(event[0] == "parsed" for event in stage_events)
    assert any(event[0] == "completed" for event in stage_events)
