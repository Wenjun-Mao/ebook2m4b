from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from .settings import Settings, get_settings


SQLITE_JOB_COLUMNS: dict[str, str] = {
    "stage_progress": "INTEGER NOT NULL DEFAULT 0",
    "engine": "VARCHAR(64) NOT NULL DEFAULT 'kokoro'",
    "queue_job_id": "VARCHAR(64)",
    "stop_requested": "INTEGER NOT NULL DEFAULT 0",
    "voice_rate": "VARCHAR(16) NOT NULL DEFAULT '+0%'",
    "voice_volume": "VARCHAR(16) NOT NULL DEFAULT '+0%'",
    "voice_pitch": "VARCHAR(16) NOT NULL DEFAULT '+0Hz'",
    "chapter_index": "INTEGER NOT NULL DEFAULT 0",
    "chapter_total": "INTEGER NOT NULL DEFAULT 0",
    "paragraph_done": "INTEGER NOT NULL DEFAULT 0",
    "paragraph_total": "INTEGER NOT NULL DEFAULT 0",
    "parsed_text_path": "VARCHAR(1024)",
    "parsed_cover_path": "VARCHAR(1024)",
    "parsed_book_path": "VARCHAR(1024)",
    "chapter_manifest_json": "TEXT",
    "selected_chapters_json": "TEXT",
    "selected_chapter_total": "INTEGER NOT NULL DEFAULT 0",
    "selected_paragraph_total": "INTEGER NOT NULL DEFAULT 0",
}


def get_engine(settings: Settings | None = None):
    active_settings = settings or get_settings()
    connect_args = {"check_same_thread": False} if active_settings.database_url.startswith("sqlite") else {}
    return create_engine(active_settings.database_url, future=True, connect_args=connect_args)


def get_session_factory(settings: Settings | None = None):
    return sessionmaker(bind=get_engine(settings), autoflush=False, autocommit=False, expire_on_commit=False)


def _ensure_sqlite_job_columns(engine) -> None:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(jobs)")).mappings().all()
        if not rows:
            return
        existing = {row["name"] for row in rows}
        for column_name, column_sql in SQLITE_JOB_COLUMNS.items():
            if column_name in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_sql}"))
            except OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    continue
                raise


def init_db(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    Base.metadata.create_all(bind=engine)
    active_settings = settings or get_settings()
    if active_settings.database_url.startswith("sqlite"):
        _ensure_sqlite_job_columns(engine)


@contextmanager
def session_scope(settings: Settings | None = None):
    session_factory = get_session_factory(settings)
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
