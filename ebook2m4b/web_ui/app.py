from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db import init_db
from ..jobs import (
    cleanup_generated_files,
    create_job,
    enqueue_conversion,
    enqueue_generation,
    get_job,
    list_recent_jobs,
    request_discard_job,
    update_job_fields,
)
from ..models import Job, JobStatus
from ..settings import Settings, get_settings
from ..storage import ensure_storage_dirs, list_existing_source_files, persist_text_input, persist_uploads
from ..tts_providers import get_engine, get_engine_info_list


def serialize_job(job: Job) -> dict:
    engine_id = (job.engine or "kokoro").strip().lower()
    status_value = (job.status or "").strip().lower() or JobStatus.QUEUED.value
    stage_progress = max(0, min(100, int(job.stage_progress or 0)))
    if stage_progress == 0 and status_value in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.DISCARDED.value,
    }:
        stage_progress = 100

    speaker_meta = None
    try:
        engine = get_engine(engine_id)
        speaker_profile = engine.get_speaker(job.speaker)
        if speaker_profile is not None:
            speaker_meta = speaker_profile.to_dict()
    except Exception:  # noqa: BLE001
        speaker_meta = None

    chapter_total = max(0, int(job.chapter_total or 0))
    chapter_index = max(0, int(job.chapter_index or 0))
    paragraph_total = max(0, int(job.paragraph_total or 0))
    paragraph_done = max(0, int(job.paragraph_done or 0))

    chapter_manifest: list[dict] = []
    if job.chapter_manifest_json:
        try:
            payload = json.loads(job.chapter_manifest_json)
            if isinstance(payload, list):
                chapter_manifest = [row for row in payload if isinstance(row, dict)]
        except Exception:  # noqa: BLE001
            chapter_manifest = []

    selected_chapters: list[int] = []
    if job.selected_chapters_json:
        try:
            payload = json.loads(job.selected_chapters_json)
            if isinstance(payload, list):
                selected_chapters = [int(item) for item in payload]
        except Exception:  # noqa: BLE001
            selected_chapters = []

    output_name = Path(job.output_path).name if job.output_path else None
    last_logs = "\n".join(job.log_text.splitlines()[-8:]) if job.log_text else ""
    can_poll = status_value in {JobStatus.QUEUED.value, JobStatus.PROCESSING.value}
    can_discard = status_value != JobStatus.DISCARDED.value
    remove_from_list = status_value in {
        JobStatus.FAILED.value,
        JobStatus.DISCARDED.value,
    }

    return {
        "id": job.id,
        "status": status_value,
        "stage": job.stage,
        "progress": max(0, min(100, job.progress)),
        "stage_progress": stage_progress,
        "source_path": job.source_path,
        "source_name": Path(job.source_path).name,
        "engine": engine_id,
        "speaker": job.speaker,
        "speaker_meta": speaker_meta,
        "voice_rate": job.voice_rate,
        "voice_volume": job.voice_volume,
        "voice_pitch": job.voice_pitch,
        "chapter_index": chapter_index,
        "chapter_total": chapter_total,
        "paragraph_done": paragraph_done,
        "paragraph_total": paragraph_total,
        "error_message": job.error_message,
        "output_path": job.output_path,
        "output_name": output_name,
        "download_url": f"/downloads/{job.id}" if job.output_path else None,
        "preview_url": f"/preview/{job.id}" if job.output_path else None,
        "can_poll": can_poll,
        "can_discard": can_discard,
        "remove_from_list": remove_from_list,
        "selection_ready": status_value == JobStatus.PARSED.value,
        "chapter_manifest": chapter_manifest,
        "selected_chapters": selected_chapters,
        "selected_chapter_total": max(0, int(job.selected_chapter_total or 0)),
        "selected_paragraph_total": max(0, int(job.selected_paragraph_total or 0)),
        "log_preview": last_logs,
        "created_at": job.created_at.isoformat(),
    }


def _resolve_existing_source(existing_path: str, settings: Settings, *, allowed_suffixes: set[str]) -> Path:
    base = settings.data_dir.resolve()
    resolved = (base / existing_path).resolve()
    if not str(resolved).startswith(str(base)):
        raise ValueError("Selected file must be inside /data")
    if not resolved.exists() or not resolved.is_file():
        raise ValueError("Selected file does not exist")
    if resolved.suffix.lower() not in allowed_suffixes:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Selected file must be one of: {allowed}")
    return resolved


def _filtered_speakers(engine_id: str, locale: str | None = None) -> list[dict]:
    engine = get_engine(engine_id)
    speaker_rows = [item.to_dict() for item in engine.list_speakers()]
    if not locale:
        return speaker_rows

    prefix = locale.strip().lower()
    if not prefix:
        return speaker_rows

    return [
        row
        for row in speaker_rows
        if str(row.get("language_code") or "").strip().lower().startswith(prefix)
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    ensure_storage_dirs(active_settings)
    init_db(active_settings)

    app = FastAPI(title=active_settings.app_name, debug=active_settings.debug)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        engine_infos = [item.to_dict() for item in get_engine_info_list()]
        selected_engine = active_settings.default_engine
        try:
            engine_obj = get_engine(selected_engine)
        except ValueError:
            selected_engine = engine_infos[0]["id"] if engine_infos else "kokoro"
            engine_obj = get_engine(selected_engine)

        speakers = [item.to_dict() for item in engine_obj.list_speakers()]
        speaker_ids = {item["id"] for item in speakers}
        selected_speaker = (
            active_settings.default_speaker
            if active_settings.default_speaker in speaker_ids
            else (speakers[0]["id"] if speakers else "")
        )

        jobs = [serialize_job(job) for job in list_recent_jobs(settings=active_settings)]
        existing_files = list_existing_source_files(active_settings)
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "app_name": active_settings.app_name,
                "jobs": jobs,
                "existing_files": existing_files,
                "engines": engine_infos,
                "speakers": speakers,
                "defaults": {
                    "source_mode": "upload",
                    "engine": selected_engine,
                    "speaker": selected_speaker,
                    "speed": active_settings.default_speed,
                    "voice_rate": active_settings.default_voice_rate,
                    "voice_volume": active_settings.default_voice_volume,
                    "voice_pitch": active_settings.default_voice_pitch,
                    "edge_locale_filter": active_settings.default_edge_locale_filter,
                    "paragraphpause": active_settings.default_paragraphpause,
                    "notitles": active_settings.default_notitles,
                },
                "selected_speaker": selected_speaker,
            },
        )

    @app.get("/api/engines")
    async def api_engines() -> JSONResponse:
        engines = [item.to_dict() for item in get_engine_info_list()]
        return JSONResponse({"engines": engines, "default_engine": active_settings.default_engine})

    @app.get("/api/speakers/{engine_id}")
    async def api_speakers(engine_id: str, locale: str = Query(default="")) -> JSONResponse:
        try:
            speaker_rows = _filtered_speakers(engine_id, locale=locale)
            engine = get_engine(engine_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse({"engine": engine.info.to_dict(), "speakers": speaker_rows})

    @app.post("/jobs/create", response_class=HTMLResponse)
    async def create_job_route(
        request: Request,
        file: UploadFile | None = File(default=None),
        existing_path: str = Form(default=""),
        pasted_text: str = Form(default=""),
        source_mode: str = Form(default=""),
        engine: str = Form(default="kokoro"),
        speaker: str = Form(default=""),
        cover_path: str = Form(default=""),
        speed: float = Form(default=1.3),
        voice_rate: str = Form(default="+0%"),
        voice_volume: str = Form(default="+0%"),
        voice_pitch: str = Form(default="+0Hz"),
        paragraphpause: int = Form(default=600),
        notitles: bool = Form(default=False),
    ):
        try:
            source_path: Path | None = None

            selected_source_mode = source_mode.strip().lower()
            if selected_source_mode not in {"upload", "existing", "paste"}:
                selected_source_mode = ""

            if selected_source_mode == "upload":
                if file is None or not file.filename:
                    raise ValueError("Choose a file to upload.")
                upload_seed = str(uuid4())
                stored = await persist_uploads(upload_seed, [file], active_settings)
                if not stored:
                    raise ValueError("Upload did not contain a file")
                source_path = stored[0]
            elif selected_source_mode == "existing":
                if not existing_path.strip():
                    raise ValueError("Choose an existing source file from /data.")
                source_path = _resolve_existing_source(
                    existing_path.strip(),
                    active_settings,
                    allowed_suffixes={".epub", ".txt"},
                )
            elif selected_source_mode == "paste":
                if not pasted_text.strip():
                    raise ValueError("Paste text content before parsing.")
                upload_seed = str(uuid4())
                source_path = persist_text_input(upload_seed, pasted_text.strip(), active_settings)
            else:
                # Backward-compatible fallback for clients that do not send source_mode.
                if file is not None and file.filename:
                    upload_seed = str(uuid4())
                    stored = await persist_uploads(upload_seed, [file], active_settings)
                    if not stored:
                        raise ValueError("Upload did not contain a file")
                    source_path = stored[0]
                elif existing_path.strip():
                    source_path = _resolve_existing_source(
                        existing_path.strip(),
                        active_settings,
                        allowed_suffixes={".epub", ".txt"},
                    )
                elif pasted_text.strip():
                    upload_seed = str(uuid4())
                    source_path = persist_text_input(upload_seed, pasted_text.strip(), active_settings)
                else:
                    raise ValueError("Upload a file, pick an existing source, or paste text")

            source_kind = source_path.suffix.lower().lstrip(".")
            cover = None
            if cover_path.strip():
                cover = _resolve_existing_source(
                    cover_path.strip(),
                    active_settings,
                    allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
                )

            selected_engine = (engine.strip() or active_settings.default_engine).lower()
            tts_engine = get_engine(selected_engine)
            available_speakers = tts_engine.list_speakers()

            selected_speaker = speaker.strip()
            if not selected_speaker:
                if selected_engine == "kokoro":
                    selected_speaker = active_settings.default_speaker
                elif available_speakers:
                    selected_speaker = available_speakers[0].id

            speaker_profile = tts_engine.get_speaker(selected_speaker)
            if speaker_profile is None:
                raise ValueError(
                    f"Speaker '{selected_speaker}' is not available for engine '{selected_engine}'."
                )

            job = create_job(
                source_path=source_path,
                source_kind=source_kind,
                engine=selected_engine,
                speaker=speaker_profile.id,
                cover_path=cover,
                speed=speed,
                voice_rate=voice_rate.strip() or active_settings.default_voice_rate,
                voice_volume=voice_volume.strip() or active_settings.default_voice_volume,
                voice_pitch=voice_pitch.strip() or active_settings.default_voice_pitch,
                paragraphpause=paragraphpause,
                notitles=notitles,
                settings=active_settings,
            )
            enqueue_conversion(job.id, active_settings)
            fresh = get_job(job.id, active_settings)
            if fresh is None:
                raise ValueError("Failed to load job after creation")
            return templates.TemplateResponse(
                request,
                "partials/job_card.html",
                {"job": serialize_job(fresh)},
            )
        except Exception as exc:  # noqa: BLE001
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": str(exc), "kind": "error"},
                status_code=400,
            )

    @app.post("/jobs/{job_id}/generate", response_class=HTMLResponse)
    async def generate_job_route(request: Request, job_id: str):
        try:
            job = get_job(job_id, active_settings)
            if job is None:
                raise ValueError("Job not found")

            status_value = (job.status or "").strip().lower()
            if status_value != JobStatus.PARSED.value:
                raise ValueError("This job is not ready for chapter selection.")

            chapter_manifest: list[dict] = []
            if job.chapter_manifest_json:
                payload = json.loads(job.chapter_manifest_json)
                if isinstance(payload, list):
                    chapter_manifest = [row for row in payload if isinstance(row, dict)]

            if not chapter_manifest:
                raise ValueError("No parsed chapters were found for this job.")

            form = await request.form()
            selected_raw = form.getlist("selected_chapters")
            selected_indexes: list[int] = []
            for raw_value in selected_raw:
                try:
                    numeric = int(str(raw_value))
                except Exception:  # noqa: BLE001
                    continue
                if numeric not in selected_indexes:
                    selected_indexes.append(numeric)

            if not selected_indexes:
                selected_indexes = [int(row.get("index") or 0) for row in chapter_manifest if int(row.get("index") or 0) > 0]

            selected_lookup = set(selected_indexes)
            selected_paragraph_total = sum(
                max(0, int(row.get("paragraph_count") or 0))
                for row in chapter_manifest
                if int(row.get("index") or 0) in selected_lookup
            )

            update_job_fields(
                job_id,
                active_settings,
                selected_chapters_json=json.dumps(selected_indexes),
                selected_chapter_total=len(selected_indexes),
                selected_paragraph_total=selected_paragraph_total,
                error_message=None,
            )
            enqueue_generation(job_id, active_settings)

            fresh = get_job(job_id, active_settings)
            if fresh is None:
                raise ValueError("Failed to load job after generation enqueue")
            return templates.TemplateResponse(
                request,
                "partials/job_card.html",
                {"job": serialize_job(fresh)},
            )
        except Exception as exc:  # noqa: BLE001
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": str(exc), "kind": "error"},
                status_code=400,
            )

    @app.post("/jobs/{job_id}/discard", response_class=HTMLResponse)
    async def discard_job_route(request: Request, job_id: str):
        try:
            job = request_discard_job(job_id, active_settings)
            return templates.TemplateResponse(
                request,
                "partials/job_card.html",
                {"job": serialize_job(job)},
            )
        except Exception as exc:  # noqa: BLE001
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": str(exc), "kind": "error"},
                status_code=400,
            )

    @app.post("/jobs/cleanup", response_class=HTMLResponse)
    async def cleanup_route(request: Request):
        try:
            summary = cleanup_generated_files(active_settings)
            message = (
                f"Cleanup complete. Removed {summary['deleted_jobs']} jobs and generated artifacts. "
                f"Discarded active jobs: {summary['discarded_active']}."
            )
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": message, "kind": "info"},
            )
        except Exception as exc:  # noqa: BLE001
            return templates.TemplateResponse(
                request,
                "partials/notice.html",
                {"message": str(exc), "kind": "error"},
                status_code=400,
            )

    @app.get("/jobs/{job_id}/live", response_class=HTMLResponse)
    async def job_live(request: Request, job_id: str):
        job = get_job(job_id, active_settings)
        if job is None:
            return HTMLResponse(
                content=(
                    "<script>"
                    f"(function(){{const card=document.getElementById('job-{job_id}');if(card){{card.remove();}}}})();"
                    "</script>"
                )
            )
        return templates.TemplateResponse(request, "partials/job_live.html", {"job": serialize_job(job)})

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: str, partial: int = Query(default=0)):
        job = get_job(job_id, active_settings)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        payload = serialize_job(job)
        if partial:
            return templates.TemplateResponse(request, "partials/job_live.html", {"job": payload})
        return templates.TemplateResponse(request, "job_detail.html", {"app_name": active_settings.app_name, "job": payload})

    @app.get("/downloads/{job_id}")
    async def download(job_id: str):
        job = get_job(job_id, active_settings)
        if job is None or not job.output_path:
            raise HTTPException(status_code=404, detail="Output not found")
        output_path = Path(job.output_path)
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Output file missing on disk")
        return FileResponse(path=output_path, filename=output_path.name)

    @app.get("/preview/{job_id}")
    async def preview(job_id: str):
        job = get_job(job_id, active_settings)
        if job is None or not job.output_path:
            raise HTTPException(status_code=404, detail="Output not found")
        output_path = Path(job.output_path)
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Output file missing on disk")
        return FileResponse(path=output_path, media_type="audio/mp4")

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "ebook2m4b.web_ui.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
