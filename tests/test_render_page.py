from __future__ import annotations

from pathlib import Path

import fitz

from groundling.render import render_pdf_page


def test_render_pdf_page_creates_png(text_pdf, tmp_path):
    out = tmp_path / "page1.png"
    width_px, height_px = render_pdf_page(text_pdf, page=1, out_path=out, scale=2.0)
    assert out.exists()
    assert out.stat().st_size > 0
    # The returned dimensions match the PNG actually produced.
    assert width_px > 0 and height_px > 0
    # Verify PNG content by opening with fitz (it reads images too).
    # fitz.Pixmap reports true pixel dims; fitz.open() on a PNG converts
    # to PDF points (px * 72/96) which is not what we want to check here.
    img = fitz.Pixmap(out)
    assert img.width == width_px
    assert img.height == height_px


def test_render_at_2x_scale_doubles_pdf_user_space_dims(text_pdf, tmp_path):
    out = tmp_path / "p.png"
    width_px, height_px = render_pdf_page(text_pdf, page=1, out_path=out, scale=2.0)
    pdf = fitz.open(text_pdf)
    page = pdf[0]
    expected_w = int(page.rect.width * 2.0)
    expected_h = int(page.rect.height * 2.0)
    pdf.close()
    assert abs(width_px - expected_w) <= 1
    assert abs(height_px - expected_h) <= 1
