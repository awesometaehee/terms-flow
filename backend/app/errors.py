"""API 오류 형식과 예외 처리기.

모든 오류 응답은 {"code", "message", "errors": [{"path", "message"}]} 형식이다.
path는 요청 본문 기준 경로다. 예: variants[1].composition.groups[0].items[2].label
"""

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

RESTRICT_VIOLATION = "23001"
UNIQUE_VIOLATION = "23505"


class FieldError(BaseModel):
    path: str
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    errors: list[FieldError] = []


# 라우터의 responses=에 사용하는 OpenAPI 오류 응답 문서
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def format_path(parts: Iterable[Any]) -> str:
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def join_path(prefix: str, path: str) -> str:
    if not path:
        return prefix
    return prefix + path if path.startswith("[") else f"{prefix}.{path}"


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"

    def __init__(self, message: str, errors: Sequence[FieldError] = (), code: str | None = None):
        super().__init__(message)
        self.message = message
        self.errors = list(errors)
        if code is not None:
            self.code = code

    def as_body(self) -> ErrorResponse:
        return ErrorResponse(code=self.code, message=self.message, errors=self.errors)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    """상태·버전 충돌. code 예: PRODUCT_ENDED, VERSION_CONFLICT, INVALID_STATUS_TRANSITION"""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"

    def __init__(self, errors: Sequence[FieldError]):
        super().__init__("입력값이 올바르지 않습니다.", errors)


class CompositionError(AppError):
    """템플릿 선택·조항 조합 실패 (예: 적용할 템플릿 없음, 필수 조항 제외 요청)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "COMPOSITION_ERROR"

    def __init__(self, errors: Sequence[FieldError]):
        super().__init__("문서를 조합할 수 없습니다.", errors)


def _response(status_code: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump())


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _response(exc.status_code, exc.as_body())

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = list(err.get("loc", ()))
            if loc and loc[0] in ("body", "query", "path"):
                loc = loc[1:]
            errors.append(FieldError(path=format_path(loc), message=err.get("msg", "")))
        return _response(status.HTTP_422_UNPROCESSABLE_CONTENT, ValidationFailed(errors).as_body())

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError) -> JSONResponse:
        body = ErrorResponse(
            code="VERSION_CONFLICT", message="다른 사용자가 먼저 수정했습니다. 다시 조회하세요."
        )
        return _response(status.HTTP_409_CONFLICT, body)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == RESTRICT_VIOLATION:
            diag = getattr(exc.orig, "diag", None)
            message = getattr(diag, "message_primary", None) or "변경할 수 없는 데이터입니다."
            return _response(
                status.HTTP_409_CONFLICT, ErrorResponse(code="IMMUTABLE", message=message)
            )
        if sqlstate == UNIQUE_VIOLATION:
            body = ErrorResponse(code="DUPLICATE", message="이미 존재하는 값입니다.")
            return _response(status.HTTP_409_CONFLICT, body)
        raise exc
