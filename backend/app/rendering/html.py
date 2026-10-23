"""문서 계획 → HTML. 미리보기와 PDF 렌더링이 같은 HTML을 사용한다.

레이아웃 블록과 조항 문구의 변수는 여기서 채우고, 모든 문구는 Jinja2 자동 이스케이프를 거친다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app import richtext
from app.rendering.composer import DOCUMENT_LABELS, DocumentPlan, SetPlan
from app.rendering.rules import fill_placeholders, placeholder_values

_TEMPLATE_DIR = Path(__file__).parent / "templates"


@lru_cache
def template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _paragraphs(text: str) -> list[list[str]]:
    """빈 줄로 문단을 나누고, 문단 안의 줄바꿈은 유지한다."""
    blocks = [b.strip() for b in text.replace("\r\n", "\n").split("\n\n")]
    return [b.split("\n") for b in blocks if b]


def format_won(amount: int) -> str:
    return f"{amount:,}원"


# --- 판매 구성 품목 표 ----------------------------------------------------------


@dataclass
class TableRow:
    kind: str  # "group" | "item" | "child"
    label: str
    cells: list[str] = field(default_factory=list)


@dataclass
class VariantTable:
    columns: list[str]
    rows: list[TableRow]
    footnotes: list[str]


def _cell_text(item: Mapping[str, Any]) -> str:
    parts = []
    if item.get("specification"):
        parts.append(str(item["specification"]))
    quantity = item.get("quantity")
    if quantity:
        value = quantity["value"]
        value_text = str(int(value)) if float(value).is_integer() else str(value)
        parts.append(f"{value_text}{quantity['unit']}")
    text = " / ".join(parts) or "제공"
    for note in item.get("notes") or []:
        text += f"\n※ {note}"
    return text


def build_variant_table(variants: Sequence[Mapping[str, Any]]) -> VariantTable:
    """구성별 품목을 하나의 비교 표로 합친다. 없는 품목은 '-'로 표시한다.

    행 순서: 그룹 order → 항목 order → 하위 항목 order (처음 나온 구성의 값 기준).
    """
    sort_keys: dict[tuple[str, ...], tuple[int, ...]] = {}
    labels: dict[tuple[str, ...], str] = {}
    cells: dict[tuple[str, ...], dict[int, str]] = {}
    seen = 0
    for vi, variant in enumerate(variants):
        for group in variant["composition"]["groups"]:
            gkey = (group["id"],)
            if gkey not in sort_keys:
                sort_keys[gkey] = (group["order"], seen)
                labels[gkey] = group["label"]
                seen += 1
            for item in group["items"]:
                ikey = (group["id"], item["id"])
                if ikey not in sort_keys:
                    sort_keys[ikey] = (*sort_keys[gkey], item["order"], seen)
                    labels[ikey] = item["label"]
                    seen += 1
                cells.setdefault(ikey, {})[vi] = _cell_text(item)
                for child in item.get("children") or []:
                    ckey = (group["id"], item["id"], child["id"])
                    if ckey not in sort_keys:
                        sort_keys[ckey] = (*sort_keys[ikey], child["order"], seen)
                        labels[ckey] = child["label"]
                        seen += 1
                    cells.setdefault(ckey, {})[vi] = _cell_text(child)

    rows = []
    for key in sorted(sort_keys, key=lambda k: sort_keys[k]):
        kind = ("group", "item", "child")[len(key) - 1]
        row_cells = (
            [] if kind == "group" else [cells[key].get(i, "-") for i in range(len(variants))]
        )
        rows.append(TableRow(kind=kind, label=labels[key], cells=row_cells))

    footnote_sets = [list(v["composition"].get("footnotes") or []) for v in variants]
    if all(f == footnote_sets[0] for f in footnote_sets):
        footnotes = footnote_sets[0]
    else:
        footnotes = [
            f"[{v['display_name']}] {note}"
            for v, notes in zip(variants, footnote_sets, strict=True)
            for note in notes
        ]
    columns = [f"{v['display_name']} ({format_won(v['price_amount'])})" for v in variants]
    return VariantTable(columns=columns, rows=rows, footnotes=footnotes)


# --- 블록 ----------------------------------------------------------------------


def _blocks(plan: SetPlan, doc: DocumentPlan) -> list[dict[str, Any]]:
    values = placeholder_values(plan.snapshot)
    variants = plan.snapshot["variants"]
    out: list[dict[str, Any]] = []
    for block in doc.template.layout["blocks"]:
        kind = block["type"]
        if kind == "heading":
            out.append(
                {
                    "kind": "heading",
                    "level": block.get("level", 1),
                    "text": fill_placeholders(block["text"], values),
                }
            )
        elif kind == "paragraph":
            text = fill_placeholders(block["text"], values)
            out.append({"kind": "paragraph", "paragraphs": _paragraphs(text)})
        elif kind == "clauses":
            numbered = block.get("numbering", "article") == "article"
            items = [
                {
                    "number": f"제{i}조" if numbered else None,
                    "title": clause.title,
                    # 서식 본문을 허용 목록 기반으로 HTML로 바꾼다 (값은 이스케이프됨).
                    "html": Markup(
                        richtext.to_html(clause.rich or richtext.from_plain(clause.content), values)
                    ),
                }
                for i, clause in enumerate(doc.included, start=1)
            ]
            out.append({"kind": "clauses", "clauses": items})
        elif kind == "variant_table":
            out.append({"kind": "variant_table", "table": build_variant_table(variants)})
        elif kind == "variant_prices":
            rows = [(v["display_name"], format_won(v["price_amount"])) for v in variants]
            out.append({"kind": "variant_prices", "rows": rows})
        elif kind == "page_break":
            out.append({"kind": "page_break"})
    return out


def _document_context(plan: SetPlan, doc: DocumentPlan) -> dict[str, Any]:
    return {
        "type": doc.document_type.value,
        "label": DOCUMENT_LABELS[doc.document_type],
        "blocks": _blocks(plan, doc),
    }


def render_html(plan: SetPlan, docs: Sequence[DocumentPlan], *, preview: bool = False) -> str:
    """docs를 한 HTML로 만든다. 문서가 여러 개면 문서마다 새 페이지에서 시작한다."""
    product = plan.snapshot["product"]
    title = " · ".join(DOCUMENT_LABELS[d.document_type] for d in docs)
    return (
        template_env()
        .get_template("document.html.j2")
        .render(
            title=f"{product['name']} {title}",
            preview=preview,
            documents=[_document_context(plan, d) for d in docs],
        )
    )


def render_document_html(plan: SetPlan, doc: DocumentPlan, *, preview: bool = False) -> str:
    return render_html(plan, [doc], preview=preview)


def render_combined_html(plan: SetPlan, *, preview: bool = False) -> str:
    return render_html(plan, plan.documents, preview=preview)
