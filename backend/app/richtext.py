"""서식 있는 본문(에디터 JSON) 검증·변환.

모듈과 문서 본문은 화면 에디터(TipTap/ProseMirror)의 JSON으로 저장한다. 서버는 허용한 노드·서식만
받아들이고(그 밖은 422), 출력 HTML은 여기서 직접 만든다. 클라이언트가 보낸 HTML은 쓰지 않는다.

허용 노드: doc, paragraph, heading(1~3), text, hardBreak, bulletList, orderedList, listItem,
          variable(인라인 변수 칩, attrs.key)
허용 서식: bold, italic, underline, strike, textStyle(color), highlight(color), link(href)
문단 정렬: paragraph·heading의 attrs.textAlign (left/center/right/justify)
"""

import html
import re
from collections.abc import Iterator, Mapping
from typing import Any

from app.errors import FieldError

BLOCK_NODES = {"paragraph", "heading", "bulletList", "orderedList"}
INLINE_NODES = {"text", "hardBreak", "variable"}
MARKS = {"bold", "italic", "underline", "strike", "textStyle", "highlight", "link"}
ALIGNS = {"left", "center", "right", "justify"}
VARIABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_COLOR = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*(0|1|0?\.\d+)\s*)?\))$"
)
_HREF = re.compile(r"^(https?://|mailto:)[^\s\"'<>]+$", re.IGNORECASE)
MAX_DEPTH = 8
Doc = dict[str, Any]


def empty_doc() -> Doc:
    return {"type": "doc", "content": [{"type": "paragraph"}]}


# --- 검증 -----------------------------------------------------------------------


def validate(doc: Any, path: str = "content_json") -> list[FieldError]:
    errors: list[FieldError] = []
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        return [FieldError(path=path, message="본문 형식이 올바르지 않습니다 (type=doc).")]
    content = doc.get("content", [])
    if not isinstance(content, list):
        return [FieldError(path=f"{path}.content", message="목록이어야 합니다.")]
    for i, node in enumerate(content):
        _validate_block(node, f"{path}.content[{i}]", errors, depth=1)
    return errors


def _validate_block(node: Any, path: str, errors: list[FieldError], depth: int) -> None:
    if depth > MAX_DEPTH:
        errors.append(FieldError(path=path, message="목록 중첩이 너무 깊습니다."))
        return
    kind = node.get("type") if isinstance(node, dict) else None
    if kind not in BLOCK_NODES:
        errors.append(FieldError(path=path, message=f"허용되지 않는 문단 형식입니다: {kind}"))
        return
    attrs = node.get("attrs") or {}
    if kind in ("paragraph", "heading"):
        align = attrs.get("textAlign")
        if align is not None and align not in ALIGNS:
            errors.append(
                FieldError(path=f"{path}.attrs.textAlign", message="허용되지 않는 정렬입니다.")
            )
        if kind == "heading" and attrs.get("level") not in (1, 2, 3):
            errors.append(FieldError(path=f"{path}.attrs.level", message="제목 수준은 1~3입니다."))
        for i, child in enumerate(node.get("content") or []):
            _validate_inline(child, f"{path}.content[{i}]", errors)
        return
    # 목록
    for i, item in enumerate(node.get("content") or []):
        item_path = f"{path}.content[{i}]"
        if not isinstance(item, dict) or item.get("type") != "listItem":
            errors.append(FieldError(path=item_path, message="목록 항목(listItem)이어야 합니다."))
            continue
        for j, child in enumerate(item.get("content") or []):
            _validate_block(child, f"{item_path}.content[{j}]", errors, depth + 1)


def _validate_inline(node: Any, path: str, errors: list[FieldError]) -> None:
    kind = node.get("type") if isinstance(node, dict) else None
    if kind not in INLINE_NODES:
        errors.append(FieldError(path=path, message=f"허용되지 않는 글 요소입니다: {kind}"))
        return
    if kind == "text" and not isinstance(node.get("text"), str):
        errors.append(FieldError(path=f"{path}.text", message="글자가 없습니다."))
    if kind == "variable":
        key = (node.get("attrs") or {}).get("key")
        if not isinstance(key, str) or not VARIABLE_KEY.match(key):
            errors.append(
                FieldError(path=f"{path}.attrs.key", message="변수 키가 올바르지 않습니다.")
            )
    for i, mark in enumerate(node.get("marks") or []):
        mark_path = f"{path}.marks[{i}]"
        mtype = mark.get("type") if isinstance(mark, dict) else None
        if mtype not in MARKS:
            errors.append(FieldError(path=mark_path, message=f"허용되지 않는 서식입니다: {mtype}"))
            continue
        attrs = mark.get("attrs") or {}
        if mtype in ("textStyle", "highlight"):
            color = attrs.get("color")
            if color is not None and not (isinstance(color, str) and _COLOR.match(color)):
                errors.append(
                    FieldError(
                        path=f"{mark_path}.attrs.color", message="색상 값이 올바르지 않습니다."
                    )
                )
        if mtype == "link":
            href = attrs.get("href")
            if not (isinstance(href, str) and _HREF.match(href)):
                errors.append(
                    FieldError(
                        path=f"{mark_path}.attrs.href",
                        message="링크는 http(s) 또는 mailto만 허용합니다.",
                    )
                )


# --- 정규화 ---------------------------------------------------------------------


def normalize(node: Any) -> Any:
    """에디터가 붙이는 빈 값(null 속성, 빈 attrs·marks)을 없앤다. 저장·비교 전에 쓴다."""
    if isinstance(node, list):
        return [normalize(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "attrs" and isinstance(value, dict):
            attrs = {k: v for k, v in value.items() if v is not None}
            if attrs:
                out[key] = attrs
        elif key in ("marks", "content") and isinstance(value, list):
            if value:
                out[key] = normalize(value)
        elif value is not None:
            out[key] = normalize(value)
    return out


# --- 탐색 -----------------------------------------------------------------------


def _walk(node: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield node
    for child in node.get("content") or []:
        yield from _walk(child)


def variable_keys(doc: Mapping[str, Any]) -> list[str]:
    """본문에 쓰인 변수 키 (처음 나온 순서, 중복 없음)."""
    seen: dict[str, None] = {}
    for node in _walk(doc):
        if node.get("type") == "variable":
            seen.setdefault(node["attrs"]["key"], None)
    return list(seen)


def to_plain(doc: Mapping[str, Any], labels: Mapping[str, str] | None = None) -> str:
    """검색·요약용 일반 텍스트. 문단은 빈 줄로 나누고, 변수는 [이름]으로 쓴다."""
    labels = labels or {}
    blocks: list[str] = []

    def inline(node: Mapping[str, Any]) -> str:
        out = ""
        for child in node.get("content") or []:
            kind = child.get("type")
            if kind == "text":
                out += child.get("text", "")
            elif kind == "hardBreak":
                out += "\n"
            elif kind == "variable":
                key = child["attrs"]["key"]
                out += f"[{labels.get(key, key)}]"
        return out

    def block(node: Mapping[str, Any], prefix: str = "") -> None:
        kind = node.get("type")
        if kind in ("paragraph", "heading"):
            blocks.append(prefix + inline(node))
        elif kind in ("bulletList", "orderedList"):
            for n, item in enumerate(node.get("content") or [], start=1):
                marker = "- " if kind == "bulletList" else f"{n}. "
                for child in item.get("content") or []:
                    block(child, prefix + marker)
                    marker = "  "

    for child in doc.get("content") or []:
        block(child)
    return "\n\n".join(b for b in blocks if b.strip())


def from_plain(text: str) -> Doc:
    """일반 텍스트를 본문 JSON으로 바꾼다. {{ key }}는 변수 칩이 된다 (기존 조항 변환용)."""
    paragraphs = [p for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    content: list[Doc] = []
    for para in paragraphs:
        inline: list[Doc] = []
        for li, line in enumerate(para.strip().split("\n")):
            if li:
                inline.append({"type": "hardBreak"})
            pos = 0
            for m in re.finditer(r"\{\{\s*([a-z][a-z0-9_.]*)\s*\}\}", line):
                if m.start() > pos:
                    inline.append({"type": "text", "text": line[pos : m.start()]})
                inline.append({"type": "variable", "attrs": {"key": m.group(1)}})
                pos = m.end()
            if pos < len(line):
                inline.append({"type": "text", "text": line[pos:]})
        content.append(
            {"type": "paragraph", "content": inline} if inline else {"type": "paragraph"}
        )
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


# --- HTML -----------------------------------------------------------------------


def _style(**props: str | None) -> str:
    parts = [f"{k.replace('_', '-')}:{v}" for k, v in props.items() if v]
    return f' style="{html.escape(";".join(parts))}"' if parts else ""


def to_html(
    doc: Mapping[str, Any],
    values: Mapping[str, str],
    labels: Mapping[str, str] | None = None,
) -> str:
    """검증된 본문을 HTML로 만든다. 값이 없는 변수는 [이름]으로 표시하고 강조한다."""
    labels = labels or {}

    def text(node: Mapping[str, Any]) -> str:
        kind = node.get("type")
        if kind == "hardBreak":
            return "<br>"
        if kind == "variable":
            key = node["attrs"]["key"]
            if key in values and values[key] != "":
                return f'<span class="var">{html.escape(values[key])}</span>'
            return f'<span class="var var-missing">[{html.escape(labels.get(key, key))}]</span>'
        out = html.escape(node.get("text", ""))
        for mark in node.get("marks") or []:
            mtype, attrs = mark["type"], mark.get("attrs") or {}
            if mtype == "bold":
                out = f"<strong>{out}</strong>"
            elif mtype == "italic":
                out = f"<em>{out}</em>"
            elif mtype == "underline":
                out = f"<u>{out}</u>"
            elif mtype == "strike":
                out = f"<s>{out}</s>"
            elif mtype == "textStyle" and attrs.get("color"):
                out = f"<span{_style(color=attrs['color'])}>{out}</span>"
            elif mtype == "highlight":
                out = (
                    f"<mark{_style(background_color=attrs.get('color') or '#fff59d')}>{out}</mark>"
                )
            elif mtype == "link":
                out = f'<a href="{html.escape(attrs["href"])}">{out}</a>'
        return out

    def inline(node: Mapping[str, Any]) -> str:
        return "".join(text(c) for c in node.get("content") or [])

    def block(node: Mapping[str, Any]) -> str:
        kind = node.get("type")
        attrs = node.get("attrs") or {}
        style = _style(text_align=attrs.get("textAlign"))
        if kind == "paragraph":
            return f"<p{style}>{inline(node) or '&nbsp;'}</p>"
        if kind == "heading":
            level = int(attrs.get("level", 2)) + 1  # 문서 제목(h1) 아래 단계
            return f"<h{level}{style}>{inline(node)}</h{level}>"
        if kind in ("bulletList", "orderedList"):
            tag = "ul" if kind == "bulletList" else "ol"
            items = "".join(
                "<li>" + "".join(block(c) for c in item.get("content") or []) + "</li>"
                for item in node.get("content") or []
            )
            return f"<{tag}>{items}</{tag}>"
        return ""

    return "".join(block(c) for c in doc.get("content") or [])
