from app import richtext
from tests.kms_helpers import doc, text, var


def _paths(value: object) -> list[str]:
    return [e.path for e in richtext.validate(value)]


def test_valid_rich_document() -> None:
    body = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2, "textAlign": "center"},
                "content": [text("제목")],
            },
            {
                "type": "paragraph",
                "content": [
                    text("굵게", "bold"),
                    {
                        "type": "text",
                        "text": "색",
                        "marks": [{"type": "textStyle", "attrs": {"color": "#d92d20"}}],
                    },
                    {
                        "type": "text",
                        "text": "형광",
                        "marks": [{"type": "highlight", "attrs": {"color": "#ffff00"}}],
                    },
                    {"type": "hardBreak"},
                    var("service_name"),
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [text("항목")]},
                            {
                                "type": "orderedList",
                                "content": [
                                    {"type": "listItem", "content": [{"type": "paragraph"}]}
                                ],
                            },
                        ],
                    }
                ],
            },
        ],
    }
    assert richtext.validate(body) == []
    assert richtext.variable_keys(body) == ["service_name"]


def test_rejects_unknown_nodes_marks_and_unsafe_values() -> None:
    body = {
        "type": "doc",
        "content": [
            {"type": "image", "attrs": {"src": "x"}},
            {
                "type": "paragraph",
                "attrs": {"textAlign": "middle"},
                "content": [
                    {"type": "text", "text": "a", "marks": [{"type": "code"}]},
                    {
                        "type": "text",
                        "text": "b",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    },
                    {
                        "type": "text",
                        "text": "c",
                        "marks": [
                            {"type": "textStyle", "attrs": {"color": "red;background:url(x)"}}
                        ],
                    },
                    {"type": "variable", "attrs": {"key": "Bad Key"}},
                ],
            },
        ],
    }
    assert _paths(body) == [
        "content_json.content[0].attrs.src",  # 이미지는 이 시스템에 올린 것만
        "content_json.content[1].attrs.textAlign",
        "content_json.content[1].content[0].marks[0]",
        "content_json.content[1].content[1].marks[0].attrs.href",
        "content_json.content[1].content[2].marks[0].attrs.color",
        "content_json.content[1].content[3].attrs.key",
    ]
    assert _paths({"type": "paragraph"}) == ["content_json"]


def test_html_escapes_text_and_fills_variables() -> None:
    body = doc(
        [
            text("<script>x</script> "),
            text("굵게", "bold"),
            text(" "),
            var("service_name"),
            text(" "),
            var("days"),
        ]
    )
    html = richtext.to_html(body, {"service_name": "A&B"}, {"days": "기간"})
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<strong>굵게</strong>" in html
    assert '<span class="var">A&amp;B</span>' in html
    assert '<span class="var var-missing">[기간]</span>' in html


def test_plain_text_and_conversion_from_legacy_text() -> None:
    converted = richtext.from_plain("첫 문단 {{ product.name }}\n줄바꿈\n\n둘째 문단")
    assert converted["content"][0]["content"][1] == var("product.name")
    assert converted["content"][0]["content"][2] == {"type": "hardBreak"}
    assert (
        richtext.to_plain(converted, {"product.name": "상품명"})
        == "첫 문단 [상품명]\n줄바꿈\n\n둘째 문단"
    )


def test_normalize_drops_editor_nulls() -> None:
    from_editor = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": {"textAlign": None},
                "content": [{"type": "text", "text": "a", "marks": []}],
            }
        ],
    }
    assert richtext.normalize(from_editor) == doc([text("a")])
