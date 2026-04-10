from __future__ import annotations

from rq import Worker

from .db import init_db
from .queueing import get_redis_connection
from .settings import get_settings
from .storage import ensure_storage_dirs


def main() -> None:
    settings = get_settings()
    ensure_storage_dirs(settings)
    init_db(settings)
    connection = get_redis_connection(settings)
    worker = Worker([settings.queue_name], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
