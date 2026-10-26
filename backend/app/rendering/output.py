"""HTML → PDF(Chromium) → 페이지별 PNG(PDFium), 통합본 PDF(pypdf).

PNG는 화면 캡처가 아니라 생성된 PDF를 PDFium으로 래스터화하므로 PDF와 내용이 같다.
Chromium은 `playwright install chromium`으로, PDFium은 pypdfium2 패키지로 설치된다.
"""

import asyncio
import atexit
import contextlib
import html
import platform
import sys
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import pypdfium2 as pdfium
from playwright.async_api import Browser, Page, Playwright, async_playwright
from pypdf import PdfReader, PdfWriter

from app.models import FileFormat, OutputDocumentType
from app.rendering import RENDERER_VERSION
from app.rendering.composer import DOCUMENT_LABELS, SetPlan
from app.rendering.html import render_document_html

# 파일명에 쓰는 문서 이름 (가이드 10장 예: {상품코드}_v{버전}_약관.pdf)
FILE_LABELS = {
    OutputDocumentType.TERMS: "약관",
    OutputDocumentType.TERMS_SUMMARY: "약관주요내용",
    OutputDocumentType.PRODUCT_DESCRIPTION: "상품설명서",
    OutputDocumentType.COMBINED: "통합",
}
DEFAULT_PNG_DPI = 150
T = TypeVar("T")


@dataclass(frozen=True)
class RenderedFile:
    # 상품 문서 세트의 문서 종류. KMS 문서 출력은 None
    document_type: OutputDocumentType | None
    format: FileFormat
    page_no: int | None
    path: Path

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class RenderResult:
    files: list[RenderedFile]
    renderer_version: str


def _footer_html(label: str) -> str:
    text = html.escape(label)
    return (
        "<div style=\"width:100%;font-family:'Noto Sans CJK KR','Malgun Gothic',sans-serif;"
        'font-size:7pt;color:#555;padding:0 16mm;display:flex;justify-content:space-between;">'
        f'<span>{text}</span><span><span class="pageNumber"></span> / '
        '<span class="totalPages"></span></span></div>'
    )


class _BrowserHost:
    """프로세스당 하나의 Chromium과 탭을 띄워 두고 렌더링마다 재사용한다.

    Windows에서는 Chromium 실행과 새 탭 생성에 각각 수 초가 걸려 매번 띄우면 매우 느리다.
    Chromium은 전용 스레드의 이벤트 루프에서 돈다. Windows는 하위 프로세스를 지원하는
    Proactor 루프가 필요한데, worker는 psycopg 때문에 Selector 루프 정책을 쓰므로
    (app/worker.py) 여기서 루프를 직접 만든다. 렌더링은 잠금으로 한 번에 하나씩 한다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            loop: asyncio.AbstractEventLoop = (
                asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
            )
            threading.Thread(target=loop.run_forever, name="chromium", daemon=True).start()
            self._loop = loop
        return self._loop

    def call(self, fn: Callable[[Page], Awaitable[T]]) -> T:
        with self._lock:
            future: Future[T] = asyncio.run_coroutine_threadsafe(
                self._with_page(fn), self._ensure_loop()
            )
            return future.result()

    async def _with_page(self, fn: Callable[[Page], Awaitable[T]]) -> T:
        if self._page is None or self._page.is_closed() or not self._browser_connected():
            await self._start()
        assert self._page is not None
        try:
            return await fn(self._page)
        except Exception:
            await self._shutdown()  # 다음 렌더링은 새 Chromium으로 시작한다.
            raise

    def _browser_connected(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def _start(self) -> None:
        await self._shutdown()
        self._playwright = await async_playwright().start()
        # 컨테이너의 작은 /dev/shm 대신 /tmp를 쓴다 (큰 문서 렌더링 중 멈춤 방지).
        self._browser = await self._playwright.chromium.launch(args=["--disable-dev-shm-usage"])
        self._page = await self._browser.new_page()

    async def _shutdown(self) -> None:
        for close in (
            self._browser.close if self._browser else None,
            self._playwright.stop if self._playwright else None,
        ):
            if close is not None:
                with contextlib.suppress(Exception):  # 이미 종료된 경우
                    await close()
        self._playwright, self._browser, self._page = None, None, None

    def close(self) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout=10)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None


_browser_host = _BrowserHost()
atexit.register(_browser_host.close)


def pdf_to_pngs(
    pdf: Path, document_type: OutputDocumentType | None, stem: str, dpi: int
) -> list[RenderedFile]:
    files = []
    document = pdfium.PdfDocument(pdf)
    try:
        for page_no, page in enumerate(document, start=1):
            target = pdf.with_name(f"{stem}_p{page_no:02d}.png")
            page.render(scale=dpi / 72).to_pil().save(target, format="PNG", dpi=(dpi, dpi))
            files.append(RenderedFile(document_type, FileFormat.PNG, page_no, target))
    finally:
        document.close()
    return files


async def _print_pdf(page: Page, html_text: str, path: Path, footer_label: str) -> None:
    await page.set_content(html_text, wait_until="load")
    await page.pdf(
        path=str(path),
        prefer_css_page_size=True,
        print_background=True,
        display_header_footer=True,
        header_template="<span></span>",
        footer_template=_footer_html(footer_label),
    )


def _version(chromium_version: str, png_dpi: int) -> str:
    return (
        f"terms-flow-renderer/{RENDERER_VERSION}; chromium/{chromium_version}; "
        f"pdfium/{pdfium.PDFIUM_INFO}; png-dpi/{png_dpi}; os/{platform.system()}"
    )


async def _render_single(page: Page, html_text: str, path: Path, footer_label: str) -> str:
    await _print_pdf(page, html_text, path, footer_label)
    browser = page.context.browser
    return browser.version if browser else "unknown"


def render_single(
    html_text: str, *, stem: str, footer_label: str, out_dir: Path, png_dpi: int = DEFAULT_PNG_DPI
) -> RenderResult:
    """HTML 문서 하나를 PDF와 페이지별 PNG로 만든다 (KMS 문서 발행)."""
    pdf_path = out_dir / f"{stem}.pdf"
    chromium_version = _browser_host.call(
        lambda page: _render_single(page, html_text, pdf_path, footer_label)
    )
    files = [RenderedFile(None, FileFormat.PDF, None, pdf_path)]
    files += pdf_to_pngs(pdf_path, None, stem, png_dpi)
    return RenderResult(files=files, renderer_version=_version(chromium_version, png_dpi))


async def _render_pdfs(
    page: Page, plan: SetPlan, version_label: str, out_dir: Path
) -> tuple[list[tuple[OutputDocumentType, str, Path]], str]:
    product_code = plan.snapshot["product"]["product_code"]
    results = []
    for doc in plan.documents:
        doc_type = OutputDocumentType(doc.document_type.value)
        stem = f"{product_code}_{version_label}_{FILE_LABELS[doc_type]}"
        pdf_path = out_dir / f"{stem}.pdf"
        await _print_pdf(
            page,
            render_document_html(plan, doc),
            pdf_path,
            f"{product_code} · {version_label} · {DOCUMENT_LABELS[doc.document_type]}",
        )
        results.append((doc_type, stem, pdf_path))
    browser = page.context.browser
    return results, browser.version if browser else "unknown"


def render_outputs(
    plan: SetPlan, *, version_label: str, out_dir: Path, png_dpi: int = DEFAULT_PNG_DPI
) -> RenderResult:
    """3종 개별 PDF, 통합 PDF, 각 PDF의 페이지별 PNG를 만든다.

    version_label은 파일명과 바닥글에 쓴다 (예: v3).
    """
    product_code = plan.snapshot["product"]["product_code"]
    pdfs, chromium_version = _browser_host.call(
        lambda page: _render_pdfs(page, plan, version_label, out_dir)
    )
    files: list[RenderedFile] = []
    for doc_type, stem, pdf_path in pdfs:
        files.append(RenderedFile(doc_type, FileFormat.PDF, None, pdf_path))
        files += pdf_to_pngs(pdf_path, doc_type, stem, png_dpi)

    # 통합본: 약관 → 약관 주요 내용 → 상품설명서 (plan.documents 순서)
    combined_stem = f"{product_code}_{version_label}_{FILE_LABELS[OutputDocumentType.COMBINED]}"
    combined = out_dir / f"{combined_stem}.pdf"
    writer = PdfWriter()
    for _, _, pdf_path in pdfs:
        for pdf_page in PdfReader(pdf_path).pages:
            writer.add_page(pdf_page)
    with combined.open("wb") as fh:
        writer.write(fh)
    files.append(RenderedFile(OutputDocumentType.COMBINED, FileFormat.PDF, None, combined))
    files += pdf_to_pngs(combined, OutputDocumentType.COMBINED, combined_stem, png_dpi)

    return RenderResult(files=files, renderer_version=_version(chromium_version, png_dpi))
