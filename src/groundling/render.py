"""Static-HTML cite viewer generation.

Two responsibilities (split across helpers):

1. Rasterise a PDF page to PNG (render_pdf_page).
2. Generate per-cite HTML files (render_cite_html and render_web_redirect,
   added in later tasks).
"""
from __future__ import annotations

from pathlib import Path

import fitz


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
