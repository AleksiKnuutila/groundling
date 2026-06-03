"""Self-contained single-file answer.html generation."""
from __future__ import annotations

import tempfile
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
    <iframe>, and no external <link> to local resources — everything
    cite-related is inlined.

    (External <link rel="stylesheet"> to Google Fonts is allowed —
    that's a CDN font, not a local resource.)"""
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
    # New: per-cite data lives in a single window.GROUNDLING_CITES map.
    assert "window.GROUNDLING_CITES" in html
    # New: PR 1 default verdict state.
    assert 'data-state="none"' in html


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
    # Both the quote and the filename appear in the embedded JSON map.
    assert "the cited verbatim text" in html
    assert "doc.pdf" in html


def test_inline_html_handles_web_cites(tmp_path):
    """Web cites have no PDF image — render with quote + URL only."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/news",
        "title": "News Article",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "the quoted web text",
        "claim_text": "the claim from web",
        "excerpt": "before the quoted web text after",
        "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "the quoted web text")',
        cite_records=cite_records, image_paths={},
        image_dims={}, scale=2.0,
    )
    assert 'data-kind="web"' in html
    # URL appears in the cites JSON map (not as an anchor href, since
    # the URL is opened from the modal via JS).
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
    # Exactly one base64 image payload in the IMG_REGISTRY.
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
    """The output must contain the JS that opens a cite modal when
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
    # The deep-link handler reads location.hash and opens the matching
    # cite modal. Pin the load-bearing regex + showModal call.
    assert "location.hash.match" in html
    assert "#cite-" in html  # the regex literal
    assert "showModal" in html


def test_inline_html_cite_anchor_has_no_href(tmp_path):
    """In-page cite anchors must NOT carry href="#cite-N" — inside
    Claude.ai's artifact iframe, navigating to a fragment bubbles to
    the parent frame and tries to navigate claudeusercontent.com.
    Anchors are role=button with tabindex=0 instead; the modal opens
    via JS click handler. Deep links from chat still work because
    they're driven by location.hash on load, not in-page hrefs."""
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
    # No fragment href on the in-page cite anchor.
    assert 'href="#cite-' not in html
    # Keyboard-accessible without href.
    assert 'role="button"' in html
    assert 'tabindex="0"' in html


def test_inline_html_size_bounded(tmp_path):
    """Sanity check: 1-cite output should be <60KB."""
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
    # New template is larger than the old one (Plex/Newsreader CSS,
    # hover-card + modal JS) but still well under 60KB for 1 cite.
    assert len(html) < 60_000


def test_inline_html_web_cite_renders_excerpt_with_mark(tmp_path):
    """Excerpt with <mark> spliced around the quote is embedded in the
    GROUNDLING_CITES JSON map as `excerptHTML`. The JSON-encoder escapes
    `<` to \\u003c, so we look for the escaped form."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a",
        "title": "Article A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "the quote",
        "claim_text": "a claim",
        "excerpt": "before the quote after",
        "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "the quote")',
        cite_records=cite_records, image_paths={},
        image_dims={}, scale=2.0,
    )
    # Excerpt with <mark> wrapping the quote appears in the JSON map.
    # JSON-encoded for <script> safety: < becomes <.
    assert "before \\u003cmark\\u003ethe quote\\u003c/mark\\u003e after" in html
    # fetched_at surfaces in JSON.
    assert "2026-06-02" in html
    # The URL appears in the JSON map (not as an anchor href).
    assert "https://example.com/a" in html
    # Article title surfaces in JSON.
    assert "Article A" in html


def test_inline_html_web_cite_does_not_inflate_img_registry(tmp_path):
    """Web cites must not allocate image slots (no PDF page PNGs)."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "q", "claim_text": "c",
        "excerpt": "before q after",
        "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    # Empty registry — no base64 PNG bytes anywhere.
    assert "window.IMG_REGISTRY = []" in html
    assert "data:image/png;base64," not in html


def test_inline_html_web_cite_escapes_excerpt_html(tmp_path):
    """A `<script>` in the excerpt must be HTML-escaped before splicing,
    then JSON-escaped before embedding in <script>. The end result has
    no executable `<script>` payload sneaking through."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "x", "claim_text": "c",
        "excerpt": "<script>evil()</script> x rest",
        "quote_offset_in_excerpt": 24,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "x")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    # First _build_excerpt_html escapes <script> to &lt;script&gt;,
    # then _json_for_html escapes the `&` to &.
    # End result in the embedded JSON literal: &lt;script&gt;
    assert "\\u0026lt;script\\u0026gt;evil()" in html
    # No raw <script>evil()</script> string in the output.
    assert "<script>evil()</script>" not in html
    # The <mark>x</mark> splice still happened server-side, then was
    # JSON-encoded; look for the encoded form.
    assert "\\u003cmark\\u003ex\\u003c/mark\\u003e" in html


def test_inline_html_web_cite_data_in_cites_map(tmp_path):
    """Web cite data lives in the GROUNDLING_CITES JSON map. The
    template renders a single #modal element that the JS populates
    from the map at runtime (not one <dialog> per cite)."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "q", "claim_text": "c",
        "excerpt": "before q after", "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    # Single shared modal element.
    assert 'id="modal"' in html
    # The cite id 1 appears as a key in the JSON map.
    assert '"1":' in html or '"1" :' in html
    # The cite kind appears for the data-kind attribute too.
    assert 'data-kind="web"' in html


def test_inline_html_web_cite_deep_link_still_works(tmp_path):
    """A web cite's #cite-N hash link opens the modal the same way
    PDF cites do — via the location.hash handler that looks up the
    cite in the JSON map and calls openModal(cite)."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "q", "claim_text": "c",
        "excerpt": "before q after", "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    # The cite id appears in the JSON map (no per-cite <dialog id="cite-N">
    # element anymore — one shared modal looks up by id).
    assert '"id": 1' in html
    # The hash-handler is the JS pathway that opens the modal.
    assert "location.hash.match" in html


def test_inline_html_web_cite_has_css(tmp_path):
    """Sanity check on the new template's CSS / structure."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "q", "claim_text": "c",
        "excerpt": "before q after", "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    # New CSS hooks: state-colored cite underlines via data-state.
    assert 'a.cite[data-state="supported"]' in html
    # The single floating hover card and modal elements exist.
    assert 'id="card"' in html
    assert 'id="modal"' in html


def test_inline_html_has_trustbar(tmp_path):
    """The redesigned template prepends a sticky .trustbar header with
    the brand and a cite-count tally."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "q", "claim_text": "c",
        "excerpt": "before q after", "quote_offset_in_excerpt": 7,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    assert 'class="trustbar"' in html
    # Bold-around-number tally.
    assert '<b>1</b> cites validated' in html


def test_inline_html_zero_cites_tally(tmp_path):
    """When there are no cites, tally still renders 0 in the trustbar."""
    html = build_inline_answer_html(
        answer_md='hello, no cites',
        cite_records=[],
        image_paths={}, image_dims={}, scale=2.0,
    )
    assert '<b>0</b> cites validated' in html


def test_inline_html_spotlight_button_hidden_in_pr1(tmp_path):
    """PR 1 has no judge data, so every cite is data-state="none".
    The Spotlight-weak-claims toggle would just dim the whole page —
    keep it hidden until PR 2 wires verdicts.json through."""
    fake_png = tmp_path / "1.png"
    fake_png.write_bytes(TINY_PNG)
    cite_records = [{
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
        "marker_quote": "q", "claim_text": "c",
        "pdf_filename": "doc.pdf",
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "q")', cite_records=cite_records,
        image_paths={1: fake_png}, image_dims={1: (1, 1)}, scale=2.0,
    )
    # The weakBtn DOM element must not be rendered when has_judge_data is False.
    assert 'id="weakBtn"' not in html


def test_inline_html_escapes_script_tag_in_cite_data(tmp_path):
    """Cite-data JSON injected into a <script> tag must escape `<` so
    a `</script>` in claim/quote can't break out and inject HTML."""
    # Use the standard 1x1 PNG bytes for image_paths.
    png_bytes = bytes.fromhex(
        '89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489'
        '0000000D49444154789C636060000000000500015E2A24A30000000049454E44AE'
        '426082'
    )
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png_bytes)
        png_path = Path(f.name)
    records = [{
        'cite_id': 1, 'kind': 'pdf',
        'spans': [{'page': 1, 'bbox': [10, 20, 30, 40]}],
        'marker_quote': 'a verbatim quote',
        'claim_text': '</script>EVIL',
        'pdf_filename': 'doc.pdf',
    }]
    html = build_inline_answer_html(
        answer_md='X [c](cite://1).',
        cite_records=records,
        image_paths={1: png_path},
        image_dims={1: (200, 100)},
    )
    # The legit </script>s closing the two embedded scripts must still
    # be present, but no extra </script> from the JSON payload.
    assert html.count('</script>') == 2, html.count('</script>')
    # The < character from the hostile string must appear escaped in
    # the JSON-encoded payload.
    assert 'u003c' in html


def test_inline_html_renders_page_title_and_subtitle(tmp_path):
    """When page_title and subtitle are passed, they appear in the
    h1 and .sub div respectively."""
    html = build_inline_answer_html(
        answer_md='hello',
        cite_records=[],
        image_paths={},
        image_dims={},
        page_title='What does the doc say?',
        subtitle='Custom subtitle here',
    )
    assert '<h1>What does the doc say?</h1>' in html
    assert 'Custom subtitle here' in html


def test_inline_html_default_subtitle_is_cite_count(tmp_path):
    """When subtitle is None and total_cites > 0, the default subtitle
    is `'N cites validated'`."""
    # Minimal cite_records — actual data not relevant to the subtitle.
    png_bytes = bytes.fromhex(
        '89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489'
        '0000000D49444154789C636060000000000500015E2A24A30000000049454E44AE'
        '426082'
    )
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(png_bytes)
        png_path = Path(f.name)
    records = [{
        'cite_id': 1, 'kind': 'pdf',
        'spans': [{'page': 1, 'bbox': [10, 20, 30, 40]}],
        'marker_quote': 'q', 'claim_text': 'c', 'pdf_filename': 'd.pdf',
    }]
    html = build_inline_answer_html(
        answer_md='x [c](cite://1).',
        cite_records=records,
        image_paths={1: png_path},
        image_dims={1: (200, 100)},
    )
    # Default subtitle when no judge data: "1 cites validated" in .sub div.
    assert '<div class="sub">1 cites validated</div>' in html


def test_build_excerpt_html_asserts_quote_at_offset():
    """Wrong q_off must fail loudly, not produce silently-wrong HTML."""
    from groundling.answer_html_inline import _build_excerpt_html
    import pytest
    with pytest.raises(AssertionError):
        _build_excerpt_html("before quote after", "quote", q_off=0)
