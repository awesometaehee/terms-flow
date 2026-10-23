"""worker: PENDING 문서 세트 버전을 렌더링해 발행한다.

- manifest에 고정된 템플릿·조항 리비전과 상품 버전 스냅샷만 사용한다 (최신 조항을 다시 읽지 않음).
- 모든 파일 업로드가 끝난 뒤 한 트랜잭션에서 파일 행·manifest·PUBLISHED 상태를 저장한다.
- 실패하면 FAILED와 사유를 남기고 기존 발행본은 건드리지 않는다.
"""

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path

import sqlalchemy as sa

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import (
    Document,
    DocumentFile,
    DocumentSetStatus,
    DocumentSetVersion,
    DocumentStatus,
    FileFormat,
    Product,
    ProductRevision,
    ProductStatus,
    Publication,
    PublicationFile,
)
from app.rendering import kms
from app.rendering.loader import plan_from_manifest
from app.rendering.output import RenderedFile, render_outputs, render_single
from app.schemas.document_sets import DocumentSetManifest, ManifestFile
from app.storage import put_file

logger = logging.getLogger(__name__)

CONTENT_TYPES = {FileFormat.PDF: "application/pdf", FileFormat.PNG: "image/png"}


def storage_key(version_id: uuid.UUID, run_id: uuid.UUID, file_name: str) -> str:
    """렌더링 실행마다 새 경로를 쓴다. 실패 후 재시도해도 이전 실행의 파일을 덮어쓰지 않는다."""
    return f"document-sets/{version_id}/{run_id}/{file_name}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mark_failed(version: DocumentSetVersion, reason: str) -> None:
    version.status = DocumentSetStatus.FAILED
    version.failure_reason = reason[:2000]


def render_and_publish(version_id: uuid.UUID) -> DocumentSetStatus:
    with get_sessionmaker()() as session:
        # 같은 버전을 두 worker가 동시에 처리하지 않도록 행을 잠근다.
        version = session.scalar(
            sa.select(DocumentSetVersion)
            .where(DocumentSetVersion.id == version_id)
            .with_for_update()
        )
        if version is None:
            raise LookupError(f"문서 세트 버전이 없습니다: {version_id}")
        if version.status != DocumentSetStatus.PENDING:
            return version.status  # 이미 처리됨 (재시도·중복 실행)

        product = session.get(Product, version.product_id)
        assert product is not None
        if product.status == ProductStatus.ENDED:
            _mark_failed(version, "판매 종료(ENDED)된 상품이라 발행하지 않았습니다.")
            session.commit()
            return version.status

        manifest = DocumentSetManifest.model_validate(version.manifest)
        revision = session.get(ProductRevision, version.product_revision_id)
        assert revision is not None
        plan = plan_from_manifest(session, manifest, revision.snapshot)

        run_id = uuid.uuid4()
        stored: list[tuple[RenderedFile, str, str, int]] = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = render_outputs(
                    plan,
                    version_label=f"v{version.version_no}",
                    out_dir=Path(tmp),
                    png_dpi=get_settings().render_png_dpi,
                )
                for f in result.files:
                    key = storage_key(version.id, run_id, f.file_name)
                    put_file(key, f.path, CONTENT_TYPES[f.format])
                    stored.append((f, key, _sha256(f.path), f.path.stat().st_size))
        except Exception as exc:
            logger.exception("문서 세트 렌더링 실패: %s", version_id)
            _mark_failed(version, f"{type(exc).__name__}: {exc}")
            session.commit()
            return version.status

        for f, key, sha, size in stored:
            assert f.document_type is not None
            session.add(
                DocumentFile(
                    document_set_version_id=version.id,
                    document_type=f.document_type,
                    format=f.format,
                    page_no=f.page_no,
                    storage_key=key,
                    sha256=sha,
                    size_bytes=size,
                )
            )
        manifest.renderer_version = result.renderer_version
        manifest.files = [
            ManifestFile(
                document_type=f.document_type,
                format=f.format,
                page_no=f.page_no,
                storage_key=key,
                sha256=sha,
            )
            for f, key, sha, _ in stored
        ]
        version.manifest = manifest.model_dump(mode="json")
        version.status = DocumentSetStatus.PUBLISHED
        version.published_at = sa.func.now()
        session.commit()
        return DocumentSetStatus.PUBLISHED


# --- KMS 문서 발행본 -------------------------------------------------------------------


def publication_storage_key(publication_id: uuid.UUID, run_id: uuid.UUID, file_name: str) -> str:
    return f"publications/{publication_id}/{run_id}/{file_name}"


def render_publication(publication_id: uuid.UUID) -> DocumentSetStatus:
    """PENDING 발행본을 고정된 문서 리비전 스냅샷으로 렌더링해 발행한다."""
    with get_sessionmaker()() as session:
        publication = session.scalar(
            sa.select(Publication)
            .where(Publication.id == publication_id)
            .with_for_update(of=Publication)
        )
        if publication is None:
            raise LookupError(f"발행본이 없습니다: {publication_id}")
        if publication.status != DocumentSetStatus.PENDING:
            return publication.status

        document = session.get(Document, publication.document_id)
        assert document is not None
        if document.status == DocumentStatus.ENDED:
            publication.status = DocumentSetStatus.FAILED
            publication.failure_reason = "종료(ENDED)된 문서라 발행하지 않았습니다."
            session.commit()
            return publication.status

        snapshot = publication.revision.snapshot
        run_id = uuid.uuid4()
        stored: list[tuple[RenderedFile, str, str, int]] = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = render_single(
                    kms.render_html(snapshot),
                    stem=kms.file_stem(snapshot["title"], publication.version_no),
                    footer_label=f"{snapshot['title']} · v{publication.version_no}",
                    out_dir=Path(tmp),
                    png_dpi=get_settings().render_png_dpi,
                )
                for f in result.files:
                    key = publication_storage_key(publication.id, run_id, f.file_name)
                    put_file(key, f.path, CONTENT_TYPES[f.format])
                    stored.append((f, key, _sha256(f.path), f.path.stat().st_size))
        except Exception as exc:
            logger.exception("문서 발행 렌더링 실패: %s", publication_id)
            publication.status = DocumentSetStatus.FAILED
            publication.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
            session.commit()
            return publication.status

        for f, key, sha, size in stored:
            session.add(
                PublicationFile(
                    publication_id=publication.id,
                    format=f.format,
                    page_no=f.page_no,
                    storage_key=key,
                    sha256=sha,
                    size_bytes=size,
                )
            )
        publication.renderer_version = result.renderer_version
        publication.status = DocumentSetStatus.PUBLISHED
        publication.published_at = sa.func.now()
        session.commit()
        return DocumentSetStatus.PUBLISHED
