"""문서 조합. DB와 렌더러에 의존하지 않는 순수 로직이다.

조항 포함 여부는 규칙마다 명시적으로 결정하고 사유를 남긴다.
- 조건 불일치 → 제외 (사유: 조건 불일치 …)
- 조건 일치 + 사용자가 제외 요청 + 선택 조항(required=False) → 제외 (사유: 사용자 제외)
- 그 밖에는 포함. 순서는 템플릿 규칙의 sort_order, 같으면 clause_key 순.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.errors import FieldError
from app.models import DocumentType
from app.rendering.rules import evaluate_condition

DOCUMENT_ORDER = (
    DocumentType.TERMS,
    DocumentType.TERMS_SUMMARY,
    DocumentType.PRODUCT_DESCRIPTION,
)
USER_EXCLUDED_REASON = "사용자 제외"
DOCUMENT_LABELS = {
    DocumentType.TERMS: "약관",
    DocumentType.TERMS_SUMMARY: "약관 주요 내용",
    DocumentType.PRODUCT_DESCRIPTION: "상품설명서",
}


@dataclass(frozen=True)
class ClauseInput:
    clause_key: str
    title: str
    clause_revision_id: uuid.UUID
    revision_no: int
    content: str
    # 서식 본문. None이면 content(일반 텍스트)를 문단으로 바꿔 쓴다.
    rich: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class RuleInput:
    clause: ClauseInput
    condition: Mapping[str, Any]
    sort_order: int
    required: bool


@dataclass(frozen=True)
class TemplateInput:
    document_type: DocumentType
    template_key: str
    template_revision_id: uuid.UUID
    revision_no: int
    layout: Mapping[str, Any]
    rules: tuple[RuleInput, ...] = ()


@dataclass(frozen=True)
class ClauseDecision:
    clause_key: str
    title: str
    required: bool
    included: bool
    reason: str
    clause: ClauseInput


@dataclass(frozen=True)
class DocumentPlan:
    template: TemplateInput
    decisions: tuple[ClauseDecision, ...]

    @property
    def document_type(self) -> DocumentType:
        return self.template.document_type

    @property
    def included(self) -> list[ClauseInput]:
        return [d.clause for d in self.decisions if d.included]


@dataclass(frozen=True)
class SetPlan:
    snapshot: Mapping[str, Any]
    documents: tuple[DocumentPlan, ...]


class CompositionFailed(Exception):
    def __init__(self, errors: Sequence[FieldError]):
        super().__init__("; ".join(f"{e.path}: {e.message}" for e in errors))
        self.errors = list(errors)


def compose_document(
    template: TemplateInput, snapshot: Mapping[str, Any], excluded_keys: set[str]
) -> DocumentPlan:
    decisions = []
    for rule in sorted(template.rules, key=lambda r: (r.sort_order, r.clause.clause_key)):
        matched, reason = evaluate_condition(rule.condition, snapshot["product"])
        included = matched
        if matched and rule.clause.clause_key in excluded_keys and not rule.required:
            included, reason = False, USER_EXCLUDED_REASON
        decisions.append(
            ClauseDecision(
                clause_key=rule.clause.clause_key,
                title=rule.clause.title,
                required=rule.required,
                included=included,
                reason=reason,
                clause=rule.clause,
            )
        )
    return DocumentPlan(template=template, decisions=tuple(decisions))


def compose_set(
    templates: Mapping[DocumentType, TemplateInput],
    snapshot: Mapping[str, Any],
    excluded_keys: Sequence[str] = (),
) -> SetPlan:
    """3종 문서를 약관 → 약관 주요 내용 → 상품설명서 순서로 조합한다."""
    rules = {r.clause.clause_key: r for t in templates.values() for r in t.rules}
    errors = []
    for i, key in enumerate(excluded_keys):
        rule = rules.get(key)
        if rule is None:
            errors.append(
                FieldError(path=f"excluded_clause_keys[{i}]", message="템플릿에 없는 조항입니다.")
            )
        elif rule.required:
            errors.append(
                FieldError(
                    path=f"excluded_clause_keys[{i}]", message="필수 조항은 제외할 수 없습니다."
                )
            )
    if errors:
        raise CompositionFailed(errors)
    excluded = set(excluded_keys)
    return SetPlan(
        snapshot=snapshot,
        documents=tuple(compose_document(templates[t], snapshot, excluded) for t in DOCUMENT_ORDER),
    )
