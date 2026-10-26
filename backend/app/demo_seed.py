"""검토용 가상 데이터. 실제 회사·상품·고객 정보가 아니며 모든 값에 [샘플]을 붙인다.

실행: python -m app.demo_seed --if-empty   (템플릿·문서가 하나도 없을 때만 넣는다)
"""

import argparse
import uuid
from typing import Any

import sqlalchemy as sa

from app.db import get_sessionmaker
from app.models import Clause, Document, DocumentStatus
from app.schemas.catalog import ClauseCreate
from app.schemas.kms import (
    BlockIn,
    CategoryCreate,
    DocumentCreate,
    DocumentSave,
    DocumentStatusChange,
    VariableCreate,
)
from app.services import catalog, documents, taxonomy

Node = dict[str, Any]


def t(value: str, *marks: Node) -> Node:
    node: Node = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


BOLD: Node = {"type": "bold"}
RED: Node = {"type": "textStyle", "attrs": {"color": "#d92d20"}}


def v(key: str) -> Node:
    return {"type": "variable", "attrs": {"key": key}}


def p(*nodes: Node, align: str | None = None) -> Node:
    para: Node = {"type": "paragraph", "content": list(nodes)}
    if align:
        para["attrs"] = {"textAlign": align}
    return para


def h(text: str) -> Node:
    return {"type": "heading", "attrs": {"level": 2}, "content": [t(text)]}


def doc(*blocks: Node) -> Node:
    return {"type": "doc", "content": list(blocks)}


def cell(*nodes: Node, header: bool = False, bg: str | None = None, **span: int) -> Node:
    attrs: Node = dict(span)
    if bg:
        attrs["background"] = bg
    node: Node = {
        "type": "tableHeader" if header else "tableCell",
        "content": [p(*nodes, align="center")],
    }
    if attrs:
        node["attrs"] = attrs
    return node


def row(*cells: Node) -> Node:
    return {"type": "tableRow", "content": list(cells)}


HEAD = "#d9e2f3"
LABEL = "#f2f2f2"

NOTICES = [
    "서비스 내용은 행사 지역에 따라 달라질 수 있습니다.",
    "해약 시 환급금은 약관에서 정한 기준에 따릅니다.",
]

VARIABLES = [
    ("company_name", "회사명", "[샘플]상조(주)", "약관·설명서의 회사 이름"),
    ("product_name", "상품명", "[샘플] 헤리티지 100", "상품 이름"),
    ("monthly_fee", "월 납입금", "30,000원", "매월 내는 금액"),
    ("installments", "납입 횟수", "120회", "총 납입 횟수"),
    ("contact", "고객센터", "[샘플] 1500-0000", "가상 번호"),
]


def templates(category: dict[str, uuid.UUID]) -> list[ClauseCreate]:
    return [
        ClauseCreate(
            clause_key="demo_purpose",
            title="[샘플] 제1조 (목적)",
            category_id=category["약관"],
            tags=["공통", "샘플"],
            content_json=doc(
                h("제1조 (목적)"),
                p(
                    t("이 약관은 "),
                    v("company_name"),
                    t("(이하 '회사')이 제공하는 "),
                    v("product_name"),
                    t(" 상조 서비스의 이용 조건과 절차를 정하는 것을 목적으로 합니다."),
                ),
            ),
        ),
        ClauseCreate(
            clause_key="demo_payment",
            title="[샘플] 제2조 (납입금)",
            category_id=category["약관"],
            tags=["공통", "샘플"],
            content_json=doc(
                h("제2조 (납입금)"),
                p(
                    t("① 회원은 매월 "),
                    v("monthly_fee"),
                    t("을 "),
                    v("installments"),
                    t(" 동안 납입합니다."),
                ),
                {
                    "type": "orderedList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [p(t("납입 방법: CMS 자동이체, 신용카드"))],
                        },
                        {"type": "listItem", "content": [p(t("납입일: 가입 시 정한 날"))]},
                    ],
                },
            ),
        ),
        ClauseCreate(
            clause_key="demo_product_table",
            title="[샘플] 상품 설명서 표",
            category_id=category["설명서"],
            tags=["상품 설명서", "샘플"],
            content_json=doc(
                {
                    "type": "table",
                    "content": [
                        row(
                            cell(t("제공내용", BOLD), header=True, bg=HEAD, colspan=2),
                            cell(v("product_name"), header=True, bg=HEAD),
                        ),
                        row(
                            cell(t("납입정보", BOLD), bg=LABEL, rowspan=2),
                            cell(t("월 납입금")),
                            cell(v("monthly_fee")),
                        ),
                        row(cell(t("납입 횟수")), cell(v("installments"))),
                        row(
                            cell(t("고인용품", BOLD), bg=LABEL, rowspan=2),
                            cell(t("관")),
                            cell(t("[샘플] 오동나무 4.2cm")),
                        ),
                        row(cell(t("수의")), cell(t("★국내최초★ ", RED), t("[샘플] 명품수의"))),
                        row(
                            cell(t("장의차량", BOLD), bg=LABEL),
                            cell(t("리무진")),
                            cell(t("왕복 400km (초과 시 [샘플] 2,000원/km)")),
                        ),
                    ],
                },
                p(t("※ 위 내용은 검토용 가상 예시입니다.")),
            ),
        ),
        ClauseCreate(
            clause_key="demo_notice",
            title="[샘플] 고객 안내 (2단)",
            category_id=category["설명서"],
            tags=["안내", "샘플"],
            content_json=doc(
                {
                    "type": "columns",
                    "content": [
                        {
                            "type": "column",
                            "attrs": {"width": 70},
                            "content": [
                                p(t("유의사항", BOLD)),
                                {
                                    "type": "bulletList",
                                    "content": [
                                        {"type": "listItem", "content": [p(t(text))]}
                                        for text in NOTICES
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "column",
                            "attrs": {"width": 30},
                            "content": [
                                p(t("고객센터", BOLD)),
                                p(v("contact")),
                                p(t("평일 09:00~18:00")),
                            ],
                        },
                    ],
                }
            ),
        ),
    ]


def seed(if_empty: bool) -> str:
    session = get_sessionmaker()()
    try:
        has_content = session.scalar(
            sa.select(sa.func.count()).select_from(Clause)
        ) or session.scalar(sa.select(sa.func.count()).select_from(Document))
        if if_empty and has_content:
            return "이미 데이터가 있어 가상 데이터를 넣지 않았습니다."

        category = {
            "약관": taxonomy.create_category(session, CategoryCreate(name="[샘플] 약관")).id,
            "설명서": taxonomy.create_category(
                session, CategoryCreate(name="[샘플] 상품 설명서")
            ).id,
        }
        for key, label, default, description in VARIABLES:
            taxonomy.create_variable(
                session,
                VariableCreate(
                    key=key, label=label, default_value=default, description=description
                ),
            )
        created = {
            data.clause_key: catalog.create_clause(session, data) for data in templates(category)
        }

        def blocks(*keys: str) -> list[BlockIn]:
            return [
                BlockIn(
                    id=uuid.uuid4(), kind="MODULE", clause_id=created[k].id, clause_revision_no=1
                )
                for k in keys
            ]

        terms = documents.create_document(
            session,
            DocumentCreate(
                title="[샘플] 헤리티지 100 이용약관", category_id=category["약관"], tags=["샘플"]
            ),
        )
        terms = documents.save_document(
            session,
            terms.id,
            DocumentSave(
                lock_version=terms.lock_version,
                title=terms.title,
                category_id=category["약관"],
                tags=["샘플"],
                blocks=blocks("demo_purpose", "demo_payment"),
            ),
        )
        documents.change_status(
            session,
            terms.id,
            DocumentStatusChange(
                status=DocumentStatus.ACTIVE,
                lock_version=terms.lock_version,
                reason="검토용 사용 시작",
            ),
        )

        sheet = documents.create_document(
            session,
            DocumentCreate(
                title="[샘플] 헤리티지 100 상품 설명서 (작성 중)", category_id=category["설명서"]
            ),
        )
        documents.save_document(
            session,
            sheet.id,
            DocumentSave(
                lock_version=sheet.lock_version,
                title=sheet.title,
                category_id=category["설명서"],
                variable_values={"monthly_fee": "35,000원"},
                blocks=[
                    *blocks("demo_product_table", "demo_notice"),
                    BlockIn(
                        id=uuid.uuid4(),
                        kind="TEXT",
                        content_json=doc(p(t("[샘플] 문서에서 직접 쓴 단락입니다."))),
                    ),
                ],
            ),
        )
        session.commit()
        counts = f"치환 항목 {len(VARIABLES)}개, 템플릿 {len(created)}개, 문서 2개"
        return f"가상 데이터를 넣었습니다: {counts}"
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="검토용 가상 데이터 넣기 ([샘플])")
    parser.add_argument("--if-empty", action="store_true", help="템플릿·문서가 없을 때만 넣는다")
    print(seed(parser.parse_args().if_empty))


if __name__ == "__main__":
    main()
