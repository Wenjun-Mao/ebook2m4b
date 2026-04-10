from __future__ import annotations

from pathlib import Path

import pytest

from ebook2m4b.settings import Settings
from ebook2m4b.storage import ensure_storage_dirs


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "jobs.db"
    settings = Settings(
        data_dir=data_dir,
        database_url=f"sqlite:///{str(db_path).replace('\\', '/')}",
        redis_url="redis://localhost:6379/15",
        run_jobs_inline=True,
    )
    ensure_storage_dirs(settings)
    return settings


@pytest.fixture
def sample_text_source(tmp_path: Path) -> Path:
    source_path = tmp_path / "sample.txt"
    source_path.write_text(
        """
# Part I
Intro paragraph one. Intro paragraph two.

## Chapter One
Chapter one paragraph one. Chapter one paragraph two.

### Section One
Section one paragraph one. Section one paragraph two.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return source_path
