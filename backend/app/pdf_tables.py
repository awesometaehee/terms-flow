"""PDF에서 표를 찾아 본문 표(table JSON)로 바꾼다.

상품 설명서처럼 칸마다 선이 그어진 표를 대상으로 한다.

1. 표 영역: pdfplumber가 선으로 찾은 표. 위아래로 바로 붙은(너비가 같은) 표는 하나로 합친다.
2. 격자: 영역 안 선분(선·사각형 테두리)의 x·y 위치. 3~4pt 안으로 붙은 선은 같은 선으로 본다.
   이웃한 격자 칸 사이에 선이 없으면 한 칸으로 합친다 (= colspan·rowspan).
3. 글자: PDFium의 글자 위치·색·굵기 (pdfminer는 일부 글꼴에서 위아래로 어긋난다).
   글자 가운데가 들어 있는 칸에 읽기 순서대로 넣는다.
4. 칸 배경색: 렌더링한 페이지에서 칸 안쪽 픽셀 중 가장 많은 색 (화면에 보이는 색 그대로).
5. 칸 안 이미지: 가운데가 들어 있는 칸에 이미지로 넣는다 (assets에 저장).
"""

import collections
import ctypes
import io
from dataclasses import dataclass
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from app import assets, richtext
from app.errors import FieldError, ValidationFailed

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 10
MAX_IMAGES = 80
SNAP = 4.0  # pt: 이보다 가까운 선은 같은 선
LINE_TOL = 1.6  # pt: 선분이 경계 위에 있다고 보는 거리
RENDER_SCALE = 2
PT_TO_PX = 96 / 72


@dataclass
class _Char:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    color: str | None  # 거의 검정이면 None
    bold: bool

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class _Region:
    r0: int
    r1: int
    c0: int
    c1: int


def _invalid(message: str) -> ValidationFailed:
    return ValidationFailed([FieldError(path="file", message=message)])


def _snap(values: list[float]) -> list[float]:
    """가까운 값끼리 묶고, 묶음마다 가장 많이 나온 위치를 대표로 쓴다."""
    groups: list[list[float]] = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= SNAP:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [max(set(g), key=lambda x: sum(abs(x - y) <= LINE_TOL for y in g)) for g in groups]


def _covered(
    segments: list[tuple[float, float, float]], fixed: float, lo: float, hi: float
) -> bool:
    """fixed 위치의 선분(위치, 시작, 끝)이 [lo, hi]를 70% 이상 덮는지."""
    spans = sorted((a, b) for pos, a, b in segments if abs(pos - fixed) <= LINE_TOL)
    length, cur = 0.0, lo
    for a, b in spans:
        a, b = max(a, cur), min(b, hi)
        if b > a:
            length += b - a
            cur = b
    return length >= 0.7 * (hi - lo)


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """위아래로 바로 붙은(좌우 끝이 같은) 표는 한 표로 합치고, 다른 표 안에 든 표는 버린다."""
    out: list[list[float]] = []
    for x0, top, x1, bottom in sorted(bboxes, key=lambda b: (b[1], b[0])):
        for b in out:
            if abs(b[0] - x0) <= 3 and abs(b[2] - x1) <= 3 and -2 <= top - b[3] <= 12:
                b[3] = max(b[3], bottom)
                break
            if b[0] - 1 <= x0 and b[1] - 1 <= top and x1 <= b[2] + 1 and bottom <= b[3] + 1:
                break
        else:
            out.append([x0, top, x1, bottom])
    return [(b[0], b[1], b[2], b[3]) for b in out]


_BOLD_NAMES = ("bold", "heavy", "black")


def _bold_font(textpage: pdfium.PdfTextPage, index: int) -> bool:
    """굵기 값이 없는 글꼴(예: Chromium이 넣은 글꼴)은 글꼴 이름으로 본다 (…-Bold 등)."""
    flags = ctypes.c_int()
    size = pdfium_raw.FPDFText_GetFontInfo(textpage.raw, index, None, 0, flags)
    if size <= 0:
        return False
    buffer = ctypes.create_string_buffer(size)
    pdfium_raw.FPDFText_GetFontInfo(textpage.raw, index, buffer, size, flags)
    name = buffer.value.decode("utf-8", "ignore").lower()
    return any(word in name for word in _BOLD_NAMES)


def _page_chars(page: pdfium.PdfPage) -> list[_Char]:
    height = page.get_height()
    textpage = page.get_textpage()
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    chars: list[_Char] = []
    for i in range(textpage.count_chars()):
        text = textpage.get_text_range(i, 1)
        left, bottom, right, top = textpage.get_charbox(i)
        pdfium_raw.FPDFText_GetFillColor(textpage.raw, i, r, g, b, a)
        rgb = (r.value, g.value, b.value)
        color = None if max(rgb) < 90 else "#{:02x}{:02x}{:02x}".format(*rgb)
        bold = pdfium_raw.FPDFText_GetFontWeight(textpage.raw, i) >= 600 or _bold_font(textpage, i)
        chars.append(_Char(text, left, right, height - top, height - bottom, color, bold))
    return chars


def _grid(
    page: Any, bbox: tuple[float, float, float, float]
) -> tuple[list[float], list[float], list[_Region]]:
    # 표가 쪽 밖으로 걸쳐 있을 수 있어 쪽 안으로 자른다.
    px0, ptop, px1, pbottom = page.bbox
    crop = (
        max(px0, bbox[0] - 1),
        max(ptop, bbox[1] - 1),
        min(px1, bbox[2] + 1),
        min(pbottom, bbox[3] + 1),
    )
    edges = page.crop(crop).edges
    h = [
        (e["top"], e["x0"], e["x1"])
        for e in edges
        if e["orientation"] == "h" and e["x1"] - e["x0"] > 2
    ]
    v = [
        (e["x0"], e["top"], e["bottom"])
        for e in edges
        if e["orientation"] == "v" and e["bottom"] - e["top"] > 2
    ]
    ys = _snap([s[0] for s in h])
    xs = _snap([s[0] for s in v])
    rows, cols = len(ys) - 1, len(xs) - 1
    if rows < 1 or cols < 1:
        return xs, ys, []
    parent = list(range(rows * cols))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols and not _covered(v, xs[c + 1], ys[r], ys[r + 1]):
                parent[find(r * cols + c + 1)] = find(r * cols + c)
            if r + 1 < rows and not _covered(h, ys[r + 1], xs[c], xs[c + 1]):
                parent[find((r + 1) * cols + c)] = find(r * cols + c)
    groups: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    for i in range(rows * cols):
        groups[find(i)].append(divmod(i, cols))
    regions: list[_Region] = []
    for squares in groups.values():
        rs = [s[0] for s in squares]
        cs = [s[1] for s in squares]
        region = _Region(min(rs), max(rs) + 1, min(cs), max(cs) + 1)
        if len(squares) == (region.r1 - region.r0) * (region.c1 - region.c0):
            regions.append(region)
        else:  # 네모가 아닌 모양은 합치지 않는다
            regions += [_Region(r, r + 1, c, c + 1) for r, c in squares]
    return xs, ys, regions


def _background(image: Any, box: tuple[float, float, float, float]) -> str | None:
    x0, top, x1, bottom = (v * RENDER_SCALE for v in box)
    crop = image.crop(
        (
            int(x0) + 3,
            int(top) + 3,
            max(int(x0) + 4, int(x1) - 3),
            max(int(top) + 4, int(bottom) - 3),
        )
    )
    small = crop.resize((max(1, crop.width // 3), max(1, crop.height // 3)))
    rgb = collections.Counter(small.getdata()).most_common(1)[0][0]
    return None if min(rgb[:3]) > 245 else "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _paragraph(chars: list[_Char], box: tuple[float, float, float, float]) -> dict[str, Any]:
    """칸 글자를 한 문단으로. 색·굵기가 같은 글자끼리 묶고, 칸 안 위치로 정렬을 정한다."""
    runs: list[tuple[str, str | None, bool]] = []
    visible = [c for c in chars if not c.text.isspace() and c.x1 > c.x0]
    for ch in chars:
        text = " " if ch.text.isspace() or ch.x1 <= ch.x0 else ch.text
        if runs and (text == " " or (runs[-1][1], runs[-1][2]) == (ch.color, ch.bold)):
            runs[-1] = (runs[-1][0] + text, runs[-1][1], runs[-1][2])
        else:
            runs.append((text, ch.color, ch.bold))
    content: list[dict[str, Any]] = []
    text_so_far = ""
    for i, (text, color, bold) in enumerate(runs):
        text = " ".join(text.split()) + (" " if text.endswith(" ") and i < len(runs) - 1 else "")
        if text_so_far == "" or text_so_far.endswith(" "):
            text = text.lstrip()
        if not text:
            continue
        text_so_far += text
        marks: list[dict[str, Any]] = []
        if bold:
            marks.append({"type": "bold"})
        if color:
            marks.append({"type": "textStyle", "attrs": {"color": color}})
        node: dict[str, Any] = {"type": "text", "text": text}
        if marks:
            node["marks"] = marks
        content.append(node)
    if content and content[-1]["text"].endswith(" "):
        content[-1]["text"] = content[-1]["text"].rstrip()
    paragraph: dict[str, Any] = {"type": "paragraph"}
    if content:
        paragraph["content"] = content
    if visible:
        left_gap = min(c.x0 for c in visible) - box[0]
        right_gap = box[2] - max(c.x1 for c in visible)
        if abs(left_gap - right_gap) <= max(4.0, 0.15 * (box[2] - box[0])):
            paragraph["attrs"] = {"textAlign": "center"}
        elif right_gap < left_gap:
            paragraph["attrs"] = {"textAlign": "right"}
    return paragraph


def _table_json(
    xs: list[float],
    ys: list[float],
    regions: list[_Region],
    chars: list[_Char],
    images: list[tuple[tuple[float, float, float, float], str, float]],
    rendered: Any,
) -> dict[str, Any]:
    def region_of(x: float, y: float) -> int | None:
        for i, reg in enumerate(regions):
            if xs[reg.c0] < x < xs[reg.c1] and ys[reg.r0] < y < ys[reg.r1]:
                return i
        return None

    # 글자를 읽기 순서대로 칸에 넣는다. 위치 없는 공백은 바로 앞 글자의 칸으로.
    cell_chars: dict[int, list[_Char]] = collections.defaultdict(list)
    last: int | None = None
    for ch in chars:
        if ch.text.isspace() or ch.x1 <= ch.x0:
            if last is not None:
                cell_chars[last].append(ch)
            continue
        last = region_of(ch.cx, ch.cy)
        if last is not None:
            cell_chars[last].append(ch)
    cell_images: dict[int, list[tuple[str, float]]] = collections.defaultdict(list)
    for (x0, top, x1, bottom), src, width in images:
        idx = region_of((x0 + x1) / 2, (top + bottom) / 2)
        if idx is not None:
            cell_images[idx].append((src, width))

    # 시작하는 칸이 없는 줄(전부 위 칸에 합쳐진 줄)은 없애고 rowspan을 줄인다.
    starts = sorted({reg.r0 for reg in regions})
    row_index = {r: i for i, r in enumerate(starts)}

    def kept_rows(r0: int, r1: int) -> int:
        return sum(1 for r in starts if r0 <= r < r1)

    col_px = [round((xs[c + 1] - xs[c]) * PT_TO_PX) for c in range(len(xs) - 1)]
    rows: list[list[dict[str, Any]]] = [[] for _ in starts]
    for i, reg in sorted(enumerate(regions), key=lambda p: (p[1].r0, p[1].c0)):
        box = (xs[reg.c0], ys[reg.r0], xs[reg.c1], ys[reg.r1])
        attrs: dict[str, Any] = {
            "colspan": reg.c1 - reg.c0,
            "rowspan": kept_rows(reg.r0, reg.r1),
            "colwidth": col_px[reg.c0 : reg.c1],
        }
        background = _background(rendered, box)
        if background:
            attrs["background"] = background
        content: list[dict[str, Any]] = [
            {"type": "image", "attrs": {"src": src, "width": width}}
            for src, width in cell_images[i]
        ]
        paragraph = _paragraph(cell_chars[i], box)
        if paragraph.get("content") or not content:
            content.append(paragraph)
        rows[row_index[reg.r0]].append({"type": "tableCell", "attrs": attrs, "content": content})
    return {"type": "table", "content": [{"type": "tableRow", "content": cells} for cells in rows]}


def _page_images(
    page: pdfium.PdfPage, budget: list[int]
) -> list[tuple[tuple[float, float, float, float], str, float]]:
    height = page.get_height()
    out: list[tuple[tuple[float, float, float, float], str, float]] = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE], max_depth=5):
        if budget[0] <= 0:
            break
        left, bottom, right, top = obj.get_bounds()
        if right - left < 6 or top - bottom < 6:
            continue
        try:
            image = obj.get_bitmap(render=True).to_pil().convert("RGB")
        except Exception:  # 손상되었거나 지원하지 않는 이미지 형식은 건너뛴다
            continue
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        src = assets.save_image(buffer.getvalue(), "image/png")
        budget[0] -= 1
        out.append(
            ((left, height - top, right, height - bottom), src, round((right - left) * PT_TO_PX))
        )
    return out


def extract_tables(data: bytes) -> list[dict[str, Any]]:
    """PDF에서 찾은 표 목록: page, index, rows, cols, content(본문 JSON), preview_html."""
    if not data.startswith(b"%PDF"):
        raise _invalid("PDF 파일이 아닙니다.")
    if len(data) > MAX_BYTES:
        raise _invalid("PDF는 20MB까지 올릴 수 있습니다.")
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        raise _invalid("PDF를 열 수 없습니다 (암호가 걸렸거나 손상된 파일).") from None
    found: list[dict[str, Any]] = []
    budget = [MAX_IMAGES]
    with pdfplumber.open(io.BytesIO(data)) as plumber:
        for page_no in range(min(len(doc), MAX_PAGES)):
            ppage = plumber.pages[page_no]
            fpage = doc[page_no]
            tables = ppage.find_tables(
                {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
            )
            bboxes = _merge_bboxes([t.bbox for t in tables if len(t.cells) >= 2])
            if not bboxes:
                continue
            chars = _page_chars(fpage)
            images = _page_images(fpage, budget)
            rendered = fpage.render(scale=RENDER_SCALE).to_pil().convert("RGB")
            for bbox in bboxes:
                xs, ys, regions = _grid(ppage, bbox)
                if len(regions) < 2 or len(xs) - 1 > 30 or len(ys) - 1 > 300:
                    continue
                table = _table_json(xs, ys, regions, chars, images, rendered)
                content = {"type": "doc", "content": [table, {"type": "paragraph"}]}
                content = richtext.normalize(content)
                if richtext.validate(content):
                    continue  # 본문 규칙에 맞지 않는 표는 건너뛴다
                found.append(
                    {
                        "page": page_no + 1,
                        "index": len(found),
                        "rows": len(table["content"]),
                        "cols": len(xs) - 1,
                        "content": content,
                        "preview_html": richtext.to_html(content, {}),
                    }
                )
    if not found:
        raise _invalid(
            "표를 찾지 못했습니다. 칸마다 선이 그어진 표만 가져올 수 있습니다 "
            "(스캔한 PDF는 지원하지 않습니다)."
        )
    return found
