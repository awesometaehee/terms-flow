"""서식 있는 본문(에디터 JSON) 검증·변환.

모듈과 문서 본문은 화면 에디터(TipTap/ProseMirror)의 JSON으로 저장한다. 서버는 허용한 노드·서식만
받아들이고(그 밖은 422), 출력 HTML은 여기서 직접 만든다. 클라이언트가 보낸 HTML은 쓰지 않는다.

허용 노드: doc, paragraph, heading(1~3), text, hardBreak, bulletList, orderedList, listItem,
          variable(인라인 변수 칩, attrs.key),
          table > tableRow(attrs.height: 최소 높이 px) > tableCell·tableHeader
          (attrs: colspan, rowspan, colwidth, background),
          columns > column (단 나누기 2~4단, column.attrs.width: 너비 비율),
          image (attrs.src: 이 시스템에 올린 이미지 /api/assets/... 만, width·height·alt)
허용 서식: bold, italic, underline, strike, textStyle(color), highlight(color), link(href)
문단 정렬: paragraph·heading의 attrs.textAlign (left/center/right/justify)
들어갈 수 있는 곳: 표 칸 안에는 문단·제목·목록·이미지, 단 안에는 그 밖에 표도 넣을 수 있다.
"""

import html
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from app.errors import FieldError

TEXT_BLOCKS = {"paragraph", "heading", "bulletList", "orderedList"}
CELL_BLOCKS = TEXT_BLOCKS | {"image"}
COLUMN_BLOCKS = CELL_BLOCKS | {"table"}
BLOCK_NODES = COLUMN_BLOCKS | {"columns"}
CELL_TYPES = {"tableCell", "tableHeader"}
INLINE_NODES = {"text", "hardBreak", "variable"}
MARKS = {"bold", "italic", "underline", "strike", "textStyle", "highlight", "link"}
ALIGNS = {"left", "center", "right", "justify"}
VARIABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_COLOR = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*(0|1|0?\.\d+)\s*)?\))$"
)
_HREF = re.compile(r"^(https?://|mailto:)[^\s\"'<>]+$", re.IGNORECASE)
# 이 시스템에 올린 이미지만 허용한다 (외부 주소는 PDF 재현성이 없고 추적에 쓰일 수 있다).
ASSET_SRC = re.compile(r"^/api/assets/[0-9a-f]{32}\.(png|jpg|gif|webp)$")
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


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _number_in(value: Any, low: float, high: float) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high


def _validate_block(
    node: Any,
    path: str,
    errors: list[FieldError],
    depth: int,
    allowed: set[str] = BLOCK_NODES,
) -> None:
    if depth > MAX_DEPTH:
        errors.append(FieldError(path=path, message="목록 중첩이 너무 깊습니다."))
        return
    kind = node.get("type") if isinstance(node, dict) else None
    if kind not in allowed:
        where = "표 칸" if allowed is CELL_BLOCKS else "단" if allowed is COLUMN_BLOCKS else "본문"
        errors.append(FieldError(path=path, message=f"{where}에 넣을 수 없는 형식입니다: {kind}"))
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
    if kind == "image":
        _validate_image(attrs, path, errors)
        return
    if kind == "table":
        _validate_table(node, path, errors, depth)
        return
    if kind == "columns":
        columns = node.get("content") or []
        if not 2 <= len(columns) <= 4:
            errors.append(FieldError(path=path, message="단은 2~4개여야 합니다."))
        for i, column in enumerate(columns):
            column_path = f"{path}.content[{i}]"
            if not isinstance(column, dict) or column.get("type") != "column":
                errors.append(FieldError(path=column_path, message="단(column)이어야 합니다."))
                continue
            width = (column.get("attrs") or {}).get("width")
            if width is not None and not _int_in(width, 5, 95):
                errors.append(
                    FieldError(path=f"{column_path}.attrs.width", message="단 너비는 5~95입니다.")
                )
            for j, child in enumerate(column.get("content") or []):
                _validate_block(
                    child, f"{column_path}.content[{j}]", errors, depth + 1, COLUMN_BLOCKS
                )
        return
    # 목록: 목록 안에는 글 문단·목록만
    for i, item in enumerate(node.get("content") or []):
        item_path = f"{path}.content[{i}]"
        if not isinstance(item, dict) or item.get("type") != "listItem":
            errors.append(FieldError(path=item_path, message="목록 항목(listItem)이어야 합니다."))
            continue
        for j, child in enumerate(item.get("content") or []):
            _validate_block(child, f"{item_path}.content[{j}]", errors, depth + 1, TEXT_BLOCKS)


def _fail(errors: list[FieldError], path: str, message: str) -> None:
    errors.append(FieldError(path=path, message=message))


def _validate_image(attrs: Mapping[str, Any], path: str, errors: list[FieldError]) -> None:
    src = attrs.get("src")
    if not (isinstance(src, str) and ASSET_SRC.match(src)):
        errors.append(
            FieldError(
                path=f"{path}.attrs.src", message="이 시스템에 올린 이미지만 넣을 수 있습니다."
            )
        )
    for key in ("width", "height"):
        value = attrs.get(key)
        if value is not None and not _number_in(value, 1, 4000):
            _fail(errors, f"{path}.attrs.{key}", "이미지 크기가 올바르지 않습니다.")
    for key in ("alt", "title"):
        value = attrs.get(key)
        if value is not None and not (isinstance(value, str) and len(value) <= 200):
            _fail(errors, f"{path}.attrs.{key}", "200자 이하로 쓰세요.")


def _validate_table(
    node: Mapping[str, Any], path: str, errors: list[FieldError], depth: int
) -> None:
    rows = node.get("content") or []
    if not rows:
        errors.append(FieldError(path=path, message="표에 행이 없습니다."))
    if len(rows) > 300:
        errors.append(FieldError(path=path, message="표의 행은 300개까지입니다."))
    for r, row in enumerate(rows):
        row_path = f"{path}.content[{r}]"
        if not isinstance(row, dict) or row.get("type") != "tableRow":
            errors.append(FieldError(path=row_path, message="표 행(tableRow)이어야 합니다."))
            continue
        # 행 높이(px, 최소 높이). 끌어서 맞춘 값
        height = (row.get("attrs") or {}).get("height")
        if height is not None and not _int_in(height, 8, 2000):
            _fail(errors, f"{row_path}.attrs.height", "행 높이는 8~2000px입니다.")
        cells = row.get("content") or []
        if not cells or len(cells) > 30:
            errors.append(FieldError(path=row_path, message="표의 칸은 행마다 1~30개입니다."))
        for c, cell in enumerate(cells):
            cell_path = f"{row_path}.content[{c}]"
            if not isinstance(cell, dict) or cell.get("type") not in CELL_TYPES:
                errors.append(FieldError(path=cell_path, message="표 칸(tableCell)이어야 합니다."))
                continue
            attrs = cell.get("attrs") or {}
            colspan = attrs.get("colspan", 1)
            if not _int_in(colspan, 1, 30):
                errors.append(
                    FieldError(
                        path=f"{cell_path}.attrs.colspan", message="가로 합치기는 1~30칸입니다."
                    )
                )
            if not _int_in(attrs.get("rowspan", 1), 1, 300):
                errors.append(
                    FieldError(
                        path=f"{cell_path}.attrs.rowspan", message="세로 합치기는 1~300칸입니다."
                    )
                )
            colwidth = attrs.get("colwidth")
            if colwidth is not None and not (
                isinstance(colwidth, list)
                and len(colwidth) == colspan
                and all(w is None or _int_in(w, 1, 4000) for w in colwidth)
            ):
                errors.append(
                    FieldError(
                        path=f"{cell_path}.attrs.colwidth", message="열 너비가 올바르지 않습니다."
                    )
                )
            background = attrs.get("background")
            if background is not None and not (
                isinstance(background, str) and _COLOR.match(background)
            ):
                errors.append(
                    FieldError(
                        path=f"{cell_path}.attrs.background", message="색상 값이 올바르지 않습니다."
                    )
                )
            for i, child in enumerate(cell.get("content") or []):
                _validate_block(child, f"{cell_path}.content[{i}]", errors, depth + 1, CELL_BLOCKS)


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
                FieldError(path=f"{path}.attrs.key", message="치환 항목 키가 올바르지 않습니다.")
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


# 값이 1이면 기본값이라 저장하지 않는 속성 (표 칸 합치기)
_DEFAULT_ONE = {"colspan", "rowspan"}


def normalize(node: Any) -> Any:
    """에디터가 붙이는 빈 값(null 속성, 빈 attrs·marks)과 기본값(표 칸 colspan·rowspan 1)을 없앤다.

    저장·비교 전에 쓴다. 프런트 lib/richdoc.ts normalizeDoc과 같은 규칙이어야 한다.
    """
    if isinstance(node, list):
        return [normalize(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "attrs" and isinstance(value, dict):
            attrs = {
                k: v
                for k, v in value.items()
                if v is not None and not (k in _DEFAULT_ONE and v == 1)
            }
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

    def cell_text(cell: Mapping[str, Any]) -> str:
        parts: list[str] = []
        for child in cell.get("content") or []:
            if child.get("type") in ("paragraph", "heading"):
                parts.append(inline(child))
        return " ".join(p for p in parts if p)

    def block(node: Mapping[str, Any], prefix: str = "") -> None:
        kind = node.get("type")
        if kind in ("paragraph", "heading"):
            blocks.append(prefix + inline(node))
        elif kind == "table":
            rows = [
                " | ".join(cell_text(cell) for cell in row.get("content") or [])
                for row in node.get("content") or []
            ]
            blocks.append("\n".join(r for r in rows if r.strip(" |")))
        elif kind == "columns":
            for column in node.get("content") or []:
                for child in column.get("content") or []:
                    block(child, prefix)
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
    image_src: Callable[[str], str] | None = None,
) -> str:
    """검증된 본문을 HTML로 만든다. 값이 없는 변수는 [이름]으로 표시하고 강조한다.

    image_src: 이미지 주소 변환 (PDF는 파일을 data URI로 넣는다). 없으면 그대로 쓴다.
    """
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
        if kind == "image":
            src = attrs["src"]
            src = image_src(src) if image_src else src
            width = attrs.get("width")
            alt = html.escape(attrs.get("alt") or "")
            size = _style(width=f"{width:g}px" if width else None)
            return f'<img class="rt-image" src="{html.escape(src)}" alt="{alt}"{size}>'
        if kind == "table":
            return table(node)
        if kind == "columns":
            columns = node.get("content") or []
            widths = [(c.get("attrs") or {}).get("width") or 0 for c in columns]
            template = (
                " ".join(f"{w}fr" for w in widths)
                if all(widths)
                else f"repeat({len(columns)}, 1fr)"
            )
            inner = "".join(
                '<div class="rt-column">'
                + "".join(block(c) for c in col.get("content") or [])
                + "</div>"
                for col in columns
            )
            return f'<div class="rt-columns"{_style(grid_template_columns=template)}>{inner}</div>'
        return ""

    def table(node: Mapping[str, Any]) -> str:
        rows = node.get("content") or []
        # 열 너비: 첫 행 칸들의 colwidth를 이어 붙인다 (에디터에서 끌어 바꾼 너비).
        widths: list[int | None] = []
        for cell in rows[0].get("content") or [] if rows else []:
            cattrs = cell.get("attrs") or {}
            widths += cattrs.get("colwidth") or [None] * int(cattrs.get("colspan", 1))
        # 저장된 px 너비는 비율로 쓴다. 너비가 없는 열은 있는 열들의 평균.
        # (에디터 FitTableView와 같은 규칙)
        # 화면·용지 너비가 달라도 표가 넘치거나 일부 열이 찌그러지지 않는다.
        colgroup = ""
        if any(widths):
            known = [w for w in widths if w]
            average = sum(known) / len(known)
            filled = [w or average for w in widths]
            total = sum(filled)
            colgroup = (
                "<colgroup>"
                + "".join(f"<col{_style(width=f'{w / total * 100:.2f}%')}>" for w in filled)
                + "</colgroup>"
            )
        body = ""
        for row in rows:
            cells = ""
            for cell in row.get("content") or []:
                cattrs = cell.get("attrs") or {}
                tag = "th" if cell.get("type") == "tableHeader" else "td"
                span = "".join(
                    f' {name}="{int(cattrs[name])}"'
                    for name in ("colspan", "rowspan")
                    if int(cattrs.get(name, 1)) > 1
                )
                inner = "".join(block(c) for c in cell.get("content") or [])
                fill = _style(background_color=cattrs.get("background"))
                cells += f"<{tag}{span}{fill}>{inner}</{tag}>"
            height = (row.get("attrs") or {}).get("height")
            body += f"<tr{_style(height=f'{int(height)}px' if height else None)}>{cells}</tr>"
        return f'<table class="rt-table">{colgroup}<tbody>{body}</tbody></table>'

    return "".join(block(c) for c in doc.get("content") or [])
