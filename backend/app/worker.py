"""Procrastinate 작업 큐 앱. 작업 정의는 app/tasks.py."""

import asyncio
import sys

import procrastinate

from app.config import get_settings

# Windows: psycopg 비동기 연결은 Proactor 루프를 지원하지 않으므로 Selector 루프를 쓴다.
# Chromium 실행은 별도 Proactor 루프에서 한다 (app/rendering/output.py).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

queue_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=get_settings().database_conninfo),
    import_paths=["app.tasks"],
)
