from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from .conversion import (
    ConversionDiscarded,
    ConversionError,
    generate_from_parsed,
    parse_source_for_job,
)
from .db import session_scope
from .models import Job, JobStatus
from .queueing import cancel_or_stop_job, dispatch_job
from .settings import Settings, get_settings


ACTIVE_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.PROCESSING.value,
    JobStatus.PARSED.value,
)
VISIBLE_STATUSES = (
    JobStatus.QUEUED.value,
    JobStatus.PROCESSING.value,
    JobStatus.PARSED.value,
    JobStatus.COMPLETED.value,
)
TERMINAL_STATUSES = (
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.DISCARDED.value,
)


def _job_snapshot(job: Job) -> dict[str, str | None]:
    return {
        "id": job.id,
        "source_path": job.source_path,
        "output_path": job.output_path,
    }


def _safe_remove_file(path: Path) -> None:
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:  # noqa: BLE001
        return


def _safe_remove_tree(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:  # noqa: BLE001
        return


def _cleanup_managed_input(source_path: Path, settings: Settings) -> None:
    try:
        rel = source_path.resolve().relative_to(settings.inputs_dir.resolve())
    except Exception:  # noqa: BLE001
        return

    # Uploaded files are stored under /data/inputs/<uuid>/filename.ext.
    if len(rel.parts) < 2:
        return

    _safe_remove_tree(source_path.parent)


def cleanup_job_artifacts(job: Job | dict[str, str | None], settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()

    if isinstance(job, dict):
        job_id = str(job.get("id") or "")
        source_path_value = job.get("source_path")
        output_path_value = job.get("output_path")
    else:
        job_id = job.id
        source_path_value = job.source_path
        output_path_value = job.output_path

    if job_id:
        _safe_remove_tree(active_settings.work_dir / job_id)
        _safe_remove_tree(active_settings.results_dir / job_id)

    if output_path_value:
        output_path = Path(output_path_value)
        _safe_remove_file(output_path)

    if source_path_value:
        source_path = Path(source_path_value)
        _cleanup_managed_input(source_path, active_settings)


def create_job(
    *,
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
    settings: Settings | None = None,
) -> Job:
    active_settings = settings or get_settings()
    with session_scope(active_settings) as session:
        job = Job(
            source_path=str(source_path),
            source_kind=source_kind,
            engine=engine,
            queue_job_id=None,
            stop_requested=0,
            speaker=speaker,
            cover_path=str(cover_path) if cover_path else None,
            speed=str(speed),
            voice_rate=voice_rate,
            voice_volume=voice_volume,
            voice_pitch=voice_pitch,
            paragraphpause=paragraphpause,
            notitles=1 if notitles else 0,
            status=JobStatus.QUEUED.value,
            stage="queued",
            progress=0,
            stage_progress=0,
            chapter_index=0,
            chapter_total=0,
            paragraph_done=0,
            paragraph_total=0,
            parsed_text_path=None,
            parsed_cover_path=None,
            parsed_book_path=None,
            chapter_manifest_json=None,
            selected_chapters_json=None,
            selected_chapter_total=0,
            selected_paragraph_total=0,
        )
        session.add(job)
        session.flush()
        session.refresh(job)
        return job


def get_job(job_id: str, settings: Settings | None = None) -> Job | None:
    active_settings = settings or get_settings()
    with session_scope(active_settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        session.expunge(job)
        return job


def list_recent_jobs(limit: int = 30, settings: Settings | None = None) -> list[Job]:
    active_settings = settings or get_settings()
    with session_scope(active_settings) as session:
        jobs = (
            session.query(Job)
            .filter(Job.status.in_(VISIBLE_STATUSES))
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )
        for job in jobs:
            session.expunge(job)
        return jobs


def update_job_fields(job_id: str, settings: Settings | None = None, **updates: Any) -> None:
    active_settings = settings or get_settings()
    with session_scope(active_settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} was not found.")
        for key, value in updates.items():
            setattr(job, key, value)


def append_job_log(job_id: str, line: str, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    with session_scope(active_settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        lines = job.log_text.splitlines()
        lines.append(line)
        if len(lines) > active_settings.max_log_lines:
            lines = lines[-active_settings.max_log_lines :]
        job.log_text = "\n".join(lines)


def enqueue_conversion(job_id: str, settings: Settings | None = None):
    active_settings = settings or get_settings()
    queued = dispatch_job(run_conversion_job, job_id, settings=active_settings)
    queue_job_id = getattr(queued, "id", None)
    if queue_job_id:
        update_job_fields(job_id, active_settings, queue_job_id=str(queue_job_id))
    return queued


def enqueue_generation(job_id: str, settings: Settings | None = None):
    active_settings = settings or get_settings()
    queued = dispatch_job(run_generation_job, job_id, settings=active_settings)
    queue_job_id = getattr(queued, "id", None)
    if queue_job_id:
        update_job_fields(
            job_id,
            active_settings,
            queue_job_id=str(queue_job_id),
            status=JobStatus.QUEUED.value,
            stage="queued_generation",
            progress=0,
            stage_progress=0,
        )
    return queued


def request_discard_job(job_id: str, settings: Settings | None = None) -> Job:
    active_settings = settings or get_settings()

    snapshot: dict[str, str | None] | None = None
    queue_job_id: str | None = None

    with session_scope(active_settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} was not found.")

        current_status = (job.status or "").strip().lower()
        if current_status in TERMINAL_STATUSES:
            if current_status == JobStatus.DISCARDED.value:
                session.expunge(job)
                return job

            # Completed/failed jobs can be explicitly discarded from UI cards.
            job.status = JobStatus.DISCARDED.value
            job.stage = "discarded"
            job.progress = 0
            job.stage_progress = 0
            job.stop_requested = 0
            job.queue_job_id = None
            job.error_message = "Discarded by user."
            snapshot = _job_snapshot(job)
            session.flush()
        else:
            job.stop_requested = 1
            job.stage = "discard_requested"
            job.error_message = "Discard requested by user."
            queue_job_id = job.queue_job_id

            if current_status in {JobStatus.QUEUED.value, JobStatus.PARSED.value} or (
                current_status == JobStatus.PROCESSING.value and not queue_job_id
            ):
                job.status = JobStatus.DISCARDED.value
                job.stage = "discarded"
                job.progress = 0
                job.stage_progress = 0
                snapshot = _job_snapshot(job)

            session.flush()

    # No queue id means either terminal discard or immediate discard.
    if queue_job_id is None:
        if snapshot is not None:
            cleanup_job_artifacts(snapshot, active_settings)

        fresh = get_job(job_id, active_settings)
        if fresh is None:
            raise ValueError(f"Job {job_id} was not found after discard request.")
        return fresh

    stop_command_sent = False
    if queue_job_id:
        stop_command_sent = cancel_or_stop_job(queue_job_id, active_settings)

    if queue_job_id and stop_command_sent:
        update_job_fields(
            job_id,
            active_settings,
            status=JobStatus.DISCARDED.value,
            stage="discarded",
            progress=0,
            stage_progress=0,
            error_message="Discarded by user.",
        )
        stopped = get_job(job_id, active_settings)
        if stopped is not None:
            cleanup_job_artifacts(stopped, active_settings)
            return stopped

    if queue_job_id and not stop_command_sent:
        update_job_fields(
            job_id,
            active_settings,
            status=JobStatus.DISCARDED.value,
            stage="discarded",
            progress=0,
            stage_progress=0,
            error_message="Discarded by user.",
        )
        fallback = get_job(job_id, active_settings)
        if fallback is not None:
            cleanup_job_artifacts(fallback, active_settings)
            return fallback

    if snapshot is not None:
        cleanup_job_artifacts(snapshot, active_settings)

    fresh = get_job(job_id, active_settings)
    if fresh is None:
        raise ValueError(f"Job {job_id} was not found after discard request.")
    return fresh


def cleanup_generated_files(settings: Settings | None = None) -> dict[str, int]:
    active_settings = settings or get_settings()

    with session_scope(active_settings) as session:
        all_jobs = session.query(Job).all()
        snapshots = [_job_snapshot(job) for job in all_jobs]
        queue_ids = [job.queue_job_id for job in all_jobs if job.queue_job_id]
        active_count = sum(1 for job in all_jobs if (job.status or "").strip().lower() in ACTIVE_STATUSES)

        for job in all_jobs:
            session.delete(job)

    for queue_id in queue_ids:
        cancel_or_stop_job(queue_id, active_settings)

    for target_dir in (active_settings.work_dir, active_settings.results_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in target_dir.iterdir():
            if item.is_dir():
                _safe_remove_tree(item)
            else:
                _safe_remove_file(item)

    # Remove upload directories under /data/inputs/* while preserving direct user-managed files.
    active_settings.inputs_dir.mkdir(parents=True, exist_ok=True)
    for item in active_settings.inputs_dir.iterdir():
        if item.is_dir():
            _safe_remove_tree(item)

    for snapshot in snapshots:
        cleanup_job_artifacts(snapshot, active_settings)

    return {
        "deleted_jobs": len(snapshots),
        "discarded_active": active_count,
    }


def run_conversion_job(job_id: str) -> str:
    settings = get_settings()

    current_queue_job_id: str | None = None
    try:
        from rq import get_current_job

        current_job = get_current_job()
        if current_job is not None:
            current_queue_job_id = str(current_job.id)
    except Exception:  # noqa: BLE001
        current_queue_job_id = None

    with session_scope(settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} was not found.")

        if bool(job.stop_requested):
            job.status = JobStatus.DISCARDED.value
            job.stage = "discarded"
            job.progress = 0
            job.stage_progress = 0
            job.error_message = "Discarded by user."
            snapshot = _job_snapshot(job)
            session.flush()
            cleanup_job_artifacts(snapshot, settings)
            return "discarded"

        job.status = JobStatus.PROCESSING.value
        job.stage = "starting_parse"
        job.progress = 1
        job.stage_progress = 0
        if current_queue_job_id:
            job.queue_job_id = current_queue_job_id
        job.chapter_index = 0
        job.chapter_total = 0
        job.paragraph_done = 0
        job.paragraph_total = 0
        session.flush()
        session.expunge(job)

    def should_stop() -> bool:
        with session_scope(settings) as session:
            current = session.get(Job, job_id)
            if current is None:
                return True
            return bool(current.stop_requested)

    def set_stage(stage: str, progress: int, stage_progress: int) -> None:
        update_job_fields(
            job_id,
            settings,
            stage=stage,
            progress=max(0, min(100, progress)),
            stage_progress=max(0, min(100, stage_progress)),
        )

    def set_counters(chapter_index: int, chapter_total: int, paragraph_done: int, paragraph_total: int) -> None:
        update_job_fields(
            job_id,
            settings,
            chapter_index=max(0, chapter_index),
            chapter_total=max(0, chapter_total),
            paragraph_done=max(0, paragraph_done),
            paragraph_total=max(0, paragraph_total),
        )

    def append_log(line: str) -> None:
        append_job_log(job_id, line, settings)

    try:
        parse_outcome = parse_source_for_job(
            job_id=job_id,
            source_path=Path(job.source_path),
            source_kind=job.source_kind,
            cover_path=Path(job.cover_path) if job.cover_path else None,
            set_stage=set_stage,
            set_counters=set_counters,
            append_log=append_log,
            should_stop=should_stop,
            settings=settings,
        )
        selected_indexes = [int(item["index"]) for item in parse_outcome.chapter_manifest]
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.PARSED.value,
            stage="parsed",
            progress=100,
            stage_progress=100,
            stop_requested=0,
            queue_job_id=None,
            output_path=None,
            error_message=None,
            parsed_text_path=str(parse_outcome.parsed_text_path),
            parsed_cover_path=str(parse_outcome.parsed_cover_path) if parse_outcome.parsed_cover_path else None,
            parsed_book_path=str(parse_outcome.parsed_book_path),
            chapter_manifest_json=json.dumps(parse_outcome.chapter_manifest, ensure_ascii=True),
            selected_chapters_json=json.dumps(selected_indexes),
            selected_chapter_total=parse_outcome.chapter_total,
            selected_paragraph_total=parse_outcome.paragraph_total,
            chapter_index=0,
            chapter_total=parse_outcome.chapter_total,
            paragraph_done=0,
            paragraph_total=parse_outcome.paragraph_total,
        )
        append_job_log(job_id, "Parse completed. Select chapters and start generation.", settings)
        return "parsed"
    except ConversionDiscarded as exc:
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.DISCARDED.value,
            stage="discarded",
            progress=0,
            stage_progress=0,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Discarded: {exc}", settings)
        discarded_job = get_job(job_id, settings)
        if discarded_job is not None:
            cleanup_job_artifacts(discarded_job, settings)
        return "discarded"
    except ConversionError as exc:
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.FAILED.value,
            stage="failed",
            stage_progress=100,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Failed: {exc}", settings)
        raise
    except Exception as exc:  # noqa: BLE001
        if should_stop():
            update_job_fields(
                job_id,
                settings,
                status=JobStatus.DISCARDED.value,
                stage="discarded",
                progress=0,
                stage_progress=0,
                error_message="Discarded by user.",
            )
            append_job_log(job_id, "Discarded by user.", settings)
            discarded_job = get_job(job_id, settings)
            if discarded_job is not None:
                cleanup_job_artifacts(discarded_job, settings)
            return "discarded"

        update_job_fields(
            job_id,
            settings,
            status=JobStatus.FAILED.value,
            stage="failed",
            stage_progress=100,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Unexpected failure: {exc}", settings)
        raise


def run_generation_job(job_id: str) -> str:
    settings = get_settings()

    current_queue_job_id: str | None = None
    try:
        from rq import get_current_job

        current_job = get_current_job()
        if current_job is not None:
            current_queue_job_id = str(current_job.id)
    except Exception:  # noqa: BLE001
        current_queue_job_id = None

    with session_scope(settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} was not found.")

        current_status = (job.status or "").strip().lower()
        current_stage = (job.stage or "").strip().lower()
        if current_status == JobStatus.QUEUED.value and current_stage == "queued_generation":
            pass
        elif current_status != JobStatus.PARSED.value:
            raise ValueError(f"Job {job_id} is not ready for generation.")

        if bool(job.stop_requested):
            job.status = JobStatus.DISCARDED.value
            job.stage = "discarded"
            job.progress = 0
            job.stage_progress = 0
            job.error_message = "Discarded by user."
            snapshot = _job_snapshot(job)
            session.flush()
            cleanup_job_artifacts(snapshot, settings)
            return "discarded"

        job.status = JobStatus.PROCESSING.value
        job.stage = "starting_generation"
        job.progress = 1
        job.stage_progress = 0
        if current_queue_job_id:
            job.queue_job_id = current_queue_job_id
        job.chapter_index = 0
        job.paragraph_done = 0
        session.flush()
        session.expunge(job)

    def should_stop() -> bool:
        with session_scope(settings) as session:
            current = session.get(Job, job_id)
            if current is None:
                return True
            return bool(current.stop_requested)

    def set_stage(stage: str, progress: int, stage_progress: int) -> None:
        update_job_fields(
            job_id,
            settings,
            stage=stage,
            progress=max(0, min(100, progress)),
            stage_progress=max(0, min(100, stage_progress)),
        )

    def set_counters(chapter_index: int, chapter_total: int, paragraph_done: int, paragraph_total: int) -> None:
        update_job_fields(
            job_id,
            settings,
            chapter_index=max(0, chapter_index),
            chapter_total=max(0, chapter_total),
            paragraph_done=max(0, paragraph_done),
            paragraph_total=max(0, paragraph_total),
        )

    def append_log(line: str) -> None:
        append_job_log(job_id, line, settings)

    job = get_job(job_id, settings)
    if job is None:
        raise ValueError(f"Job {job_id} was not found before generation.")

    if not job.parsed_book_path or not job.parsed_text_path or not job.chapter_manifest_json:
        raise ValueError("Job parse artifacts are missing. Parse the source again.")

    chapter_manifest = json.loads(job.chapter_manifest_json)
    if not isinstance(chapter_manifest, list):
        raise ValueError("Job chapter manifest is malformed.")

    selected_indexes: list[int] = []
    if job.selected_chapters_json:
        raw_selected = json.loads(job.selected_chapters_json)
        if isinstance(raw_selected, list):
            selected_indexes = [int(item) for item in raw_selected]

    try:
        output_path, normalized_selected, selected_chapters, selected_paragraphs = generate_from_parsed(
            job_id=job_id,
            source_path=Path(job.source_path),
            engine=job.engine,
            speaker=job.speaker,
            speed=float(job.speed),
            voice_rate=job.voice_rate,
            voice_volume=job.voice_volume,
            voice_pitch=job.voice_pitch,
            paragraphpause=job.paragraphpause,
            notitles=bool(job.notitles),
            parsed_text_path=Path(job.parsed_text_path),
            parsed_cover_path=Path(job.parsed_cover_path) if job.parsed_cover_path else None,
            parsed_book_path=Path(job.parsed_book_path),
            chapter_manifest=chapter_manifest,
            selected_chapter_indexes=selected_indexes,
            set_stage=set_stage,
            set_counters=set_counters,
            append_log=append_log,
            should_stop=should_stop,
            settings=settings,
        )
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.COMPLETED.value,
            stage="completed",
            progress=100,
            stage_progress=100,
            stop_requested=0,
            queue_job_id=None,
            output_path=str(output_path),
            selected_chapters_json=json.dumps(normalized_selected),
            selected_chapter_total=selected_chapters,
            selected_paragraph_total=selected_paragraphs,
            chapter_index=selected_chapters,
            chapter_total=selected_chapters,
            paragraph_done=selected_paragraphs,
            paragraph_total=selected_paragraphs,
            error_message=None,
        )
        append_job_log(job_id, f"Completed: {output_path}", settings)
        return str(output_path)
    except ConversionDiscarded as exc:
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.DISCARDED.value,
            stage="discarded",
            progress=0,
            stage_progress=0,
            queue_job_id=None,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Discarded: {exc}", settings)
        discarded_job = get_job(job_id, settings)
        if discarded_job is not None:
            cleanup_job_artifacts(discarded_job, settings)
        return "discarded"
    except ConversionError as exc:
        update_job_fields(
            job_id,
            settings,
            status=JobStatus.FAILED.value,
            stage="failed",
            stage_progress=100,
            queue_job_id=None,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Failed: {exc}", settings)
        raise
    except Exception as exc:  # noqa: BLE001
        if should_stop():
            update_job_fields(
                job_id,
                settings,
                status=JobStatus.DISCARDED.value,
                stage="discarded",
                progress=0,
                stage_progress=0,
                queue_job_id=None,
                error_message="Discarded by user.",
            )
            append_job_log(job_id, "Discarded by user.", settings)
            discarded_job = get_job(job_id, settings)
            if discarded_job is not None:
                cleanup_job_artifacts(discarded_job, settings)
            return "discarded"

        update_job_fields(
            job_id,
            settings,
            status=JobStatus.FAILED.value,
            stage="failed",
            stage_progress=100,
            queue_job_id=None,
            error_message=str(exc),
        )
        append_job_log(job_id, f"Unexpected failure: {exc}", settings)
        raise
