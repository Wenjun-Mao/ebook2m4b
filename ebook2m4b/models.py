from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    PARSED = "parsed"
    COMPLETED = "completed"
    FAILED = "failed"
    DISCARDED = "discarded"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED.value, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), default="kokoro", nullable=False)
    queue_job_id: Mapped[str | None] = mapped_column(String(64))
    stop_requested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    speaker: Mapped[str] = mapped_column(String(128), nullable=False)
    cover_path: Mapped[str | None] = mapped_column(String(1024))
    speed: Mapped[str] = mapped_column(String(16), default="1.3", nullable=False)
    voice_rate: Mapped[str] = mapped_column(String(16), default="+0%", nullable=False)
    voice_volume: Mapped[str] = mapped_column(String(16), default="+0%", nullable=False)
    voice_pitch: Mapped[str] = mapped_column(String(16), default="+0Hz", nullable=False)
    paragraphpause: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    notitles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    output_path: Mapped[str | None] = mapped_column(String(1024))
    parsed_text_path: Mapped[str | None] = mapped_column(String(1024))
    parsed_cover_path: Mapped[str | None] = mapped_column(String(1024))
    parsed_book_path: Mapped[str | None] = mapped_column(String(1024))
    chapter_manifest_json: Mapped[str | None] = mapped_column(Text)
    selected_chapters_json: Mapped[str | None] = mapped_column(Text)
    selected_chapter_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected_paragraph_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    log_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    chapter_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chapter_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
