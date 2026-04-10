from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EBOOK2M4B_",
        extra="ignore",
    )

    app_name: str = "Ebook2M4B"
    host: str = "0.0.0.0"
    port: int = 7777
    debug: bool = False

    data_dir: Path = Path("/data")
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "sqlite:////data/ebook2m4b.db"
    queue_name: str = "ebook2m4b"
    job_timeout_seconds: int = 10800
    run_jobs_inline: bool = False

    default_speaker: str = "af_heart"
    default_engine: str = "kokoro"
    default_speed: float = 1.3
    default_paragraphpause: int = 600
    default_notitles: bool = False
    default_voice_rate: str = "+0%"
    default_voice_volume: str = "+0%"
    default_voice_pitch: str = "+0Hz"
    default_edge_locale_filter: str = ""

    parser_language: str = "en"
    parser_newline_mode: str = "double"
    parser_title_mode: str = "auto"
    parser_remove_endnotes: bool = True
    parser_remove_reference_numbers: bool = True
    parser_max_segment_chars: int = 400
    parser_min_sentence_words: int = 8

    engine_script: Path = Path("/app/ebook2m4b/tts_providers/kokoro/synthesis.py")
    max_log_lines: int = 1200

    @computed_field  # type: ignore[misc]
    @property
    def inputs_dir(self) -> Path:
        return self.data_dir / "inputs"

    @computed_field  # type: ignore[misc]
    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @computed_field  # type: ignore[misc]
    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
