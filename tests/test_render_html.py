from __future__ import annotations

import re
from pathlib import Path

import pytest

from groundling.render import build_text_fragment_url, render_cite_pdf, render_cite_web


def test_text_fragment_url_encodes_cited_text():
    url = build_text_fragment_url(
        "https://example.com/article",
        "Revenue grew 20% YoY",
    )
    assert url == "https://example.com/article#:~:text=Revenue%20grew%2020%25%20YoY"


def test_text_fragment_url_strips_trailing_ellipsis():
    """Anthropic truncates cited_text to 150 chars with `…`. Strip it
    before URL-encoding so the fragment matches the source page."""
    url = build_text_fragment_url(
        "https://example.com/x",
        "Some long quote ends here…",
    )
    assert "%E2%80%A6" not in url
    assert url.endswith("text=Some%20long%20quote%20ends%20here")


def test_text_fragment_url_strips_trailing_three_dots():
    url = build_text_fragment_url("https://x/", "Quote ends...")
    assert url.endswith("text=Quote%20ends")


def test_render_cite_web_writes_redirect_stub(tmp_path):
    out = tmp_path / "3.html"
    render_cite_web(
        out_path=out,
        url="https://example.com/article",
        title="Article",
        cited_text="Revenue grew 20% YoY",
    )
    html = out.read_text()
    assert "<meta http-equiv=\"refresh\"" in html
    assert "Revenue%20grew%2020%25%20YoY" in html
    assert "Article" in html


def test_render_cite_pdf_writes_image_and_bbox_divs(text_pdf, tmp_path):
    """Renders PDF page → PNG and writes the HTML referencing it."""
    out_html = tmp_path / "1.html"
    image_path = tmp_path / "1.png"
    spans = [
        {"page": 1, "bbox": [72.0, 70.0, 150.0, 85.0]},
    ]
    render_cite_pdf(
        pdf_path=text_pdf,
        out_html=out_html,
        image_path=image_path,
        cite_id=1,
        total=3,
        question="what does it say?",
        cited_text="Hello",
        spans=spans,
        prev_id=None,
        next_id=2,
        scale=2.0,
    )
    assert image_path.exists()
    html = out_html.read_text()
    assert "Citation 1 / 3" in html
    assert "sample.pdf, page 1" in html  # uses text_pdf.name → "sample.pdf"
    assert "next" in html
    assert "<img" in html
    # Highlight div with 2x-scaled bbox: left=144, top=140, width=156, height=30.
    assert re.search(r"left:\s*144(?:\.0)?px", html)
    assert re.search(r"top:\s*140(?:\.0)?px", html)
    assert re.search(r"width:\s*156(?:\.0)?px", html)
    assert re.search(r"height:\s*30(?:\.0)?px", html)


def test_render_cite_pdf_highlights_share_positioning_context_with_image(text_pdf, tmp_path):
    """Highlights' (top, left) are PDF-derived pixel offsets relative to
    the image's top-left. They must therefore live inside an element
    whose padding-box top-left coincides with the image's top-left —
    i.e. inside `.page` (no padding/border), NOT directly under
    `.page-wrap` which has `padding: 20px`. Regression: ~10pt offset
    bug where highlights appeared one line too high."""
    out_html = tmp_path / "1.html"
    image_path = tmp_path / "1.png"
    render_cite_pdf(
        pdf_path=text_pdf,
        out_html=out_html,
        image_path=image_path,
        cite_id=1, total=1,
        question="?", cited_text="?",
        spans=[{"page": 1, "bbox": [10, 10, 20, 20]}],
        prev_id=None, next_id=None, scale=2.0,
    )
    html = out_html.read_text()
    # The .page container must exist and have position: relative.
    assert ".page {" in html
    assert "position: relative" in html.split(".page {", 1)[1].split("}", 1)[0]
    # The img and the highlight must both sit inside .page (so the
    # highlight's absolute coords are measured from the image origin).
    page_block = html.split('<div class="page">', 1)[1].split("</div>", 2)
    # page_block[0] is content up to first </div> — but we have <img>
    # then </div> (closing .page). The highlight should appear before
    # the page's closing </div>.
    inside_page = html.split('<div class="page">', 1)[1].split("</div>\n  </div>", 1)[0]
    assert "<img" in inside_page
    assert 'class="highlight"' in inside_page
    # And .page-wrap must NOT itself be position: relative (otherwise
    # the highlight would resolve against its padding box).
    page_wrap_rules = html.split(".page-wrap {", 1)[1].split("}", 1)[0]
    assert "position: relative" not in page_wrap_rules


def test_render_cite_pdf_multiple_spans_emits_multiple_highlights(text_pdf, tmp_path):
    spans = [
        {"page": 1, "bbox": [10, 10, 20, 20]},
        {"page": 1, "bbox": [30, 30, 40, 40]},
        {"page": 1, "bbox": [50, 50, 60, 60]},
    ]
    out_html = tmp_path / "1.html"
    image_path = tmp_path / "1.png"
    render_cite_pdf(
        pdf_path=text_pdf,
        out_html=out_html,
        image_path=image_path,
        cite_id=1, total=1,
        question="?", cited_text="?",
        spans=spans, prev_id=None, next_id=None, scale=2.0,
    )
    html = out_html.read_text()
    assert html.count('class="highlight"') == 3
