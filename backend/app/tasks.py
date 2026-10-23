"""worker 작업 정의. API는 defer_render()로 작업을 넣고, worker 컨테이너가 실행한다."""

import uuid

from app.worker import queue_app

DOCUMENTS_QUEUE = "documents"


@queue_app.task(name="render_document_set", queue=DOCUMENTS_QUEUE)
def render_document_set(version_id: str) -> None:
    # Chromium·Poppler가 있는 worker에서만 import한다.
    from app.rendering.publisher import render_and_publish

    render_and_publish(uuid.UUID(version_id))


def defer_render(version_id: uuid.UUID) -> None:
    # queueing_lock: 같은 버전의 대기 작업이 이미 있으면 새로 넣지 않는다.
    with queue_app.open():
        render_document_set.configure(queueing_lock=str(version_id)).defer(
            version_id=str(version_id)
        )


@queue_app.task(name="render_publication", queue=DOCUMENTS_QUEUE)
def render_publication(publication_id: str) -> None:
    from app.rendering.publisher import render_publication as run

    run(uuid.UUID(publication_id))


def defer_publication(publication_id: uuid.UUID) -> None:
    with queue_app.open():
        render_publication.configure(queueing_lock=f"pub-{publication_id}").defer(
            publication_id=str(publication_id)
        )
