"""build_cite_attrs() unit tests — pure function, no fixtures needed."""
from __future__ import annotations

from groundling.answer_html import build_cite_attrs


def test_build_cite_attrs_pdf_single_span():
    cite_record = {
        "cite_id": 1,
        "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    }
    attrs = build_cite_attrs(
        cite_record, image_filename="1.png", image_w_px=1240, image_h_px=1754,
        scale=2.0,
    )
    assert attrs == {
        "data-cite-id": "1",
        "data-kind": "pdf",
        "data-state": "none",  # PR 2 overrides per verdicts.json.
        "data-img": "cites/1.png",
        "data-img-w": "1240",
        "data-img-h": "1754",
        "data-bx": "20",       # 10.0 * 2.0
        "data-by": "40",       # 20.0 * 2.0
        "data-bw": "40",       # (30-10) * 2.0
        "data-bh": "40",       # (40-20) * 2.0
    }


def test_build_cite_attrs_pdf_multi_span_uses_union_bbox():
    """Multi-span cite: union bbox spans from leftmost-topmost to
    rightmost-bottommost word, in image pixels."""
    cite_record = {
        "cite_id": 2,
        "kind": "pdf",
        "spans": [
            {"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]},
            {"page": 1, "bbox": [50.0, 25.0, 80.0, 45.0]},
            {"page": 1, "bbox": [12.0, 22.0, 28.0, 38.0]},
        ],
    }
    attrs = build_cite_attrs(
        cite_record, image_filename="2.png", image_w_px=1240, image_h_px=1754,
        scale=2.0,
    )
    # Union bbox in PDF pts: x0=10, y0=20, x1=80, y1=45
    # Scaled 2x: bx=20, by=40, bw=(80-10)*2=140, bh=(45-20)*2=50
    assert attrs["data-bx"] == "20"
    assert attrs["data-by"] == "40"
    assert attrs["data-bw"] == "140"
    assert attrs["data-bh"] == "50"


def test_build_cite_attrs_web():
    cite_record = {"cite_id": 3, "kind": "web"}
    attrs = build_cite_attrs(
        cite_record, image_filename=None, image_w_px=None, image_h_px=None,
        scale=2.0,
    )
    assert attrs == {
        "data-cite-id": "3",
        "data-kind": "web",
        "data-state": "none",
    }


def test_build_cite_attrs_web_with_url():
    """Web cites with a url field surface it as data-url so the run-dir
    hover card can show the real URL instead of a generic label."""
    cite_record = {
        "cite_id": 4,
        "kind": "web",
        "url": "https://example.com/article",
    }
    attrs = build_cite_attrs(
        cite_record, image_filename=None, image_w_px=None, image_h_px=None,
        scale=2.0,
    )
    assert attrs == {
        "data-cite-id": "4",
        "data-kind": "web",
        "data-state": "none",
        "data-url": "https://example.com/article",
    }


import re
from pathlib import Path

from groundling.answer_html import decorate_answer_html


def _records(*items) -> list[dict]:
    return list(items)


def test_decorate_answer_html_wrap_cite_decorated():
    answer_md = (
        'See [the revenue figure]'
        '(http://localhost:8123/run-x/cites/1.html "170,360,448,000.00") here.'
    )
    cite_records = _records({
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    })
    image_dims = {1: ("1.png", 1240, 1754)}
    html = decorate_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name="run-x",
        scale=2.0,
    )
    # The anchor exists with class="cite" and data attributes.
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html
    assert 'data-kind="pdf"' in html
    assert 'data-state="none"' in html
    assert 'data-img="cites/1.png"' in html
    assert 'data-bx="20"' in html
    # The dormant preview span has been removed from decorate output.
    assert 'class="preview"' not in html
    # The link text survives.
    assert ">the revenue figure<" in html


def test_decorate_answer_html_point_marker_decorated():
    """Point markers get rewritten by run_render to [N](href) in the
    appendix style. decorate_answer_html should handle that shape too —
    the [N] link text and the anchor href both come from run_render."""
    answer_md = (
        'See [1] for the figure.\n\n'
        '[1]: http://localhost:8123/run-x/cites/1.html\n'
    )
    cite_records = _records({
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    })
    image_dims = {1: ("1.png", 1240, 1754)}
    html = decorate_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name="run-x",
        scale=2.0,
    )
    # The reference-style [1] becomes an <a> via markdown-it; we should
    # find it decorated.
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html


def test_decorate_answer_html_web_cite_no_image_attrs():
    answer_md = (
        '[from the news](http://localhost:8123/run-x/cites/1.html "the quote") here.'
    )
    cite_records = _records({"cite_id": 1, "kind": "web"})
    html = decorate_answer_html(
        answer_md=answer_md, cite_records=cite_records,
        image_dims={},  # web cites have no image
        run_dir_name="run-x",
        scale=2.0,
    )
    assert 'data-kind="web"' in html
    assert 'data-img=' not in html
    assert 'data-bx=' not in html


def test_decorate_answer_html_non_cite_links_untouched():
    answer_md = 'See [the docs](https://example.com/docs) for details.'
    html = decorate_answer_html(
        answer_md=answer_md, cite_records=[],
        image_dims={},
        run_dir_name="run-x",
        scale=2.0,
    )
    assert 'class="cite"' not in html
    assert 'href="https://example.com/docs"' in html


def test_decorate_answer_html_file_url_base():
    """When the run_render base is file://, cite anchors come out as
    file://<abs>/run-x/cites/1.html. The matcher should handle both
    schemes."""
    answer_md = (
        '[claim](file:///tmp/qa-runs/run-x/cites/1.html "quote")'
    )
    cite_records = _records({
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    })
    image_dims = {1: ("1.png", 1240, 1754)}
    html = decorate_answer_html(
        answer_md=answer_md, cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name="run-x",
        scale=2.0,
    )
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html


from groundling.answer_html import build_answer_html


def test_build_answer_html_emits_full_page():
    answer_md = (
        '[claim](http://localhost:8123/run-x/cites/1.html "q")'
    )
    cite_records = _records({
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    })
    image_dims = {1: ("1.png", 1240, 1754)}
    html = build_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name="run-x",
        scale=2.0,
    )
    # Doctype + page shell.
    assert html.startswith("<!doctype html>") or html.startswith("<!DOCTYPE html>")
    # Trust strip with brand + cite tally.
    assert 'class="trustbar"' in html
    assert '<b>1</b> cites validated' in html
    # Spotlight toggle ABSENT in PR 1 (has_judge_data=False).
    assert 'id="weakBtn"' not in html
    # Hover card element exists.
    assert 'id="card"' in html
    # Modal + iframe (replacing the old side pane).
    assert 'id="modal"' in html
    assert 'id="modalFrame"' in html
    # Mobile-fallthrough media query still gates the modal-click path.
    assert "(hover: hover)" in html
    # Decorated cite anchor with data-state="none" default.
    assert 'class="cite"' in html
    assert 'data-state="none"' in html
    assert 'data-cite-id="1"' in html
    # Dormant preview span is gone.
    assert 'class="preview"' not in html


def test_build_answer_html_renders_page_title_and_subtitle():
    """When page_title and subtitle are passed, they appear in the h1
    and .sub div respectively."""
    html = build_answer_html(
        answer_md='hello',
        cite_records=[],
        image_dims={},
        run_dir_name='test',
        page_title='What does the doc say?',
        subtitle='Custom subtitle here',
    )
    assert '<h1>What does the doc say?</h1>' in html
    assert '<div class="sub">Custom subtitle here</div>' in html


def test_build_answer_html_default_subtitle_zero_cites():
    """When subtitle is None and there are zero cites, the .sub div is
    empty (no subtitle text rendered)."""
    html = build_answer_html(
        answer_md='hello',
        cite_records=[],
        image_dims={},
        run_dir_name='test',
    )
    # Empty subtitle should NOT emit a .sub div (it's gated on a truthy
    # subtitle in the template).
    assert '<div class="sub">' not in html


def test_build_answer_html_default_subtitle_with_cites():
    """When subtitle is None but there are cites, the default
    'N cites validated' subtitle is rendered."""
    cite_records = _records({
        "cite_id": 1, "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    })
    html = build_answer_html(
        answer_md='[claim](http://localhost:8123/run-x/cites/1.html "q")',
        cite_records=cite_records,
        image_dims={1: ("1.png", 1240, 1754)},
        run_dir_name='run-x',
    )
    assert '<div class="sub">1 cites validated</div>' in html


def test_build_answer_html_web_cite_emits_data_url():
    """Web cites with a url surface it as data-url on the anchor so
    the hover card can show the real URL."""
    answer_md = (
        '[news](http://localhost:8123/run-x/cites/1.html "the quote")'
    )
    cite_records = _records({
        "cite_id": 1, "kind": "web", "url": "https://example.com/story",
    })
    html = build_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims={},
        run_dir_name='run-x',
    )
    assert 'data-url="https://example.com/story"' in html
