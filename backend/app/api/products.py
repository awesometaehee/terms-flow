import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ERROR_RESPONSES
from app.models import ProductStatus
from app.schemas.document_sets import DocumentSetSummary
from app.schemas.products import (
    CompanyCreate,
    CompanyOut,
    ProductCreate,
    ProductDetail,
    ProductSummary,
    ProductUpdate,
    RevisionDetail,
    RevisionSummary,
    StatusChange,
    StatusHistoryOut,
)
from app.services import document_sets, products

router = APIRouter(tags=["products"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/companies", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_company(data: CompanyCreate, session: SessionDep) -> CompanyOut:
    company = products.create_company(session, data)
    session.commit()
    return CompanyOut.model_validate(company)


@router.get("/companies")
def list_companies(session: SessionDep) -> list[CompanyOut]:
    return [CompanyOut.model_validate(c) for c in products.list_companies(session)]


@router.post("/products", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_product(data: ProductCreate, session: SessionDep) -> ProductDetail:
    product = products.create_product(session, data)
    session.commit()
    return products.to_detail(session, product)


@router.get("/products")
def list_products(
    session: SessionDep,
    status: ProductStatus | None = None,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
) -> list[ProductSummary]:
    return products.list_products(session, status=status, company_id=company_id, q=q)


@router.get("/products/{product_id}", responses=ERROR_RESPONSES)
def get_product(product_id: uuid.UUID, session: SessionDep) -> ProductDetail:
    return products.to_detail(session, products.get_product(session, product_id))


@router.patch("/products/{product_id}", responses=ERROR_RESPONSES)
def update_product(
    product_id: uuid.UUID, data: ProductUpdate, session: SessionDep
) -> ProductDetail:
    product = products.update_product(session, product_id, data)
    session.commit()
    return products.to_detail(session, product)


@router.post("/products/{product_id}/status", responses=ERROR_RESPONSES)
def change_status(product_id: uuid.UUID, data: StatusChange, session: SessionDep) -> ProductDetail:
    product = products.change_status(session, product_id, data)
    session.commit()
    return products.to_detail(session, product)


@router.get("/products/{product_id}/status-history", responses=ERROR_RESPONSES)
def list_status_history(product_id: uuid.UUID, session: SessionDep) -> list[StatusHistoryOut]:
    rows = products.list_status_history(session, product_id)
    return [StatusHistoryOut.model_validate(r) for r in rows]


@router.get("/products/{product_id}/revisions", responses=ERROR_RESPONSES)
def list_revisions(product_id: uuid.UUID, session: SessionDep) -> list[RevisionSummary]:
    return [RevisionSummary.model_validate(r) for r in products.list_revisions(session, product_id)]


@router.get("/products/{product_id}/revisions/{revision_no}", responses=ERROR_RESPONSES)
def get_revision(product_id: uuid.UUID, revision_no: int, session: SessionDep) -> RevisionDetail:
    return RevisionDetail.model_validate(products.get_revision(session, product_id, revision_no))


@router.get("/products/{product_id}/document-sets", responses=ERROR_RESPONSES)
def list_document_sets(product_id: uuid.UUID, session: SessionDep) -> list[DocumentSetSummary]:
    rows = document_sets.list_document_sets(session, product_id)
    return [DocumentSetSummary.model_validate(r) for r in rows]
