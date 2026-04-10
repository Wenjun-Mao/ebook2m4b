from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..parsers.processing import BookData


SynthesisProgressCallback = Callable[[int, int, int, int], None]
LogCallback = Callable[[str], None]


@dataclass(slots=True, frozen=True)
class SpeakerProfile:
    id: str
    display_name: str
    language: str
    language_code: str
    gender: str | None = None
    target_quality: str | None = None
    training_duration: str | None = None
    overall_grade: str | None = None

    @property
    def quality_label(self) -> str | None:
        return self.overall_grade or self.target_quality

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["quality_label"] = self.quality_label
        return payload


@dataclass(slots=True, frozen=True)
class EngineInfo:
    id: str
    label: str
    description: str

    def to_dict(self) -> dict:
        return asdict(self)


class TTSEngine(ABC):
    info: EngineInfo

    @abstractmethod
    def list_speakers(self) -> list[SpeakerProfile]:
        raise NotImplementedError

    def get_speaker(self, speaker_id: str) -> SpeakerProfile | None:
        normalized = speaker_id.strip().lower()
        for speaker in self.list_speakers():
            if speaker.id.lower() == normalized:
                return speaker
        return None

    @abstractmethod
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
        cancel_check: Callable[[], bool],
    ) -> Path:
        raise NotImplementedError
