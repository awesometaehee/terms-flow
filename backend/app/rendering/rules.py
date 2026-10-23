"""조건·변수·레이아웃 규칙. 템플릿·조항 등록 시 검증과 조합 시 평가에 함께 쓴다.

조건 형식: {"channel": ["OFFLINE"], "bundle_type": ["BUNDLE"], "refund_type": ["A", "B"]}
- 모든 키가 맞아야 한다 (AND). 키 안의 값 목록은 그중 하나 (OR). 빈 객체는 항상 참.
변수 형식: 문구 안의 {{ product.name }}. PLACEHOLDER_VARIABLES에 있는 이름만 허용한다.
"""

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from app.config import get_settings
from app.errors import FieldError, format_path, join_path
from app.models import BundleType, SalesChannel

CONDITION_FIELDS: dict[str, str] = {
    "channel": "판매 채널",
    "refund_type": "환급 방식",
    "bundle_type": "상품 유형",
}
_ALLOWED_VALUES: dict[str, set[str] | None] = {
    "channel": {m.value for m in SalesChannel},
    "bundle_type": {m.value for m in BundleType},
    "refund_type": None,  # 승인된 목록이 없어 코드 형식만 검사한다.
}
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

PLACEHOLDER_VARIABLES: dict[str, str] = {
    "product.name": "상품명",
    "product.product_code": "상품 코드",
    "company.name": "법인명",
    "company.code": "법인 코드",
}
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


# --- 조건 ---------------------------------------------------------------------


def validate_condition(condition: Mapping[str, Any], path: str) -> list[FieldError]:
    errors: list[FieldError] = []
    for key, values in condition.items():
        key_path = f"{path}.{key}"
        if key not in CONDITION_FIELDS:
            allowed = ", ".join(CONDITION_FIELDS)
            errors.append(
                FieldError(path=key_path, message=f"조건 항목은 {allowed}만 쓸 수 있습니다.")
            )
            continue
        if not isinstance(values, list) or not values:
            errors.append(FieldError(path=key_path, message="값 목록(1개 이상)이어야 합니다."))
            continue
        allowed_values = _ALLOWED_VALUES[key]
        for i, value in enumerate(values):
            ok = isinstance(value, str) and (
                value in allowed_values if allowed_values is not None else bool(_CODE.match(value))
            )
            if not ok:
                errors.append(
                    FieldError(path=f"{key_path}[{i}]", message="허용되지 않는 값입니다.")
                )
    return errors


def evaluate_condition(
    condition: Mapping[str, Any], product: Mapping[str, Any]
) -> tuple[bool, str]:
    """(일치 여부, 사람이 읽을 사유)를 반환한다. product는 스냅샷의 product 항목이다."""
    if not condition:
        return True, "항상 포함"
    matched: list[str] = []
    for key, values in condition.items():
        label = CONDITION_FIELDS[key]
        actual = product[key]
        if actual not in values:
            return False, f"조건 불일치: {label} {'/'.join(values)} 아님 (현재 {actual})"
        matched.append(f"{label}={actual}")
    return True, "조건 일치: " + ", ".join(matched)


# --- 변수 ---------------------------------------------------------------------


def validate_placeholders(text: str, path: str) -> list[FieldError]:
    errors = []
    for name in PLACEHOLDER.findall(text):
        if name not in PLACEHOLDER_VARIABLES:
            allowed = ", ".join(PLACEHOLDER_VARIABLES)
            errors.append(
                FieldError(
                    path=path, message=f"알 수 없는 변수 {{{{{name}}}}}. 사용 가능: {allowed}"
                )
            )
    return errors


def placeholder_values(snapshot: Mapping[str, Any]) -> dict[str, str]:
    product = snapshot["product"]
    return {
        "product.name": product["name"],
        "product.product_code": product["product_code"],
        "company.name": product["company"]["name"],
        "company.code": product["company"]["code"],
    }


def fill_placeholders(text: str, values: Mapping[str, str]) -> str:
    # 등록 시 검증했으므로 모든 변수는 values에 있다. 결과는 HTML 렌더링 때 이스케이프된다.
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


# --- 레이아웃 -----------------------------------------------------------------


@lru_cache
def _layout_validator(schema_version: int) -> Draft202012Validator:
    path = get_settings().schemas_dir / f"layout.v{schema_version}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_layout(layout: Mapping[str, Any], path: str = "layout_definition") -> list[FieldError]:
    if layout.get("schemaVersion") != 1:
        return [
            FieldError(path=f"{path}.schemaVersion", message="지원하지 않는 schemaVersion입니다.")
        ]
    schema_errors = sorted(
        _layout_validator(1).iter_errors(layout), key=lambda e: list(map(str, e.absolute_path))
    )
    if schema_errors:
        return [
            FieldError(path=join_path(path, format_path(e.absolute_path)), message=e.message)
            for e in schema_errors
        ]
    errors: list[FieldError] = []
    for i, block in enumerate(layout["blocks"]):
        if "text" in block:
            errors += validate_placeholders(block["text"], f"{path}.blocks[{i}].text")
    return errors
