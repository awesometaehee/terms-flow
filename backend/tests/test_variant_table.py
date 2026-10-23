from typing import Any

from app.rendering.html import build_variant_table
from tests.helpers import composition


def _variant(name: str, price: int, comp: dict[str, Any]) -> dict[str, Any]:
    return {"display_name": name, "price_amount": price, "composition": comp}


def test_single_variant_has_one_column() -> None:
    table = build_variant_table([_variant("[샘플] A", 3_000_000, composition())])

    assert table.columns == ["[샘플] A (3,000,000원)"]
    assert [(r.kind, r.label, r.cells) for r in table.rows] == [
        ("group", "고인 용품", []),
        ("item", "관", ["[샘플] 규격 / 1개"]),
        ("item", "수의", ["제공"]),
        ("child", "[샘플] 하위 항목", ["제공"]),
    ]
    assert table.footnotes == ["[샘플] 주석"]


def test_multiple_variants_merge_rows_in_order_and_mark_missing() -> None:
    extra = composition()
    extra["groups"].insert(
        0,
        {
            "id": "ceremony",
            "label": "장례 행사",
            "order": 20,
            "items": [
                {"id": "vehicle", "label": "차량", "order": 10, "notes": ["[샘플] 비고"]},
            ],
        },
    )
    extra["footnotes"] = ["[샘플] 다른 주석"]

    table = build_variant_table(
        [_variant("기본", 1_000_000, composition()), _variant("고급", 2_000_000, extra)]
    )

    assert [(r.label, r.cells) for r in table.rows] == [
        ("고인 용품", []),
        ("관", ["[샘플] 규격 / 1개", "[샘플] 규격 / 1개"]),
        ("수의", ["제공", "제공"]),
        ("[샘플] 하위 항목", ["제공", "제공"]),
        ("장례 행사", []),
        ("차량", ["-", "제공\n※ [샘플] 비고"]),
    ]
    assert table.footnotes == ["[기본] [샘플] 주석", "[고급] [샘플] 다른 주석"]
