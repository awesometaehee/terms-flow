"""KMS 문서 리비전 스냅샷 → HTML. 미리보기와 PDF 발행이 같은 HTML을 쓴다.

스냅샷에는 단락 본문·변수 이름·기본값이 모두 들어 있어 DB의 현재 모듈을 다시 읽지 않는다.
"""

import re
from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from app import assets, richtext
from app.rendering.html import template_env


def variable_values(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """기본값 위에 문서 입력값을 덮어쓴 변수 값."""
    values = {
        key: spec["default"]
        for key, spec in snapshot.get("variables", {}).items()
        if spec.get("default")
    }
    values.update({k: v for k, v in snapshot.get("variable_values", {}).items() if v})
    return values


def missing_variables(snapshot: Mapping[str, Any]) -> list[str]:
    values = variable_values(snapshot)
    return [key for key in snapshot.get("variables", {}) if key not in values]


def render_html(snapshot: Mapping[str, Any], *, preview: bool = False) -> str:
    """preview: 브라우저 미리보기 (이미지는 /api/assets 주소로 불러온다).

    발행(PDF)은 이미지를 data URI로 HTML에 넣는다.
    """
    values = variable_values(snapshot)
    labels = {key: spec["label"] for key, spec in snapshot.get("variables", {}).items()}
    image_src = None if preview else assets.data_uri
    blocks = [
        {
            "id": b["id"],
            "html": Markup(richtext.to_html(b["content_json"], values, labels, image_src)),
        }
        for b in snapshot["blocks"]
    ]
    return (
        template_env()
        .get_template("kms_document.html.j2")
        .render(title=snapshot["title"], blocks=blocks, preview=preview)
    )


def file_stem(title: str, version_no: int) -> str:
    """파일명: 제목에서 파일명에 못 쓰는 문자를 _로 바꾸고 버전을 붙인다."""
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_.")[:80] or "document"
    return f"{safe}_v{version_no}"
