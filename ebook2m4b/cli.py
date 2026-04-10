from __future__ import annotations

import argparse
from pathlib import Path

from .conversion import run_one_click
from .settings import get_settings
from .storage import ensure_storage_dirs
from .tts_providers import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(prog="ebook2m4b", description="One-command EPUB/TXT to M4B converter")
    parser.add_argument("source", type=str, help="Path to .epub or .txt source file")
    parser.add_argument("--engine", type=str, default=None)
    parser.add_argument("--speaker", type=str, default=None)
    parser.add_argument("--cover", type=str, default=None)
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--voice-rate", type=str, default=None)
    parser.add_argument("--voice-volume", type=str, default=None)
    parser.add_argument("--voice-pitch", type=str, default=None)
    parser.add_argument("--paragraphpause", type=int, default=None)
    parser.add_argument("--notitles", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    ensure_storage_dirs(settings)

    selected_engine = (args.engine or settings.default_engine).strip().lower()
    tts_engine = get_engine(selected_engine)

    selected_speaker = (args.speaker or settings.default_speaker).strip()
    speaker_profile = tts_engine.get_speaker(selected_speaker)
    if speaker_profile is None:
        valid = ", ".join(item.id for item in tts_engine.list_speakers())
        raise ValueError(
            f"Unknown speaker '{selected_speaker}' for engine '{selected_engine}'. Available: {valid}"
        )

    speed = args.speed if args.speed is not None else settings.default_speed
    voice_rate = args.voice_rate if args.voice_rate is not None else settings.default_voice_rate
    voice_volume = args.voice_volume if args.voice_volume is not None else settings.default_voice_volume
    voice_pitch = args.voice_pitch if args.voice_pitch is not None else settings.default_voice_pitch
    paragraphpause = (
        args.paragraphpause if args.paragraphpause is not None else settings.default_paragraphpause
    )

    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = (settings.data_dir / source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    cover_path = None
    if args.cover:
        cover_path = Path(args.cover)
        if not cover_path.is_absolute():
            cover_path = (settings.data_dir / cover_path).resolve()

    source_kind = source_path.suffix.lower().lstrip(".")
    if source_kind not in {"epub", "txt"}:
        raise ValueError("Source must be .epub or .txt")

    def set_stage(stage: str, progress: int, stage_progress: int) -> None:
        print(f"[{progress:3d}% overall | {stage_progress:3d}% stage] {stage}")

    def set_counters(chapter_index: int, chapter_total: int, paragraph_done: int, paragraph_total: int) -> None:
        print(
            "Progress counters: "
            f"chapter {chapter_index}/{chapter_total}, "
            f"text units {paragraph_done}/{paragraph_total}"
        )

    def append_log(line: str) -> None:
        print(line)

    output = run_one_click(
        job_id="cli",
        source_path=source_path,
        source_kind=source_kind,
        engine=selected_engine,
        speaker=speaker_profile.id,
        cover_path=cover_path,
        speed=speed,
        voice_rate=voice_rate,
        voice_volume=voice_volume,
        voice_pitch=voice_pitch,
        paragraphpause=paragraphpause,
        notitles=args.notitles,
        set_stage=set_stage,
        set_counters=set_counters,
        append_log=append_log,
        settings=settings,
    )
    print(f"Output: {output}")


if __name__ == "__main__":
    main()
