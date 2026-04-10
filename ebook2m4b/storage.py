from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile

from .settings import Settings, get_settings

SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_storage_dirs(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    for directory in (active_settings.data_dir, active_settings.inputs_dir, active_settings.work_dir, active_settings.results_dir):
        directory.mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str, default_stem: str = "file") -> str:
    cleaned = SAFE_FILENAME_PATTERN.sub("_", filename).strip("._")
    return cleaned or default_stem


def job_input_dir(job_id: str, settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    path = active_settings.inputs_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_work_dir(job_id: str, settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    path = active_settings.work_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_result_dir(job_id: str, settings: Settings | None = None) -> Path:
    active_settings = settings or get_settings()
    path = active_settings.results_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_existing_source_files(settings: Settings | None = None) -> list[str]:
    active_settings = settings or get_settings()
    files: list[str] = []
    if not active_settings.data_dir.exists():
        return files
    for path in active_settings.data_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(active_settings.data_dir)
        if rel.parts and rel.parts[0] in {"work", "cache"}:
            continue
        if path.suffix.lower() not in {".epub", ".txt"}:
            continue
        files.append(str(rel))
    files.sort()
    return files


async def persist_uploads(job_id: str, uploads: Iterable[UploadFile], settings: Settings | None = None) -> list[Path]:
    upload_dir = job_input_dir(job_id, settings)
    stored_paths: list[Path] = []
    for index, upload in enumerate(uploads, start=1):
        if not upload.filename:
            continue
        safe_name = f"{index:02d}-{sanitize_filename(upload.filename, default_stem='upload')}"
        destination = upload_dir / safe_name
        destination.write_bytes(await upload.read())
        stored_paths.append(destination)
        await upload.close()
    return stored_paths


def persist_text_input(job_id: str, text: str, settings: Settings | None = None) -> Path:
    upload_dir = job_input_dir(job_id, settings)
    destination = upload_dir / "01-pasted.txt"
    destination.write_text(text, encoding="utf-8")
    return destination


def copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True
