from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from redis import Redis

from .settings import Settings, get_settings

if TYPE_CHECKING:
    from rq import Queue


def get_redis_connection(settings: Settings | None = None) -> Redis:
    active_settings = settings or get_settings()
    return Redis.from_url(active_settings.redis_url)


def get_queue(settings: Settings | None = None) -> Queue:
    from rq import Queue

    active_settings = settings or get_settings()
    return Queue(
        active_settings.queue_name,
        connection=get_redis_connection(active_settings),
        default_timeout=active_settings.job_timeout_seconds,
    )


def dispatch_job(task: Callable, /, *args, settings: Settings | None = None, **kwargs):
    active_settings = settings or get_settings()
    if active_settings.run_jobs_inline:
        return task(*args, **kwargs)
    return get_queue(active_settings).enqueue(task, *args, **kwargs)


def cancel_or_stop_job(queue_job_id: str, settings: Settings | None = None) -> bool:
    from rq.command import send_stop_job_command
    from rq.job import Job as RQJob

    active_settings = settings or get_settings()
    connection = get_redis_connection(active_settings)

    try:
        job = RQJob.fetch(queue_job_id, connection=connection)
    except Exception:  # noqa: BLE001
        return False

    try:
        status = (job.get_status(refresh=True) or "").lower()
    except Exception:  # noqa: BLE001
        status = ""

    if status in {"queued", "deferred", "scheduled"}:
        try:
            job.cancel()
        except Exception:  # noqa: BLE001
            return False
        return True

    if status in {"started", "busy"}:
        try:
            send_stop_job_command(connection, queue_job_id)
        except Exception:  # noqa: BLE001
            return False
        return True

    return False
