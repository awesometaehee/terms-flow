"""문서 파일 저장소.

- local: STORAGE_LOCAL_DIR 폴더에 저장 키 경로 그대로 저장한다 (로컬 개발 기본).
- s3: S3 호환 스토리지 (운영 저장소용).
두 방식 모두 같은 키에 덮어쓰지 않는다. 키에 문서 세트 버전 ID와 렌더링 실행 ID가 들어가므로
정상적으로는 항상 새 키다.
"""

import shutil
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from app.config import get_settings


def _local_path(key: str) -> Path:
    parts = PurePosixPath(key).parts
    if not parts or any(p in ("..", "") or ":" in p for p in parts) or key.startswith("/"):
        raise ValueError(f"잘못된 저장 키입니다: {key}")
    return get_settings().storage_local_dir.joinpath(*parts)


@lru_cache
def get_s3_client() -> Any:
    import boto3

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def ensure_bucket() -> None:
    """저장 위치(폴더 또는 버킷)가 없으면 만든다."""
    settings = get_settings()
    if settings.storage_backend == "local":
        settings.storage_local_dir.mkdir(parents=True, exist_ok=True)
        return
    from botocore.exceptions import ClientError

    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def check_storage() -> None:
    """저장소에 접근할 수 없으면 예외를 낸다 (헬스체크용)."""
    settings = get_settings()
    if settings.storage_backend == "local":
        if not settings.storage_local_dir.is_dir():
            raise FileNotFoundError(settings.storage_local_dir)
        return
    get_s3_client().head_bucket(Bucket=settings.s3_bucket)


def put_file(key: str, path: Path, content_type: str) -> None:
    settings = get_settings()
    if settings.storage_backend == "local":
        target = _local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # "x" 모드: 이미 있으면 FileExistsError (덮어쓰기 금지)
        with path.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        return
    from botocore.exceptions import ClientError

    client = get_s3_client()
    try:
        client.head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError:
        with path.open("rb") as fh:
            client.put_object(Bucket=settings.s3_bucket, Key=key, Body=fh, ContentType=content_type)
        return
    raise FileExistsError(f"이미 존재하는 저장 키입니다: {key}")


def open_object(key: str) -> BinaryIO:
    """읽기용 파일 객체. 사용 후 close()한다."""
    settings = get_settings()
    if settings.storage_backend == "local":
        return _local_path(key).open("rb")
    response = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    body: BinaryIO = response["Body"]
    return body
