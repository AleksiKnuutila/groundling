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
    # Base64 image bytes are in the IMG_REGISTRY (not in <img src>).
    assert "data:image/png;base64," in html
    assert "window.IMG_REGISTRY" in html
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


def test_inline_html_dedupes_same_page_image(tmp_path):
    """Two cites on the same PDF page should result in EXACTLY ONE
    base64-encoded data URI in the output — the same image must not
    be inlined twice.

    Regression guard for REL-228."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [
        {"cite_id": 1, "kind": "pdf",
         "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
         "marker_quote": "first", "claim_text": "c1",
         "pdf_filename": "doc.pdf"},
        {"cite_id": 2, "kind": "pdf",
         "spans": [{"page": 1, "bbox": [50.0, 60.0, 70.0, 80.0]}],
         "marker_quote": "second", "claim_text": "c2",
         "pdf_filename": "doc.pdf"},
    ]
    # Both cites share the same image path (same PDF, same page).
    image_paths = {1: fake_png, 2: fake_png}
    image_dims = {1: (1, 1), 2: (1, 1)}
    html = build_inline_answer_html(
        answer_md=(
            '[a](cite://1 "first") and [b](cite://2 "second")'
        ),
        cite_records=cite_records, image_paths=image_paths,
        image_dims=image_dims, scale=2.0,
    )
    # Exactly one base64 image payload.
    assert html.count("data:image/png;base64,") == 1


def test_inline_html_dedupes_per_unique_page(tmp_path):
    """Three cites: two on page 1 of doc.pdf, one on page 2.
    Output should have EXACTLY TWO base64 data URIs."""
    page1_png = tmp_path / "1.png"
    page2_png = tmp_path / "2.png"
    page1_png.write_bytes(TINY_PNG)
    page2_png.write_bytes(TINY_PNG)
    cite_records = [
        {"cite_id": 1, "kind": "pdf",
         "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
         "marker_quote": "a", "claim_text": "ca", "pdf_filename": "doc.pdf"},
        {"cite_id": 2, "kind": "pdf",
         "spans": [{"page": 1, "bbox": [50.0, 60.0, 70.0, 80.0]}],
         "marker_quote": "b", "claim_text": "cb", "pdf_filename": "doc.pdf"},
        {"cite_id": 3, "kind": "pdf",
         "spans": [{"page": 2, "bbox": [10.0, 20.0, 30.0, 40.0]}],
         "marker_quote": "c", "claim_text": "cc", "pdf_filename": "doc.pdf"},
    ]
    image_paths = {1: page1_png, 2: page1_png, 3: page2_png}
    image_dims = {1: (1, 1), 2: (1, 1), 3: (1, 1)}
    html = build_inline_answer_html(
        answer_md=(
            '[a](cite://1 "a"), [b](cite://2 "b"), [c](cite://3 "c")'
        ),
        cite_records=cite_records, image_paths=image_paths,
        image_dims=image_dims, scale=2.0,
    )
    assert html.count("data:image/png;base64,") == 2


def test_inline_html_supports_hash_deep_link(tmp_path):
    """The output must contain the JS that opens a cite dialog when
    the page loads with #cite-N in the URL hash. Lets chat markdown
    like `[3](answer.html#cite-3)` jump straight to verification."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [{
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        "marker_quote": "q", "claim_text": "c",
        "pdf_filename": "doc.pdf",
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")',
        cite_records=cite_records, image_paths={1: fake_png},
        image_dims={1: (1, 1)}, scale=2.0,
    )
    # The deep-link handler reads window.location.hash and opens
    # the matching <dialog>. Pin the load-bearing regex + showModal call.
    assert "window.location.hash.match" in html
    assert "#cite-" in html  # the regex literal
    assert "showModal" in html


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
