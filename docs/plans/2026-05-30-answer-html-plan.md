# answer.html Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a third render output `answer.html` — a self-contained browser view of the answer with cite highlights, hover previews of the cited PDF region, and a click-opens-side-pane iframe to the existing `cites/N.html`.

**Architecture:** A new helper `groundling.answer_html.build_answer_html()` parses `answer.md` with `markdown-it-py`, finds `<a href="…/cites/N.html">` anchors, decorates each with `class="cite"` + `data-*` attributes from the matching `cite_record`, and wraps the result in a Jinja-rendered page shell containing styles, a side-pane `<aside>`, and ~20 lines of vanilla JS. Reuses the existing `cites/N.png` files as CSS-cropped background images for the hover preview — no new image generation.

**Tech Stack:** Python 3.11+, `markdown-it-py` (new), Jinja2 (existing), vanilla CSS + JS for the page itself.

**Design doc:** `docs/plans/2026-05-30-answer-html-design.md` — read before starting if any task is ambiguous.

---

## Reading the existing code

Before Task 1, read these files to ground your edits:

- `src/groundling/render_cmd.py` — `run_render()`. You'll add one call here in the final task. Note the `cite_records` list shape and the `_cite_url(web_base, run_dir, cite_id)` helper.
- `src/groundling/render.py` — see how `_build_highlights()` converts span bboxes to image-pixel rectangles. The same scale math applies here.
- `src/groundling/templates/cite_pdf.html.j2` — the cite page template the iframe will load. You're not modifying it; you're just embedding it.
- `tests/test_render_cmd.py` — see `_seeded_prep()` and `_chunk_id_from_prep()` helpers and the `text_pdf` fixture. New tests follow this pattern.

`cite_records` entries have the shape:
```python
{
    "marker": Marker(kind, quote, pdf_stem, chunk_id, url, wrap_kind, claim_text, ...),
    "cite_id": int,
    "kind": "pdf" | "web",
    "spans": [{"page": int, "bbox": [x0,y0,x1,y1]}, ...],    # only for pdf
    "pdf_path": Path,                                          # only for pdf
}
```

Image dimensions: at render time, the cite page image is `cites/<cite_id>.png` (or `cites/<owner_id>.png` when a same-page cite reused the image). Image natural width = `page.rect.width * scale`, height analogous, where `scale=2.0`. Bbox in image pixels = `bbox * scale`.

---

## Task 1: Add markdown-it-py dependency

**Files:**
- Modify: `pyproject.toml` (the `[project] dependencies` array)
- Run: `uv sync`

**Step 1: Add the dep**

Edit `pyproject.toml`'s dependencies array to include `"markdown-it-py>=3.0"`:

```toml
dependencies = [
  "anthropic>=0.40",
  "pymupdf>=1.24",
  "jinja2>=3.1",
  "typer>=0.12",
  "python-dotenv>=1.0",
  "markdown-it-py>=3.0",
]
```

**Step 2: Sync**

Run: `uv sync`
Expected: prints something like `+ markdown-it-py==3.x.x` and exits 0.

**Step 3: Verify import**

Run: `uv run python -c "import markdown_it; print(markdown_it.__version__)"`
Expected: prints a version like `3.0.0`, exits 0.

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add markdown-it-py dependency for answer.html rendering"
```

---

## Task 2: Compute per-cite image geometry helper

A pure function that turns a `cite_record` into the data attributes the HTML cite anchor needs. Isolated so tests can pin its math without mocking the page renderer.

**Files:**
- Create: `src/groundling/answer_html.py`
- Test: `tests/test_answer_html.py`

**Step 1: Write the failing test**

Create `tests/test_answer_html.py`:

```python
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
    assert attrs == {"data-cite-id": "3", "data-kind": "web"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_answer_html.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'groundling.answer_html'`.

**Step 3: Write minimal implementation**

Create `src/groundling/answer_html.py`:

```python
"""Build a browser-native answer view: answer.html.

Takes the validated cite records and the rewritten answer markdown
from run_render and emits a single self-contained HTML page with cite
highlights, hover previews of the cited PDF region, and a side-pane
iframe of the full cite page.
"""
from __future__ import annotations


def build_cite_attrs(
    cite_record: dict,
    *,
    image_filename: str | None,
    image_w_px: int | None,
    image_h_px: int | None,
    scale: float,
) -> dict[str, str]:
    """Compute the data-* attributes for one cite anchor.

    PDF cites get image + union-bbox geometry; web cites get just
    cite_id + kind. All bbox values are in image pixels (PDF points
    times scale)."""
    attrs = {
        "data-cite-id": str(cite_record["cite_id"]),
        "data-kind": cite_record["kind"],
    }
    if cite_record["kind"] != "pdf":
        return attrs

    # Union bbox across all spans (PDF points).
    spans = cite_record["spans"]
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)

    attrs["data-img"] = f"cites/{image_filename}"
    attrs["data-img-w"] = str(int(image_w_px))
    attrs["data-img-h"] = str(int(image_h_px))
    attrs["data-bx"] = str(int(x0 * scale))
    attrs["data-by"] = str(int(y0 * scale))
    attrs["data-bw"] = str(int((x1 - x0) * scale))
    attrs["data-bh"] = str(int((y1 - y0) * scale))
    return attrs
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_answer_html.py -v`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add src/groundling/answer_html.py tests/test_answer_html.py
git commit -m "feat(answer-html): cite attribute helper with union bbox math"
```

---

## Task 3: Markdown-to-HTML conversion + cite link decoration

Parse `answer.md` with `markdown-it-py`, find cite anchors by href pattern, inject `class="cite"` + data attributes + a child `<span class="preview">`.

**Files:**
- Modify: `src/groundling/answer_html.py`
- Modify: `tests/test_answer_html.py`

**Step 1: Write the failing tests**

Append to `tests/test_answer_html.py`:

```python
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
        web_base="http://localhost:8123",
        scale=2.0,
    )
    # The anchor exists with class="cite" and data attributes.
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html
    assert 'data-kind="pdf"' in html
    assert 'data-img="cites/1.png"' in html
    assert 'data-bx="20"' in html
    # The child preview span is there.
    assert '<span class="preview"></span>' in html
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
        web_base="http://localhost:8123",
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
        web_base="http://localhost:8123", scale=2.0,
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
        web_base="http://localhost:8123", scale=2.0,
    )
    assert 'class="cite"' not in html
    assert 'href="https://example.com/docs"' in html


def test_decorate_answer_html_file_url_base():
    """Default web_base is file://. Cite anchors come out as
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
        web_base="file:///tmp/qa-runs", scale=2.0,
    )
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_answer_html.py -v`
Expected: 5 new tests FAIL with `ImportError: cannot import name 'decorate_answer_html'`. (Existing 3 still pass.)

**Step 3: Implement decorate_answer_html**

Append to `src/groundling/answer_html.py`:

```python
import re

from markdown_it import MarkdownIt


def _cite_id_from_href(
    href: str,
    *,
    run_dir_name: str,
) -> int | None:
    """Extract cite_id from a `…/<run_dir_name>/cites/N.html` href.
    Returns None if href doesn't match the cite URL pattern."""
    m = re.search(
        rf"/{re.escape(run_dir_name)}/cites/(\d+)\.html$", href,
    )
    return int(m.group(1)) if m else None


def decorate_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_dims: dict[int, tuple[str, int, int]],
    run_dir_name: str,
    web_base: str,
    scale: float,
) -> str:
    """Render answer_md to HTML and decorate cite anchors with
    `class="cite"` + data-* attributes + a child <span class="preview">.

    Non-cite links (any other href) are left untouched.

    image_dims maps cite_id -> (image_filename, image_w_px, image_h_px)
    for PDF cites. Web cites are absent."""
    records_by_id = {r["cite_id"]: r for r in cite_records}

    md = MarkdownIt("commonmark").enable("table")
    html = md.render(answer_md)

    # Walk anchors via regex. The HTML markdown-it emits is well-formed
    # enough that a single non-greedy <a …>…</a> regex catches every
    # link cleanly. We rewrite each anchor in place.
    anchor_re = re.compile(
        r'<a\s+href="([^"]+)"([^>]*)>(.*?)</a>',
        re.DOTALL,
    )

    def _replace(m: re.Match) -> str:
        href, rest, inner = m.group(1), m.group(2), m.group(3)
        cite_id = _cite_id_from_href(href, run_dir_name=run_dir_name)
        if cite_id is None or cite_id not in records_by_id:
            return m.group(0)  # not a cite link — leave alone

        record = records_by_id[cite_id]
        if record["kind"] == "pdf":
            image_filename, image_w_px, image_h_px = image_dims[cite_id]
        else:
            image_filename, image_w_px, image_h_px = None, None, None

        attrs = build_cite_attrs(
            record,
            image_filename=image_filename,
            image_w_px=image_w_px,
            image_h_px=image_h_px,
            scale=scale,
        )
        attrs_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        return (
            f'<a class="cite" href="{href}"{rest} {attrs_str}>'
            f'{inner}<span class="preview"></span></a>'
        )

    return anchor_re.sub(_replace, html)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_answer_html.py -v`
Expected: 8 passed (3 from Task 2 + 5 from Task 3).

**Step 5: Commit**

```bash
git add src/groundling/answer_html.py tests/test_answer_html.py
git commit -m "feat(answer-html): markdown→html with cite anchor decoration"
```

---

## Task 4: Page template (styles + body shell + JS)

A Jinja template that wraps the decorated answer HTML in a full page: styles for cite highlights, hover preview, side pane; the side-pane `<aside>` markup; and the click-handler JS. Pure CSS for hover, vanilla JS for click.

**Files:**
- Create: `src/groundling/templates/answer.html.j2`
- Modify: `src/groundling/answer_html.py` (add `build_answer_html()` that uses the template)
- Modify: `tests/test_answer_html.py`

**Step 1: Write the failing test**

Append to `tests/test_answer_html.py`:

```python
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
        web_base="http://localhost:8123",
        scale=2.0,
    )
    # Doctype + page shell.
    assert html.startswith("<!doctype html>") or html.startswith("<!DOCTYPE html>")
    # Decorated cite anchor.
    assert 'class="cite"' in html
    # Side pane markup.
    assert '<aside class="cite-pane"' in html
    assert '<iframe' in html
    # JS hooks: hover-capability check + pane-open class.
    assert "(hover: hover)" in html
    assert "pane-open" in html
    # Cite highlight CSS — at least the background colour rule.
    assert ".cite" in html
    # Preview popover CSS.
    assert ".preview" in html
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_answer_html.py::test_build_answer_html_emits_full_page -v`
Expected: FAIL with `ImportError: cannot import name 'build_answer_html'`.

**Step 3: Create the template**

Create `src/groundling/templates/answer.html.j2`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Answer</title>
<style>
  body { font: 16px/1.55 system-ui, sans-serif; color: #222; margin: 0; display: flex; }
  main.answer { flex: 1 1 auto; padding: 32px 40px; max-width: 760px; transition: flex-basis 0.2s, max-width 0.2s; }
  body.pane-open main.answer { flex: 0 0 60%; max-width: none; }
  body.pane-open aside.cite-pane { display: flex; }

  main.answer h1, main.answer h2, main.answer h3 { line-height: 1.25; }
  main.answer p { margin: 0.8em 0; }
  main.answer ul, main.answer ol { padding-left: 1.4em; }

  a.cite {
    background: #fff7c2;
    border-bottom: 1px solid #e0c000;
    text-decoration: none;
    color: inherit;
    padding: 0 2px;
    position: relative;
    cursor: pointer;
  }
  a.cite:hover { background: #ffeb80; }

  /* Hover preview popover. PDF cites use the page image as a CSS
     background, positioned so the bbox centre sits at the popover
     centre. Web cites get a quote-only card via a separate rule. */
  a.cite .preview {
    display: none;
    position: absolute;
    bottom: 1.6em;
    left: 0;
    width: 480px;
    height: 280px;
    border: 1px solid #bbb;
    box-shadow: 0 6px 24px rgba(0,0,0,0.2);
    background-color: #fff;
    background-repeat: no-repeat;
    z-index: 100;
    overflow: hidden;
    border-radius: 4px;
  }
  a.cite:hover .preview { display: block; }
  a.cite[data-kind="pdf"] .preview {
    background-image: var(--img);
    background-size: var(--img-w) var(--img-h);
    background-position:
      calc(240px - var(--bx) - var(--bw) / 2)
      calc(140px - var(--by) - var(--bh) / 2);
  }
  a.cite[data-kind="pdf"] .preview::after {
    content: "";
    position: absolute;
    left: calc(240px - var(--bw) / 2);
    top:  calc(140px - var(--bh) / 2);
    width: var(--bw);
    height: var(--bh);
    background: rgba(255, 235, 0, 0.35);
    border: 1px solid rgba(200, 160, 0, 0.6);
  }

  aside.cite-pane {
    display: none;
    flex: 0 0 40%;
    border-left: 1px solid #ddd;
    background: #fafafa;
    position: relative;
    height: 100vh;
    position: sticky;
    top: 0;
  }
  aside.cite-pane iframe {
    width: 100%; height: 100%; border: 0;
  }
  aside.cite-pane .close {
    position: absolute; top: 8px; right: 12px;
    background: #fff; border: 1px solid #ccc; border-radius: 4px;
    width: 28px; height: 28px; cursor: pointer;
    font-size: 18px; line-height: 1; padding: 0;
    z-index: 10;
  }
  aside.cite-pane .close:hover { background: #eee; }

  @media (hover: none) {
    a.cite .preview { display: none !important; }
  }
  @media (max-width: 700px) {
    body.pane-open main.answer { flex: 1 1 auto; }
    body.pane-open aside.cite-pane { display: none; }
  }
</style>
</head>
<body>
<main class="answer">
{{ answer_html | safe }}
</main>
<aside class="cite-pane" hidden>
  <button class="close" aria-label="Close">×</button>
  <iframe src="about:blank" title="Cite source"></iframe>
</aside>
<script>
  (function () {
    const pane = document.querySelector('aside.cite-pane');
    const iframe = pane.querySelector('iframe');
    const closeBtn = pane.querySelector('.close');

    // Inject per-cite CSS custom props from data-* (the page-image url
    // can't sit in static CSS, and CSS calc() math needs the geometry
    // as CSS units).
    document.querySelectorAll('a.cite[data-kind="pdf"]').forEach(a => {
      a.style.setProperty('--img', `url("${a.dataset.img}")`);
      a.style.setProperty('--img-w', a.dataset.imgW + 'px');
      a.style.setProperty('--img-h', a.dataset.imgH + 'px');
      a.style.setProperty('--bx', a.dataset.bx + 'px');
      a.style.setProperty('--by', a.dataset.by + 'px');
      a.style.setProperty('--bw', a.dataset.bw + 'px');
      a.style.setProperty('--bh', a.dataset.bh + 'px');
    });

    document.querySelectorAll('a.cite').forEach(a => {
      a.addEventListener('click', e => {
        if (!window.matchMedia('(hover: hover)').matches) return;
        e.preventDefault();
        iframe.src = a.getAttribute('href');
        pane.hidden = false;
        document.body.classList.add('pane-open');
      });
    });

    closeBtn.addEventListener('click', () => {
      pane.hidden = true;
      iframe.src = 'about:blank';
      document.body.classList.remove('pane-open');
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !pane.hidden) closeBtn.click();
    });
  })();
</script>
</body>
</html>
```

**Step 4: Implement build_answer_html**

Append to `src/groundling/answer_html.py`:

```python
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def build_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_dims: dict[int, tuple[str, int, int]],
    run_dir_name: str,
    web_base: str,
    scale: float = 2.0,
) -> str:
    """Build the full answer.html page from the rewritten markdown.

    Returns a self-contained HTML string. Cite anchors are decorated
    for hover preview + click-to-side-pane behaviour."""
    answer_html = decorate_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name=run_dir_name,
        web_base=web_base,
        scale=scale,
    )
    template = _env.get_template("answer.html.j2")
    return template.render(answer_html=answer_html)
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_answer_html.py -v`
Expected: 9 passed.

**Step 6: Commit**

```bash
git add src/groundling/answer_html.py src/groundling/templates/answer.html.j2 tests/test_answer_html.py
git commit -m "feat(answer-html): page template with hover preview + side pane"
```

---

## Task 5: Wire build_answer_html into run_render

Call the helper from `run_render` after `answer.md` is written, passing the same data already in scope. Build `image_dims` from the rendered cite pages.

**Files:**
- Modify: `src/groundling/render_cmd.py` — after `(run_dir / "answer.md").write_text(...)` block
- Test: `tests/test_render_cmd.py` — end-to-end assertion that `answer.html` exists with the right shape

**Step 1: Write the failing end-to-end test**

Append to `tests/test_render_cmd.py`:

```python
def test_run_render_writes_answer_html_with_cite_decoration(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [the opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123",
    )
    html_path = result.run_dir / "answer.html"
    assert html_path.exists()
    html = html_path.read_text()
    # Page shell.
    assert "<!doctype html>" in html or "<!DOCTYPE html>" in html
    assert '<aside class="cite-pane"' in html
    # Cite decoration arrived through the full pipeline.
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html
    assert 'data-kind="pdf"' in html
    assert 'data-img="cites/1.png"' in html
    # Mobile fall-through media query.
    assert "(hover: hover)" in html


def test_run_render_answer_html_handles_zero_cites(tmp_path, text_pdf):
    """No cites → answer.html still exists, just plain prose."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    result = run_render(
        prep_dir=prep_dir, answer_md="no cites here.", state_dir=None,
    )
    html_path = result.run_dir / "answer.html"
    assert html_path.exists()
    html = html_path.read_text()
    assert 'class="cite"' not in html
    # Page shell still present.
    assert '<aside class="cite-pane"' in html
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_cmd.py::test_run_render_writes_answer_html_with_cite_decoration -v`
Expected: FAIL — `answer.html` doesn't exist.

**Step 3: Wire it up in run_render**

In `src/groundling/render_cmd.py`, after the line:

```python
(run_dir / "answer.md").write_text(out, encoding="utf-8")
```

add the following block (still inside `run_render`):

```python
    # Also emit answer.html — browser view with hover preview + side
    # pane. Build image_dims from the cite records we already validated.
    import fitz
    from groundling.answer_html import build_answer_html

    image_dims: dict[int, tuple[str, int, int]] = {}
    page_dims_cache: dict[tuple[Path, int], tuple[int, int]] = {}
    for rec in cite_records:
        if rec["kind"] != "pdf":
            continue
        cid = rec["cite_id"]
        page = rec["spans"][0]["page"]
        # Determine which N.png this cite uses (may be a dedupe owner's).
        key = (rec["pdf_path"], page)
        owner = rendered_pages.get(key, cid)
        image_filename = f"{owner}.png"
        # Cache page dims by (pdf_path, page).
        if key not in page_dims_cache:
            with fitz.open(rec["pdf_path"]) as doc:
                p = doc.load_page(page - 1)
                page_dims_cache[key] = (
                    int(p.rect.width * 2.0),
                    int(p.rect.height * 2.0),
                )
        w_px, h_px = page_dims_cache[key]
        image_dims[cid] = (image_filename, w_px, h_px)

    answer_html = build_answer_html(
        answer_md=out,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name=run_dir.name,
        web_base=web_base,
        scale=2.0,
    )
    (run_dir / "answer.html").write_text(answer_html, encoding="utf-8")
```

Note: `rendered_pages` and `cite_records` and `out` are already defined earlier in `run_render`. The scale `2.0` matches `render_pdf_page`'s default. `web_base` and `run_dir` are parameters in scope.

**Step 4: Run the new tests**

Run: `uv run pytest tests/test_render_cmd.py -v`
Expected: all pass (existing + 2 new).

**Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass — no regressions in the rest of the suite.

**Step 6: Commit**

```bash
git add src/groundling/render_cmd.py tests/test_render_cmd.py
git commit -m "feat(render): emit answer.html alongside answer.md"
```

---

## Task 6: AGENTS.md note

One short addition so a fresh Claude Code session knows the file exists.

**Files:**
- Modify: `AGENTS.md` — under "Step 3: render"

**Step 1: Add the note**

Find the section under `### Step 3: render` in `AGENTS.md` and append after the existing paragraphs (before the `---` separator):

```
For browser viewing, the run dir also contains `answer.html` — a
self-contained page with cite highlights, hover preview of the
cited PDF region, and a click-opens-side-pane iframe of the full
cite page. Serve it via `groundling serve` and open
`http://127.0.0.1:8123/<run_id>/answer.html`.
```

**Step 2: Verify no test references AGENTS.md content**

Run: `uv run pytest -q`
Expected: all pass.

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): mention answer.html browser view in render step"
```

---

## Task 7: End-to-end smoke against the live BYD run

Validate the feature in the wild using the existing render run from
the wrapping-cites experiment.

**Files:** none modified — this is a manual verification step.

**Step 1: Re-render the BYD answer to materialise answer.html**

```bash
cat /tmp/wrapping-test-answer.md | \
  uv run groundling render \
    /tmp/grounded-qa-e2e/.groundling-prep/2026-05-30T18-28-33 \
    --answer - \
    --web-base http://127.0.0.1:8123
```

Expected: stdout shows the rewritten markdown; stderr shows `validated=9 invalid_chunk=0 invalid_quote=0 invalid_url=0`. A new run dir appears under `/tmp/grounded-qa-e2e/qa-runs/`.

**Step 2: Confirm answer.html exists in that run dir**

```bash
ls /tmp/grounded-qa-e2e/qa-runs/ | tail -1
# then:
ls /tmp/grounded-qa-e2e/qa-runs/<latest>/
```

Expected: `answer.html` is present alongside `answer.md`.

**Step 3: Curl-check it's served**

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  "http://127.0.0.1:8123/<latest-run-id>/answer.html"
```

Expected: `HTTP 200`.

**Step 4: Visually verify in browser**

Open `http://127.0.0.1:8123/<latest-run-id>/answer.html`. Confirm:
- Cite spans appear with soft yellow background.
- Hovering a cite shows a popover with the PDF region + yellow highlight.
- Clicking a cite opens the side pane with the full cite page.
- Pressing Escape closes the pane.

Report any issues. If everything works, the feature is done.

No commit for this task — it's verification.

---

## Out of scope (file as follow-ups if needed)

- Inline PDF embedding via `<embed>` instead of a CSS-cropped PNG.
- Multi-document split view (one iframe per cite source side-by-side).
- Print stylesheet — answer.html as PDF-via-print.
- Dark mode.
- Reference appendix styling: today, point-marker answers carry a
  reference appendix at the bottom (`[1]: http://...`). It currently
  renders as plain list-style links. Could be hidden in answer.html
  since cites are already inline-clickable. Punt for now.
