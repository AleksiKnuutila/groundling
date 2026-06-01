"""Self-contained single-file answer.html generation."""
from __future__ import annotations

from pathlib import Path

from groundling.answer_html_inline import build_inline_answer_html


# 1x1 red PNG — smallest possible valid PNG.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000"
    "00907753de0000000c49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def test_inline_html_has_no_external_resources(tmp_path):
    """The output HTML must contain no <img src="cites/...">, no
    <iframe>, and no external <link> — everything is inlined."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [{
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        "marker_quote": "test quote",
        "claim_text": "test claim",
        "pdf_filename": "test.pdf",
    }]
    image_paths = {1: fake_png}
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "test quote")',
        cite_records=cite_records, image_paths=image_paths,
        image_dims={1: (1, 1)}, scale=2.0,
    )
    assert 'src="cites/' not in html
    assert 'src="data:image/png;base64,' in html
    assert '<iframe' not in html
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html


def test_inline_html_includes_cite_content_inline(tmp_path):
    """Cite content (quote + page-image + claim) embedded directly."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [{
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        "marker_quote": "the cited verbatim text",
        "claim_text": "the surrounding claim",
        "pdf_filename": "doc.pdf",
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "the cited verbatim text")',
        cite_records=cite_records, image_paths={1: fake_png},
        image_dims={1: (1, 1)}, scale=2.0,
    )
    assert "the cited verbatim text" in html
    assert "doc.pdf" in html


def test_inline_html_handles_web_cites(tmp_path):
    """Web cites have no PDF image — render with quote + URL only."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/news",
        "marker_quote": "the quoted web text",
        "claim_text": "the claim from web",
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "the quoted web text")',
        cite_records=cite_records, image_paths={},
        image_dims={}, scale=2.0,
    )
    assert 'data-kind="web"' in html
    assert "https://example.com/news" in html
    assert "the quoted web text" in html


def test_inline_html_size_bounded(tmp_path):
    """Sanity check: 1-cite output should be <50KB."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [{
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        "marker_quote": "q", "claim_text": "c",
        "pdf_filename": "tiny.pdf",
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")',
        cite_records=cite_records, image_paths={1: fake_png},
        image_dims={1: (1, 1)}, scale=2.0,
    )
    assert len(html) < 50_000
