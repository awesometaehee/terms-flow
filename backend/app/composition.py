"""판매 구성(composition_jsonb) 검증.

스키마 파일은 저장소 루트 schemas/에 schemaVersion별로 둔다. JSON Schema로 표현할 수 없는
ID 유일성 규칙은 이 모듈에서 추가로 검사한다.
"""

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from app.config import get_settings
from app.errors import FieldError, format_path

SUPPORTED_SCHEMA_VERSIONS = (1,)


@lru_cache
def _validator(schema_version: int) -> Draft202012Validator:
    path = get_settings().schemas_dir / f"composition.v{schema_version}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _duplicate_id_errors(data: dict[str, Any]) -> list[FieldError]:
    """그룹 ID는 그룹끼리, 항목 ID는 하위 항목을 포함한 구성 전체에서 유일해야 한다."""
    errors: list[FieldError] = []
    group_ids: set[str] = set()
    item_ids: set[str] = set()
    for gi, group in enumerate(data["groups"]):
        if group["id"] in group_ids:
            errors.append(FieldError(path=f"groups[{gi}].id", message="그룹 ID가 중복됩니다."))
        group_ids.add(group["id"])
        for ii, item in enumerate(group["items"]):
            rows = [(f"groups[{gi}].items[{ii}]", item)]
            rows += [
                (f"groups[{gi}].items[{ii}].children[{ci}]", child)
                for ci, child in enumerate(item.get("children", []))
            ]
            for path, row in rows:
                if row["id"] in item_ids:
                    errors.append(FieldError(path=f"{path}.id", message="항목 ID가 중복됩니다."))
                item_ids.add(row["id"])
    return errors


def validate_composition(data: Any) -> list[FieldError]:
    """오류가 없으면 빈 목록을 반환한다. path 예: groups[0].items[2].label"""
    version = data.get("schemaVersion") if isinstance(data, dict) else None
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        message = "지원하지 않는 schemaVersion입니다."
        return [FieldError(path="schemaVersion", message=message)]
    schema_errors = sorted(
        _validator(version).iter_errors(data), key=lambda e: list(map(str, e.absolute_path))
    )
    if schema_errors:
        return [
            FieldError(path=format_path(e.absolute_path), message=e.message) for e in schema_errors
        ]
    return _duplicate_id_errors(data)
