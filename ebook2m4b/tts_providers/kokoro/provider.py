from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from ..base import EngineInfo, SpeakerProfile, TTSEngine
from ..base import LogCallback, SynthesisProgressCallback
from ...parsers.processing import BookData
from .speakers import get_kokoro_speakers
from .synthesis import add_cover, ensure_punkt, generate_metadata, make_m4b, read_book


@contextmanager
def _pushd(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


class KokoroEngine(TTSEngine):
    info = EngineInfo(
        id="kokoro",
        label="Kokoro 82M",
        description="Local Kokoro text-to-speech engine.",
    )

    def list_speakers(self) -> list[SpeakerProfile]:
        return get_kokoro_speakers()

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
        ensure_punkt()
        if cancel_check():
            raise RuntimeError("Discarded by user.")

        book_contents = [
            {"title": chapter.title, "paragraphs": list(chapter.paragraphs)}
            for chapter in book.chapters
        ]
        chapter_titles = [chapter.title for chapter in book.chapters]

        source_txt_name = source_txt.name
        with _pushd(work_dir):
            log_callback(
                f"Kokoro synthesis started with speaker={speaker.id}, speed={speed:.2f}, paragraphpause={paragraphpause}ms."
            )
            files = read_book(
                book_contents,
                speaker.id,
                paragraphpause,
                speed,
                notitles,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            if cancel_check():
                raise RuntimeError("Discarded by user.")
            generate_metadata(files, book.author, book.title, chapter_titles)
            if cancel_check():
                raise RuntimeError("Discarded by user.")
            output_name = make_m4b(files, source_txt_name, speaker.id)
            if cover_path is not None:
                add_cover(str(cover_path), output_name)

        output_path = (work_dir / output_name).resolve()
        log_callback(f"Kokoro synthesis completed: {output_path.name}")
        return output_path
