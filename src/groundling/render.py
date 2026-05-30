"""Static-HTML cite viewer generation.

Two responsibilities (split across helpers):

1. Rasterise a PDF page to PNG (render_pdf_page).
2. Generate per-cite HTML files (render_cite_html and render_web_redirect,
   added in later tasks).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import fitz
from jinja2 import Environment, FileSystemLoader, select_autoescape


def render_pdf_page(
    pdf_path: Path,
    *,
    page: int,
    out_path: Path,
    scale: float = 2.0,
) -> tuple[int, int]:
    """Rasterise `pdf_path` page `page` (1-indexed) to PNG at `out_path`.

    Returns (width_px, height_px) — the dimensions of the saved PNG.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        pdf_page = doc.load_page(page - 1)
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        pix.save(out_path)
        return pix.width, pix.height


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _strip_trailing_ellipsis(s: str) -> str:
    s = s.rstrip()
    for sentinel in ("…", "..."):
        if s.endswith(sentinel):
            s = s[: -len(sentinel)].rstrip()
            break
    return s


def build_text_fragment_url(url: str, cited_text: str) -> str:
    needle = _strip_trailing_ellipsis(cited_text)
    return f"{url}#:~:text={quote(needle, safe='')}"


def render_cite_web(
    *,
    out_path: Path,
    url: str,
    title: str,
    cited_text: str,
) -> None:
    fragment_url = build_text_fragment_url(url, cited_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    template = _env.get_template("cite_web.html.j2")
    out_path.write_text(template.render(
        title=title,
        fragment_url=fragment_url,
    ))


def _build_highlights(
    spans: list[dict],
    *,
    scale: float,
    canvas_padding_px: int = 0,
) -> list[dict]:
    """Convert (page, bbox) spans into pixel-space rectangles for the
    HTML overlay. Caller already filtered to one page."""
    highlights = []
    for s in spans:
        x0, y0, x1, y1 = s["bbox"]
        highlights.append({
            "left": x0 * scale + canvas_padding_px,
            "top": y0 * scale + canvas_padding_px,
            "width": (x1 - x0) * scale,
            "height": (y1 - y0) * scale,
        })
    return highlights


def render_cite_pdf(
    *,
    pdf_path: Path,
    out_html: Path,
    image_path: Path,
    cite_id: int,
    total: int,
    question: str,
    cited_text: str,
    spans: list[dict],
    prev_id: int | None,
    next_id: int | None,
    scale: float = 2.0,
) -> None:
    """Render the cited PDF page to PNG (if not present) and write the
    HTML viewer that references it.

    Highlights all spans on the page of the first span. If spans cross
    pages we render the first span's page and overlay only same-page
    spans — multi-page citations are rare for v1; revisit if needed.
    """
    if not spans:
        return
    first_page = spans[0]["page"]
    page_spans = [s for s in spans if s["page"] == first_page]

    # Render page image only if it doesn't already exist (caller may dedupe).
    if not image_path.exists():
        width_px, height_px = render_pdf_page(
            pdf_path, page=first_page, out_path=image_path, scale=scale,
        )
    else:
        # Re-derive dimensions for the HTML <img>.
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(first_page - 1)
            width_px = int(page.rect.width * scale)
            height_px = int(page.rect.height * scale)

    highlights = _build_highlights(page_spans, scale=scale)
    template = _env.get_template("cite_pdf.html.j2")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(template.render(
        cite_id=cite_id,
        total=total,
        question=question,
        cited_text=cited_text,
        pdf_filename=pdf_path.name,
        page=first_page,
        image_filename=image_path.name,
        image_w=width_px,
        image_h=height_px,
        highlights=highlights,
        prev_id=prev_id,
        next_id=next_id,
    ))
