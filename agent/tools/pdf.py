"""PDF reading. The app shows you a page; the agent gets that page's text with your question."""
from __future__ import annotations

from pathlib import Path

from ..errors import ToolError
from .base import Tool, params

MAX_PAGES_PER_CALL = 5
MAX_CHARS_PER_CALL = 12_000
NO_TEXT_NOTE = ("(This page has almost no selectable text. It may be a scanned picture or a figure, "
                "so I can't read it. Tell the user honestly, and ask them to type the part they mean.)")


class PdfSession:
    """Holds the PDF you currently have open."""

    def __init__(self) -> None:
        self.doc = None
        self.path: Path | None = None

    # ----- opening -----
    def open(self, path: str | Path) -> int:
        import pymupdf

        p = Path(path).expanduser()
        if not p.is_file():
            raise ToolError(f"I can't find the file: {p}")
        try:
            doc = pymupdf.open(p)
        except Exception as e:
            raise ToolError(f"I couldn't open that PDF ({e}).")
        if doc.needs_pass:
            doc.close()
            raise ToolError("That PDF is password-protected.")
        if doc.page_count == 0:
            doc.close()
            raise ToolError("That PDF has no pages.")
        self.close()
        self.doc, self.path = doc, p
        return doc.page_count

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
        self.doc, self.path = None, None

    @property
    def is_open(self) -> bool:
        return self.doc is not None

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    @property
    def name(self) -> str:
        return self.path.name if self.path else ""

    # ----- reading -----
    def _check(self, n: int) -> int:
        if not self.is_open:
            raise ToolError("No PDF is open. Ask the user to open one first.")
        if not 1 <= n <= self.page_count:
            raise ToolError(f"Page {n} doesn't exist. This PDF has {self.page_count} pages.")
        return n - 1

    def page_text(self, n: int) -> str:
        return self.doc[self._check(n)].get_text("text").strip()

    def render_page(self, n: int, zoom: float = 1.6) -> bytes:
        import pymupdf

        page = self.doc[self._check(n)]
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")

    def search(self, query: str, max_hits: int = 8) -> list[tuple[int, str]]:
        if not self.is_open:
            raise ToolError("No PDF is open.")
        q = query.strip().lower()
        if not q:
            raise ToolError("Give me something to search for.")
        hits: list[tuple[int, str]] = []
        for i in range(self.page_count):
            text = " ".join(self.doc[i].get_text("text").split())
            pos = text.lower().find(q)
            if pos != -1:
                start = max(0, pos - 60)
                hits.append((i + 1, "..." + text[start:pos + len(q) + 80] + "..."))
                if len(hits) >= max_hits:
                    break
        return hits

    def context_for(self, page: int, include_previous: bool = False, highlight: str = "",
                    max_chars: int = 6000) -> str:
        """The text block given to the AI along with your question."""
        if not self.is_open:
            return ""
        page = min(max(page, 1), self.page_count)
        lines = [f'[Reader context] The user is reading "{self.name}" and is currently on page '
                 f"{page} of {self.page_count}."]
        if highlight.strip():
            lines.append(f"Text the user highlighted: {highlight.strip()[:1500]}")
        pages = [page - 1, page] if include_previous and page > 1 else [page]
        for pg in pages:
            text = self.page_text(pg)
            label = "Page text" if pg == page else f"Previous page ({pg}) text"
            if len(text) < 20:
                text = NO_TEXT_NOTE
            elif len(text) > max_chars:
                text = text[:max_chars] + "\n...[page text cut for length]"
            lines.append(f"--- {label} ---\n{text}")
        return "\n".join(lines)


def make_pdf_tools(pdf: PdfSession) -> list[Tool]:
    def pdf_info() -> str:
        if not pdf.is_open:
            return "No PDF is open."
        return f'"{pdf.name}" has {pdf.page_count} pages.'

    def read_pdf_pages(start_page: int, end_page: int | None = None) -> str:
        start = int(start_page)
        end = int(end_page) if end_page is not None else start
        if end < start:
            start, end = end, start
        end = min(end, start + MAX_PAGES_PER_CALL - 1)
        out, used = [], 0
        for n in range(start, end + 1):
            text = pdf.page_text(n) or NO_TEXT_NOTE
            chunk = f"=== Page {n} ===\n{text}"
            if used + len(chunk) > MAX_CHARS_PER_CALL:
                out.append(f"=== Page {n} === (cut: too much text; ask for fewer pages)")
                break
            out.append(chunk)
            used += len(chunk)
        return "\n\n".join(out)

    def search_pdf(query: str) -> str:
        hits = pdf.search(query)
        if not hits:
            return f"No page contains '{query}'."
        return "\n".join(f"Page {pg}: {snip}" for pg, snip in hits)

    return [
        Tool("pdf_info", "Say which PDF is open and how many pages it has.", params({}), pdf_info),
        Tool("read_pdf_pages",
             f"Read the text of PDF pages (max {MAX_PAGES_PER_CALL} pages per call). Page numbers start at 1.",
             params({"start_page": {"type": "integer"}, "end_page": {"type": "integer"}}, ["start_page"]),
             read_pdf_pages),
        Tool("search_pdf", "Find which pages of the open PDF contain a word or phrase.",
             params({"query": {"type": "string"}}, ["query"]), search_pdf),
    ]
