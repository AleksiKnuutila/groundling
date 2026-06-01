# groundling → Claude.ai Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package groundling as a self-contained Claude.ai Skill (zip uploadable via Settings > Features > Skills) so the user can ground PDF Q&A in their browser without needing pipx or any local install. Pattern B from the design discussion — wheels bundled in the skill zip, idempotent `pip install --no-index` at runtime, works in any network setting.

**Architecture:** A new top-level `skill/` directory in the repo holds the skill artifact. The skill bundles the groundling wheel itself + its runtime deps (pymupdf, markdown-it-py, jinja2, pillow) in `skill/wheels/`. Skill scripts (`bootstrap.py`, `prep.py`, `render.py`) wrap groundling's existing modules. A new `groundling.answer_html_inline` module produces a single-file self-contained HTML (base64-inlined PNGs + inline `<dialog>` for cite content, no relative-path multi-file output). `SKILL.md` is the workflow checklist; `reference.md` is level-2 script-API detail loaded on demand.

**Tech Stack:** Python 3.11+ (matches sandbox Python), `uv pip download` for wheel collection, the existing groundling chunker / marker / render code reused unchanged, Pillow for base64 image encoding, sentinel-file pattern for idempotent bootstrap.

**Design discussion + research:** Brainstorm in conversation history; research on skill conventions confirmed:
- Anthropic-built skills (PDF, xlsx, web-artifacts-builder) use `SKILL.md` + `scripts/` + optional `reference.md`. No skill currently bundles wheels — we're paving new ground.
- SKILL.md should be under 500 lines; description third-person + trigger-rich + explicit negatives.
- Progressive disclosure ONE LEVEL DEEP — reference.md loaded from SKILL.md, no nesting.
- Anti-patterns to avoid: first-person description, listing many library choices, punting errors to Claude, time-sensitive phrasing, nested references.

---

## Reading the existing code

Before Task 1, skim these:

- `src/groundling/answer_html.py` — current decorate + build pipeline. The new inline module reuses `decorate_answer_html`, just changes how the output gets wrapped.
- `src/groundling/render_cmd.py` — writes multi-file output to `run_dir/`. The skill render does the same chunking + validation but writes a single answer.html.
- `src/groundling/render.py` — `render_pdf_page()` is the rasterizer we reuse for cite images.
- `src/groundling/markers.py` — `parse_markers()` + `resolve_marker_to_spans()` validate the marker contract; unchanged for skill use.
- `src/groundling/templates/answer.html.j2` — current page shell. The inline variant uses a new template (`answer_inline.html.j2`) but most CSS/JS stays similar.
- `src/groundling/prep.py` — has `linearize_chunks()` we reuse in skill prep.

---

## Task 1: Self-contained inline answer.html generator

A new module produces a single HTML file with everything inlined. Reuses `decorate_answer_html` patterns; replaces the page template and the side-pane mechanism.

**Files:**
- Create: `src/groundling/answer_html_inline.py`
- Create: `src/groundling/templates/answer_inline.html.j2`
- Test: `tests/test_answer_html_inline.py`

**Step 1: Write the failing tests**

Create `tests/test_answer_html_inline.py`:

```python
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
        cite_records=cite_records, image_paths=image_paths, scale=2.0,
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
        cite_records=cite_records, image_paths={1: fake_png}, scale=2.0,
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
        cite_records=cite_records, image_paths={}, scale=2.0,
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
        cite_records=cite_records, image_paths={1: fake_png}, scale=2.0,
    )
    assert len(html) < 50_000
```

**Step 2: Verify tests fail**

Run: `uv run pytest tests/test_answer_html_inline.py -v`
Expected: 4 FAIL with `ModuleNotFoundError`.

**Step 3: Implement the module**

Create `src/groundling/answer_html_inline.py`:

```python
"""Single-file self-contained answer.html for Claude.ai skill use.

Differences from answer_html.py:
- PNGs base64-inlined as data: URIs (no cites/N.png files)
- Cite content in inline <dialog> elements (no iframe)
- Renders standalone — open the .html in a browser, no server needed
"""
from __future__ import annotations

import base64
import html as html_lib
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from PIL import Image

from groundling.answer_html import build_cite_attrs


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "j2")),
)


def _png_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_inline_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_paths: dict[int, Path],
    scale: float = 2.0,
) -> str:
    """Build a single self-contained HTML file.

    cite_records entries must include:
      - cite_id, kind ("pdf" or "web"), spans (for pdf)
      - marker_quote: verbatim cited text
      - claim_text: agent's claim wrapping the cite (or None)
      - pdf_filename (for pdf) or url (for web)

    image_paths maps cite_id -> Path to PDF page PNG; base64-inlined.
    answer_md uses cite://N as href scheme (rewritten upstream).
    """
    inline_cites = []
    for rec in cite_records:
        cid = rec["cite_id"]
        if rec["kind"] == "pdf":
            data_uri = _png_to_data_uri(image_paths[cid])
            x0 = min(s["bbox"][0] for s in rec["spans"])
            y0 = min(s["bbox"][1] for s in rec["spans"])
            x1 = max(s["bbox"][2] for s in rec["spans"])
            y1 = max(s["bbox"][3] for s in rec["spans"])
            inline_cites.append({
                "cite_id": cid, "kind": "pdf", "data_uri": data_uri,
                "bx": int(x0 * scale), "by": int(y0 * scale),
                "bw": int((x1 - x0) * scale), "bh": int((y1 - y0) * scale),
                "quote": rec["marker_quote"],
                "claim": rec.get("claim_text") or "",
                "filename": rec.get("pdf_filename", ""),
                "page": rec["spans"][0]["page"],
            })
        else:
            inline_cites.append({
                "cite_id": cid, "kind": "web",
                "url": rec["url"],
                "quote": rec["marker_quote"],
                "claim": rec.get("claim_text") or "",
            })

    decorated_body = _decorate_for_inline(
        answer_md, cite_records, image_paths=image_paths, scale=scale,
    )
    template = _env.get_template("answer_inline.html.j2")
    return template.render(
        answer_html=decorated_body, inline_cites=inline_cites,
    )


def _decorate_for_inline(
    answer_md, cite_records, *, image_paths, scale,
):
    """Render markdown to HTML; decorate cite anchors with data-* attrs
    and rewrite cite://N hrefs to #cite-N in-page anchors."""
    md = MarkdownIt("commonmark").enable("table")
    md.validateLink = lambda url: True
    rendered = md.render(answer_md)

    records_by_id = {r["cite_id"]: r for r in cite_records}
    anchor_re = re.compile(
        r'<a\s+href="cite://(\d+)"([^>]*)>(.*?)</a>', re.DOTALL,
    )

    def _replace(m):
        cid = int(m.group(1))
        rest, inner = m.group(2), m.group(3)
        rec = records_by_id.get(cid)
        if rec is None:
            return m.group(0)
        if rec["kind"] == "pdf":
            with Image.open(image_paths[cid]) as img:
                image_w, image_h = img.width, img.height
            attrs = build_cite_attrs(
                {"cite_id": cid, "kind": "pdf", "spans": rec["spans"]},
                image_filename=f"_inline_{cid}",
                image_w_px=image_w, image_h_px=image_h, scale=scale,
            )
            attrs["data-img"] = _png_to_data_uri(image_paths[cid])
        else:
            attrs = build_cite_attrs(
                {"cite_id": cid, "kind": "web"},
                image_filename=None, image_w_px=None,
                image_h_px=None, scale=scale,
            )
        attrs_str = " ".join(
            f'{k}="{html_lib.escape(v, quote=True)}"'
            for k, v in attrs.items()
        )
        return (
            f'<a class="cite" href="#cite-{cid}"{rest} {attrs_str}>'
            f'{inner}<span class="preview"></span></a>'
        )

    return anchor_re.sub(_replace, rendered)
```

**Step 4: Create the inline template**

Create `src/groundling/templates/answer_inline.html.j2`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grounded Answer</title>
<style>
  body { font: 16px/1.55 system-ui, sans-serif; color: #222; margin: 0; }
  main.answer { padding: 32px 40px; max-width: 760px; margin: 0 auto; }
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

  a.cite .preview {
    display: none;
    position: absolute;
    bottom: 1.6em; left: 0;
    width: 480px; height: 280px;
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
    width: var(--bw); height: var(--bh);
    background: rgba(255, 235, 0, 0.35);
    border: 1px solid rgba(200, 160, 0, 0.6);
  }

  dialog.cite-detail {
    border: 1px solid #ccc;
    border-radius: 6px;
    padding: 16px;
    max-width: 80vw;
    max-height: 80vh;
    overflow: auto;
  }
  dialog.cite-detail .pdf-image {
    position: relative;
    display: inline-block;
  }
  dialog.cite-detail img { display: block; max-width: 100%; }
  dialog.cite-detail .highlight {
    position: absolute;
    background: rgba(255, 235, 0, 0.35);
    border: 1px solid rgba(200, 160, 0, 0.6);
    pointer-events: none;
  }
  dialog.cite-detail .quote {
    border-left: 3px solid #ccc;
    background: #fafafa;
    padding: 8px 12px;
    margin: 12px 0;
  }
  dialog.cite-detail .source { opacity: 0.6; font-size: 12px; }
  dialog.cite-detail .close-btn {
    position: absolute; top: 8px; right: 12px;
    background: #fff; border: 1px solid #ccc; border-radius: 4px;
    width: 28px; height: 28px; cursor: pointer;
  }

  @media (hover: none) { a.cite .preview { display: none !important; } }
</style>
</head>
<body>
<main class="answer">
{{ answer_html | safe }}
</main>

{% for cite in inline_cites %}
<dialog class="cite-detail" id="cite-{{ cite.cite_id }}-detail" data-cite-id="{{ cite.cite_id }}">
  <button class="close-btn" aria-label="Close">×</button>
  {% if cite.kind == "pdf" %}
  <h3>Cite {{ cite.cite_id }} — {{ cite.filename }} (page {{ cite.page }})</h3>
  {% if cite.claim %}<div class="quote"><strong>Claim:</strong> {{ cite.claim }}</div>{% endif %}
  <div class="quote"><strong>Quote:</strong> {{ cite.quote }}</div>
  <div class="pdf-image">
    <img src="{{ cite.data_uri }}" alt="page {{ cite.page }}">
    <div class="highlight" style="left: {{ cite.bx }}px; top: {{ cite.by }}px; width: {{ cite.bw }}px; height: {{ cite.bh }}px;"></div>
  </div>
  {% else %}
  <h3>Cite {{ cite.cite_id }} — Web</h3>
  {% if cite.claim %}<div class="quote"><strong>Claim:</strong> {{ cite.claim }}</div>{% endif %}
  <div class="quote"><strong>Quote:</strong> {{ cite.quote }}</div>
  <p class="source"><a href="{{ cite.url }}" target="_blank" rel="noopener">{{ cite.url }}</a></p>
  {% endif %}
</dialog>
{% endfor %}

<script>
  (function () {
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
        const cid = a.dataset.citeId;
        const dlg = document.getElementById(`cite-${cid}-detail`);
        if (dlg) { e.preventDefault(); dlg.showModal(); }
      });
    });
    document.querySelectorAll('dialog.cite-detail .close-btn').forEach(btn => {
      btn.addEventListener('click', () => btn.closest('dialog').close());
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        document.querySelectorAll('dialog[open]').forEach(d => d.close());
      }
    });
  })();
</script>
</body>
</html>
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_answer_html_inline.py -v`
Expected: 4 passed.

**Step 6: Full suite**

Run: `uv run pytest -q`
Expected: 145 + 4 = 149 passing.

**Step 7: Commit**

```bash
git add src/groundling/answer_html_inline.py \
        src/groundling/templates/answer_inline.html.j2 \
        tests/test_answer_html_inline.py
git commit -m "feat(skill): self-contained inline answer.html generator"
```

---

## Task 2: Skill directory scaffolding

**Files:**
- Create: `skill/SKILL.md` (placeholder; Task 7 writes the real content)
- Create: `skill/reference.md` (placeholder; Task 7)
- Create: `skill/LICENSE.txt` (copy of repo's license if present, else placeholder)
- Create: `skill/scripts/.gitkeep`
- Create: `skill/wheels/.gitkeep`
- Modify: `.gitignore` (add `skill/wheels/*.whl` and `skill/dist/`)

**Step 1: Create structure**

```bash
mkdir -p skill/scripts skill/wheels
touch skill/scripts/.gitkeep skill/wheels/.gitkeep
cat > skill/SKILL.md <<'MD'
---
name: groundling
description: Placeholder — replaced by Task 7.
---
# Placeholder
MD
cat > skill/reference.md <<'MD'
# Placeholder — replaced by Task 7.
MD
```

If repo has a LICENSE file:
```bash
cp LICENSE skill/LICENSE.txt 2>/dev/null || echo "TBD" > skill/LICENSE.txt
```

**Step 2: Update .gitignore**

Append to repo-root `.gitignore`:

```
# Claude Skill build artifacts
skill/wheels/*.whl
skill/dist/
```

**Step 3: Sanity check**

Run: `git status` — confirm only the new placeholders + .gitignore line show.

**Step 4: Commit**

```bash
git add skill/ .gitignore
git commit -m "scaffold: claude skill directory structure"
```

---

## Task 3: Bootstrap script (idempotent install with sentinel)

**Files:**
- Create: `skill/scripts/bootstrap.py`
- Test: `tests/test_skill_bootstrap.py`

**Step 1: Write the failing test**

```python
"""Idempotent bootstrap: install groundling from bundled wheels exactly once."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BOOTSTRAP = Path(__file__).parent.parent / "skill" / "scripts" / "bootstrap.py"


def test_bootstrap_creates_sentinel_on_first_run(tmp_path, monkeypatch):
    """First invocation runs pip install and writes the sentinel file."""
    # Run with a custom sentinel path so we don't touch /tmp globally.
    env = {**os.environ, "GROUNDLING_SENTINEL": str(tmp_path / ".installed")}
    # First run: --dry-run mode skips actual pip install but writes sentinel.
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--dry-run"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".installed").exists()
    assert "would install" in result.stdout.lower() or "installed" in result.stdout.lower()


def test_bootstrap_skips_on_second_run(tmp_path):
    """If sentinel exists, bootstrap is a no-op (no pip invocation)."""
    sentinel = tmp_path / ".installed"
    sentinel.touch()
    env = {**os.environ, "GROUNDLING_SENTINEL": str(sentinel)}
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--dry-run"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "already installed" in result.stdout.lower() or "skip" in result.stdout.lower()
```

**Step 2: Implement bootstrap.py**

```python
#!/usr/bin/env python3
"""Idempotent skill bootstrap: install groundling from bundled wheels.

Runs once per sandbox lifetime — the sentinel file prevents re-install
on subsequent invocations. Override sentinel location via
GROUNDLING_SENTINEL env var (used by tests).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SENTINEL = "/tmp/.groundling-installed"


def main():
    p = argparse.ArgumentParser(description="Install groundling skill deps.")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip pip install; still write sentinel.")
    args = p.parse_args()

    sentinel = Path(os.environ.get("GROUNDLING_SENTINEL", DEFAULT_SENTINEL))
    if sentinel.exists():
        print(f"groundling already installed (sentinel: {sentinel}); skipping.")
        return

    skill_dir = Path(__file__).parent.parent
    wheels = skill_dir / "wheels"

    if args.dry_run:
        print(f"[dry-run] would install groundling from {wheels}/")
    else:
        if not wheels.exists() or not list(wheels.glob("*.whl")):
            print(f"error: no wheels in {wheels}", file=sys.stderr)
            sys.exit(1)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-index",
             "--find-links", str(wheels), "groundling"],
            check=True,
        )
        print("groundling installed.")

    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()


if __name__ == "__main__":
    main()
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_skill_bootstrap.py -v`
Expected: 2 passed.

**Step 4: Commit**

```bash
git add skill/scripts/bootstrap.py tests/test_skill_bootstrap.py
git commit -m "feat(skill): idempotent bootstrap with sentinel-file detection"
```

---

## Task 4: Prep script

**Files:**
- Create: `skill/scripts/prep.py`
- Test: `tests/test_skill_prep.py`

**Step 1: Write the failing test**

```python
"""Skill prep entry point: chunk PDFs, output linearized text + chunks.json."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_PREP = Path(__file__).parent.parent / "skill" / "scripts" / "prep.py"


def test_skill_prep_processes_pdfs(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    out_dir = tmp_path / "prep-out"
    result = subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(out_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out_dir / "doc1.linearized.txt").exists()
    assert (out_dir / "doc1.chunks.json").exists()
    chunks = json.loads((out_dir / "doc1.chunks.json").read_text())
    assert isinstance(chunks, list)
    assert all("chunk_id" in c and "text" in c for c in chunks)


def test_skill_prep_skips_non_pdfs(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    (corpus / "ignore.txt").write_text("ignore me")
    out_dir = tmp_path / "prep-out"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(out_dir)],
        check=True, capture_output=True,
    )
    assert (out_dir / "doc1.linearized.txt").exists()
    assert not (out_dir / "ignore.linearized.txt").exists()


def test_skill_prep_exits_2_on_empty_corpus(tmp_path):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    result = subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
```

**Step 2: Verify failure**

Run: `uv run pytest tests/test_skill_prep.py -v`
Expected: 3 FAIL.

**Step 3: Implement prep.py**

```python
#!/usr/bin/env python3
"""Skill prep: chunk every PDF in --corpus into linearized text + chunks.json.

Writes per-PDF outputs to --out/:
  <stem>.linearized.txt   — chunk-id-bracketed text Claude reads
  <stem>.chunks.json      — chunk metadata for render-time validation

Exits 2 if --corpus has no PDFs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from groundling.chunker import chunk_pdf
from groundling.prep import linearize_chunks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--no-tables", action="store_true",
                   help="Skip table detection (faster, less precise).")
    args = p.parse_args()

    pdfs = sorted(args.corpus.glob("*.pdf"))
    if not pdfs:
        print(f"error: no PDFs in {args.corpus}", file=sys.stderr)
        sys.exit(2)

    args.out.mkdir(parents=True, exist_ok=True)
    for pdf_path in pdfs:
        stem = pdf_path.stem
        chunks = chunk_pdf(pdf_path, detect_tables=not args.no_tables)
        (args.out / f"{stem}.linearized.txt").write_text(
            linearize_chunks(chunks), encoding="utf-8",
        )
        (args.out / f"{stem}.chunks.json").write_text(
            json.dumps(chunks, indent=2), encoding="utf-8",
        )
        print(f"prepared {stem}: {len(chunks)} chunks", file=sys.stderr)


if __name__ == "__main__":
    main()
```

**Step 4: Verify linearize_chunks exists**

Run: `grep -n "def linearize_chunks" src/groundling/prep.py`
Expected: a match. If not, find the actual name and update the import in prep.py.

**Step 5: Run tests**

Run: `uv run pytest tests/test_skill_prep.py -v`
Expected: 3 passed.

**Step 6: Commit**

```bash
git add skill/scripts/prep.py tests/test_skill_prep.py
git commit -m "feat(skill): prep entry — chunk PDFs + linearized text"
```

---

## Task 5: Render script

**Files:**
- Create: `skill/scripts/render.py`
- Test: `tests/test_skill_render.py`

**Step 1: Write tests**

```python
"""Skill render: validate markers + produce single-file inline answer.html."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_PREP = Path(__file__).parent.parent / "skill" / "scripts" / "prep.py"
SKILL_RENDER = Path(__file__).parent.parent / "skill" / "scripts" / "render.py"


def test_skill_render_produces_single_html(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    prep_out = tmp_path / "prep"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(prep_out)],
        check=True,
    )
    chunks = json.loads((prep_out / "doc1.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    cid, quote = first["chunk_id"], first["text"].split()[0]
    answer = f'See [the opening](chunk://doc1/{cid} "{quote}") here.'
    (tmp_path / "answer.md").write_text(answer, encoding="utf-8")

    out_html = tmp_path / "answer.html"
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out),
         "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(out_html)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out_html.exists()
    html = out_html.read_text(encoding="utf-8")
    assert 'src="cites/' not in html
    assert '<iframe' not in html
    assert 'data:image/png;base64,' in html
    assert 'class="cite"' in html


def test_skill_render_exits_5_on_zero_cites(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    prep_out = tmp_path / "prep"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(prep_out)],
        check=True,
    )
    (tmp_path / "answer.md").write_text("no cites here.")
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out),
         "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(tmp_path / "out.html")],
        capture_output=True, text=True,
    )
    assert result.returncode == 5
```

**Step 2: Implement render.py**

```python
#!/usr/bin/env python3
"""Skill render: validate markers + produce single-file answer.html.

Reads:
  --prep-dir   produced by prep.py
  --corpus     directory of original PDFs (for rendering page images)
  --answer     markdown file with cite markers
  --out        path to write the single-file answer.html

Exits 0 on success. Exits 5 if zero markers survived validation.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from groundling.answer_html_inline import build_inline_answer_html
from groundling.extract import extract_words
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_pdf_page


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prep-dir", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--answer", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    answer_md = args.answer.read_text(encoding="utf-8")
    markers = parse_markers(answer_md)

    pdf_state = {}
    def _load_pdf_state(stem):
        if stem in pdf_state:
            return pdf_state[stem]
        pdf_path = args.corpus / f"{stem}.pdf"
        chunks_json = args.prep_dir / f"{stem}.chunks.json"
        if not pdf_path.exists() or not chunks_json.exists():
            return None
        chunks = json.loads(chunks_json.read_text(encoding="utf-8"))
        words = extract_words(pdf_path, cache_dir=None)
        pdf_state[stem] = (words, chunks, pdf_path)
        return pdf_state[stem]

    cite_records = []
    next_id = 0
    for m in markers:
        if m.kind == "pdf":
            state = _load_pdf_state(m.pdf_stem)
            if state is None:
                continue
            words, chunks, pdf_path = state
            spans = resolve_marker_to_spans(m, chunks, words)
            if spans is None:
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "pdf",
                "spans": spans, "pdf_path": pdf_path,
                "marker_quote": m.quote,
                "claim_text": m.claim_text,
                "pdf_filename": pdf_path.name,
            })
        else:  # web
            if not (m.url and m.url.startswith(("http://", "https://"))):
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "web",
                "url": m.url,
                "marker_quote": m.quote,
                "claim_text": m.claim_text,
            })

    if not cite_records:
        print("error: zero valid cites in answer", file=sys.stderr)
        sys.exit(5)

    image_paths = {}
    page_owners = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for rec in cite_records:
            if rec["kind"] != "pdf":
                continue
            page = rec["spans"][0]["page"]
            key = (rec["pdf_path"], page)
            if key not in page_owners:
                page_owners[key] = rec["cite_id"]
                img = tmp_dir / f"{rec['cite_id']}.png"
                render_pdf_page(rec["pdf_path"], page=page,
                                out_path=img, scale=2.0)
                image_paths[rec["cite_id"]] = img
            else:
                image_paths[rec["cite_id"]] = image_paths[page_owners[key]]

        out_md = _rewrite_to_cite_scheme(answer_md, markers, cite_records)
        html = build_inline_answer_html(
            answer_md=out_md,
            cite_records=cite_records,
            image_paths=image_paths,
            scale=2.0,
        )

    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(cite_records)} cites)", file=sys.stderr)


def _rewrite_to_cite_scheme(answer_md, markers, cite_records):
    """Rewrite surviving markers to [text](cite://N "quote"); drop
    invalid markers entirely."""
    survivors = {id(r["marker"]): r["cite_id"] for r in cite_records}
    out = answer_md
    surviving_ids = set(survivors)
    all_spans = sorted(
        ((m.span_start, m.span_end, id(m), m) for m in markers),
        key=lambda t: -t[0],
    )
    for s, e, mid, m in all_spans:
        if mid in surviving_ids:
            cid = survivors[mid]
            if m.wrap_kind == "wrap":
                quote_escaped = m.quote.replace('"', '\\"')
                out = (out[:s]
                       + f'[{m.claim_text}](cite://{cid} "{quote_escaped}")'
                       + out[e:])
            else:
                out = (out[:s]
                       + f'[{cid}](cite://{cid} "{m.quote}")'
                       + out[e:])
        else:
            out = out[:s] + out[e:]
    return out


if __name__ == "__main__":
    main()
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_skill_render.py -v`
Expected: 2 passed.

**Step 4: Commit**

```bash
git add skill/scripts/render.py tests/test_skill_render.py
git commit -m "feat(skill): render entry — validate markers + inline HTML"
```

---

## Task 6: Wheel bundling script

**Files:**
- Create: `skill/build_wheels.sh` (executable)

**Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Build skill/wheels/ — bundled wheels for offline pip install.
# Target: Claude.ai sandbox (manylinux2014_x86_64, Python 3.12 per
# empirical reports).
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

PLATFORM="manylinux2014_x86_64"
PYTHON_VERSION="3.12"
WHEELS_DIR="skill/wheels"

echo "== Building groundling wheel =="
rm -rf dist/
uv build --wheel

echo "== Populating $WHEELS_DIR =="
rm -f "$WHEELS_DIR"/*.whl
cp dist/groundling-*.whl "$WHEELS_DIR/"

# Runtime deps. Use --only-binary=:all: to force pre-built wheels
# (we cannot compile in the sandbox).
uv pip download \
    --platform "$PLATFORM" \
    --python-version "$PYTHON_VERSION" \
    --only-binary=:all: \
    --dest "$WHEELS_DIR" \
    pymupdf markdown-it-py jinja2 pillow

rm -rf dist/

echo ""
echo "Bundled wheels:"
ls -lh "$WHEELS_DIR"/*.whl
```

**Step 2: Make executable, run it**

```bash
chmod +x skill/build_wheels.sh
./skill/build_wheels.sh
```

Expected: prints list of wheels totalling ~30-50MB.

**Step 3: Sanity-test the bundle**

Create a fresh venv and confirm offline install works:

```bash
python -m venv /tmp/skill-test-venv
/tmp/skill-test-venv/bin/pip install --no-index \
    --find-links skill/wheels groundling
/tmp/skill-test-venv/bin/python -c "from groundling.chunker import chunk_pdf; print('ok')"
rm -rf /tmp/skill-test-venv
```

Expected: `ok` printed.

**Step 4: Commit (script only — wheels are gitignored)**

```bash
git add skill/build_wheels.sh
git status  # confirm skill/wheels/*.whl are NOT tracked
git commit -m "feat(skill): wheel-bundling script for offline pip install"
```

---

## Task 7: SKILL.md + reference.md

The actual skill content. SKILL.md is the level-1 workflow checklist; reference.md is level-2 detail.

**Files:**
- Modify: `skill/SKILL.md` (replace placeholder with real content)
- Modify: `skill/reference.md` (replace placeholder)

**Step 1: Write SKILL.md**

Replace `skill/SKILL.md` with:

```markdown
---
name: groundling
description: Grounded Q&A over PDFs uploaded to a Project, optionally extended with web sources. Produces a self-contained HTML artifact with cite spans that show source passages on hover and open a full PDF-page view on click. Use when the user asks a question that requires verifiable citations from uploaded PDF documents — even casually (like "what does the report say about X" when PDFs are in scope). Do NOT trigger for ungrounded summarisation, for non-PDF documents (use docx/xlsx skills for those), or when the user explicitly asks for an answer without citations.
---

# Groundling — grounded PDF Q&A

Produces a verifiable answer to a question grounded in uploaded PDFs.
The output is a single self-contained `answer.html` the user can open
as an artifact; cite spans on hover show the source PDF region with
the cited passage highlighted.

Bundled wheels in `wheels/` make this work in any sandbox network
setting — no PyPI access required.

## Workflow

### Step 1: Bootstrap

Run once per sandbox lifetime. Idempotent — a sentinel file at
`/tmp/.groundling-installed` skips re-install on subsequent runs.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py
```

### Step 2: Find the user's PDFs

Use bash to locate uploaded PDFs in the sandbox. Common locations vary
by surface; check the working directory first, then `/mnt/user-data/`
or similar attachment paths. Pass the directory containing the PDFs to
prep.

### Step 3: Prep (cache-aware)

Build per-PDF chunks and linearized text. The output dir is
`/tmp/groundling-prep` by convention. Skip prep if the dir already
exists from an earlier turn in this conversation.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/prep.py \
    --corpus <pdf-dir> \
    --out /tmp/groundling-prep
```

For each `<stem>.pdf`, this writes `<stem>.linearized.txt` and
`<stem>.chunks.json` into the out dir.

### Step 4: Read + answer

Read each `<stem>.linearized.txt` from the prep dir. Each chunk is
prefixed with a bracketed ID like `[p2:b01]` (prose block) or
`[p2:t0r1c1]` (table cell).

Formulate the answer in markdown. Embed cite markers next to claims
following the contract below. Write the answer to `/tmp/answer.md`.

#### Marker contract

Two shapes — **prefer the wrapping form** when you can name the
specific claim a cite supports:

**Wrapping (preferred):**

    [<claim text>](chunk://<pdf-stem>/<chunk_id> "exact verbatim quote")
    [<claim text>](web://https://full-url "exact verbatim quote")

The link text is the precise span of your answer that this citation
grounds. The quote in the title attribute MUST be a verbatim
substring of the cited chunk's text.

**Point (footnote):** when the claim is the whole preceding sentence
and pulling out a fragment would feel artificial.

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim quote"]
    [url="https://full-url" quote="exact verbatim quote"]

See `reference.md` for marker validation rules and edge cases.

### Step 5: Render

Validate markers and produce the single-file HTML. Exit code 5 means
zero markers survived validation — your answer is ungrounded, rewrite
it.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/render.py \
    --prep-dir /tmp/groundling-prep \
    --corpus <pdf-dir> \
    --answer /tmp/answer.md \
    --out /tmp/answer.html
```

### Step 6: Surface to user

Print the answer markdown to the conversation, with cite markers
rewritten to `[N]` superscript-style references (the markdown body
should read cleanly, not as raw markers). Attach `/tmp/answer.html`
as a file artifact so the user can open it inline.
```

**Step 2: Write reference.md**

Replace `skill/reference.md` with:

```markdown
# groundling — reference

Level-2 detail loaded on demand from SKILL.md. Contains marker
validation rules, script flags, exit codes, common errors.

## prep.py

```
python scripts/prep.py --corpus <DIR> --out <DIR> [--no-tables]
```

- `--corpus` — directory of `.pdf` files; other extensions ignored.
- `--out` — output directory; created if missing.
- `--no-tables` — skip `find_tables()` table detection. Use for
  prose-heavy corpora or when table-detection produces noisy
  chunks. Default is tables-on (better cite precision on financial
  docs).

Output per PDF:
- `<stem>.linearized.txt` — chunk-id-bracketed plain text Claude
  reads to formulate the answer.
- `<stem>.chunks.json` — list of `{chunk_id, text, page, bbox,
  word_idx_start, word_idx_end}` for render-time validation.

Exit codes:
- `0` — success
- `2` — no PDFs in --corpus

## render.py

```
python scripts/render.py --prep-dir <DIR> --corpus <DIR> \
    --answer <FILE> --out <FILE>
```

- `--prep-dir` — output of `prep.py`.
- `--corpus` — original PDFs (used to re-render page images for
  cite previews).
- `--answer` — markdown with cite markers.
- `--out` — single self-contained `answer.html` written here.

Exit codes:
- `0` — success
- `5` — zero markers survived validation (answer is ungrounded)

## Marker validation rules

For every marker:

1. **Chunk lookup** — `<pdf-stem>` must match a `.chunks.json` file
   in the prep dir; `<chunk_id>` must exist in that file.
2. **Quote substring** — the `quote=` value must be a verbatim
   substring of the chunk's text. Unicode punctuation (curly
   quotes, em dashes, non-breaking spaces) is normalised to ASCII
   before comparison — you can quote with either form.
3. **Word resolution** — the quote's word positions in the chunk
   become the bbox highlight on the rendered page.

Invalid markers are silently dropped from the answer. The render
counter (printed to stderr) tells you how many survived:
`validated=N invalid_chunk=N invalid_quote=N invalid_url=N`.

## Web markers

Web cites have **loose validation only** in this skill — we trust
the marker without fetching the URL to verify the quote (network
access is optional in the sandbox). The user clicks through to the
source URL to verify.

## Common errors

- **"no PDFs in --corpus"** — wrong path; check `ls <corpus>` and
  verify the PDFs are there.
- **"zero valid cites"** — markers didn't validate. Most common
  cause: quote not a verbatim substring of the chunk. Re-read the
  linearized text and quote exactly.
- **`ModuleNotFoundError: No module named 'groundling'`** —
  bootstrap not run. Run `python scripts/bootstrap.py` first.
```

**Step 3: Sanity check character counts**

```bash
wc -c skill/SKILL.md skill/reference.md
```

SKILL.md should be ~3000-4000 chars (well under the 500-line ceiling).

**Step 4: Commit**

```bash
git add skill/SKILL.md skill/reference.md
git commit -m "docs(skill): SKILL.md workflow + reference.md detail"
```

---

## Task 8: End-to-end skill smoke test

**Files:**
- Create: `skill/smoke_skill.sh` (executable)

**Step 1: Write the script**

```bash
#!/usr/bin/env bash
# End-to-end: build skill zip, extract to a temp dir, install from
# bundled wheels into a fresh venv, run prep + render on the BYD
# corpus, verify output HTML is self-contained.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

./skill/build_wheels.sh

echo "== Building skill zip =="
mkdir -p skill/dist
ZIP="$REPO_ROOT/skill/dist/groundling-skill.zip"
rm -f "$ZIP"
( cd skill && zip -r "$ZIP" SKILL.md reference.md LICENSE.txt scripts wheels )

echo "== Simulating sandbox =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

unzip -q "$ZIP" -d "$TMP/skill"
python -m venv "$TMP/venv"
"$TMP/venv/bin/python" "$TMP/skill/scripts/bootstrap.py"

CORPUS=/tmp/grounded-qa-e2e
test -d "$CORPUS" || { echo "no BYD corpus at $CORPUS; cannot smoke-test"; exit 1; }

PREP="$TMP/prep"
"$TMP/venv/bin/python" "$TMP/skill/scripts/prep.py" \
    --corpus "$CORPUS" --out "$PREP"
test -f "$PREP/BYD-2025-Q1.linearized.txt"
test -f "$PREP/BYD-2025-Q1.chunks.json"

ANS="$TMP/answer.md"
cat > "$ANS" <<'MD'
Q1 revenue was [RMB 170 billion](chunk://BYD-2025-Q1/p2:t0r1c1 "170,360,448,000.00").
MD
OUT="$TMP/answer.html"
"$TMP/venv/bin/python" "$TMP/skill/scripts/render.py" \
    --prep-dir "$PREP" --corpus "$CORPUS" \
    --answer "$ANS" --out "$OUT"

test -f "$OUT"
grep -q 'class="cite"' "$OUT"
grep -q 'data:image/png;base64,' "$OUT"
! grep -q 'src="cites/' "$OUT"
! grep -q '<iframe' "$OUT"

# Idempotent bootstrap check.
"$TMP/venv/bin/python" "$TMP/skill/scripts/bootstrap.py" | grep -q "already installed"

echo ""
echo "SKILL SMOKE TEST PASSED"
```

**Step 2: Make executable, run it**

```bash
chmod +x skill/smoke_skill.sh
./skill/smoke_skill.sh
```

Expected: every section logs progress, final line is `SKILL SMOKE TEST PASSED`, exit 0.

**Step 3: Commit**

```bash
git add skill/smoke_skill.sh
git commit -m "test(skill): end-to-end smoke — build zip + sandbox install + render"
```

---

## Task 9: README — skill usage section

**Files:**
- Modify: `README.md` (add a "Use as a Claude.ai Skill" section)

**Step 1: Append to README, after the existing commands table**

```markdown
## Use as a Claude.ai Skill

Groundling can run entirely inside Claude.ai's sandbox — no pipx
install on your machine, no remote server. Upload the skill zip
via Settings > Features > Skills, then ask questions about PDFs
uploaded to a Project.

Build the zip:

    ./skill/build_wheels.sh
    ./skill/smoke_skill.sh   # optional but recommended

The zip is at `skill/dist/groundling-skill.zip` (~30-50MB, bundled
wheels). Upload via Customize > Skills > Upload a skill.

When you ask a question about a PDF in your project, Claude
auto-invokes the skill, runs prep + render in the sandbox, and
returns a self-contained `answer.html` with cite-span hover
previews of the source PDF region.
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): use groundling as a Claude.ai skill"
```

---

## Out of scope (file as follow-ups)

- Auto-finding uploaded PDFs in the sandbox (REL-224 #2 — still open; SKILL.md asks Claude to find them at runtime).
- Cross-platform wheel bundling (current targets manylinux2014_x86_64 only).
- Compressed images in inline output (PNG today; JPEG for cite previews would shrink table-heavy answers significantly).
- Token-budget tracking on prep output (linearized text could be huge for big corpora).
- Marketplace publishing (when one exists for Claude.ai skills).
- LLM-as-judge layer (REL-224 follow-up).
