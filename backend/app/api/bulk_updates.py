import logging
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ERROR_RESPONSES
from app.schemas.bulk_updates import (
    BulkUpdateCreate,
    BulkUpdateDetail,
    BulkUpdateRetry,
    BulkUpdateSummary,
    ImpactOut,
    ImpactRequest,
    VariableBulkUpdateCreate,
    VariableImpactOut,
)
from app.services import bulk_updates
from app.tasks import defer_publication, defer_render

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bulk updates"])
SessionDep = Annotated[Session, Depends(get_session)]


def _defer_all(queue: bulk_updates.RenderQueue) -> None:
    # 큐 등록에 실패한 버전은 PENDING으로 남으며, 작업 결과에서 진행 중으로 보인다.
    for defer, ids in ((defer_render, queue.versions), (defer_publication, queue.publications)):
        for target_id in ids:
            try:
                defer(target_id)
            except Exception:
                logger.exception("렌더링 작업 등록 실패: %s", target_id)


@router.post("/bulk-updates/preview", responses=ERROR_RESPONSES)
def preview(data: ImpactRequest, session: SessionDep) -> ImpactOut:
    """모듈 리비전 적용 대상(판매 중 상품·사용 중 문서)과 제외 대상, 변경 전후 문구."""
    return bulk_updates.analyze_impact(session, data.clause_id, data.revision_no)


@router.post("/bulk-updates", status_code=status.HTTP_202_ACCEPTED, responses=ERROR_RESPONSES)
def create(data: BulkUpdateCreate, session: SessionDep) -> BulkUpdateDetail:
    job, to_render = bulk_updates.create_job(session, data)
    session.commit()
    _defer_all(to_render)
    return bulk_updates.job_detail(session, job.id)


@router.get("/bulk-updates")
def list_jobs(session: SessionDep) -> Sequence[BulkUpdateSummary]:
    return bulk_updates.list_jobs(session)


@router.get("/bulk-updates/{job_id}", responses=ERROR_RESPONSES)
def get_job(job_id: uuid.UUID, session: SessionDep) -> BulkUpdateDetail:
    return bulk_updates.job_detail(session, job_id)


@router.post("/bulk-updates/{job_id}/retry", responses=ERROR_RESPONSES)
def retry(
    job_id: uuid.UUID, session: SessionDep, data: BulkUpdateRetry | None = None
) -> BulkUpdateDetail:
    """실패한 대상만 다시 처리한다. 값이 비어 실패한 문서에는 variable_values를 넣는다."""
    job, to_render = bulk_updates.retry_job(session, job_id, data)
    session.commit()
    _defer_all(to_render)
    return bulk_updates.job_detail(session, job.id)


@router.post("/variables/{variable_id}/bulk-updates/preview", responses=ERROR_RESPONSES)
def preview_variable(variable_id: uuid.UUID, session: SessionDep) -> VariableImpactOut:
    """변수 기본값을 바꾼 뒤 다시 발행할 문서. 문서에 값을 따로 입력한 문서는 따로 보여 준다."""
    return bulk_updates.analyze_variable(session, variable_id)


@router.post(
    "/variables/{variable_id}/bulk-updates",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERROR_RESPONSES,
)
def create_variable_job(
    variable_id: uuid.UUID, data: VariableBulkUpdateCreate, session: SessionDep
) -> BulkUpdateDetail:
    """변수의 현재 기본값을 사용 중 문서에 반영하고 다시 발행한다."""
    job, to_render = bulk_updates.create_variable_job(session, variable_id, data)
    session.commit()
    _defer_all(to_render)
    return bulk_updates.job_detail(session, job.id)
