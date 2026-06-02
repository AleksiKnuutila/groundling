# Web Evidence Skill — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task.

**Goal:** Add a `web://` cite kind to the existing groundling skill,
grounded in evidence files deposited by Claude during web QA. Output
is one `answer.html` with mixed PDF + web cites.

**Architecture:** Claude deposits per-source JSON evidence files in
`/tmp/groundling-web/`; `skill/scripts/render.py` loads them, validates
web markers against deposited evidence (substring check), and emits
`cite_records` with `kind: "web"`. The Jinja template gets a new hover
popover block and dialog excerpt rendering for web cites; CSS gets a
typographic popover style and a globe icon to distinguish web cites
visually.

**Tech Stack:** Python 3.11, existing Jinja2 templates, pytest. No new
runtime dependencies.

**Design doc:** `docs/plans/2026-06-02-web-evidence-skill-design.md`

---

## Task 1: Web evidence loader + excerpt computation

Two pure helpers, no I/O outside `load_web_evidence`. Bedrock for
everything downstream.

**Files:**
- Modify: `skill/scripts/render.py` (top-of-file helpers above `main`)
- Test: `tests/test_render_web.py` (new file)

**Step 1: Write the failing tests**

```python
# tests/test_render_web.py
import json
from pathlib import Path
import sys

# Make sibling import work the same way other tests do.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import render  # noqa: E402


def _write_ev(dir, name, payload):
    (dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_load_web_evidence_missing_dir_returns_empty(tmp_path):
    assert render.load_web_evidence(tmp_path / "nope") == {}


def test_load_web_evidence_empty_dir_returns_empty(tmp_path):
    assert render.load_web_evidence(tmp_path) == {}


def test_load_web_evidence_valid_file_indexed_by_url(tmp_path):
    _write_ev(tmp_path, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "hello world",
    })
    ev = render.load_web_evidence(tmp_path)
    assert "https://example.com/a" in ev
    assert ev["https://example.com/a"]["extracted_text"] == "hello world"


def test_load_web_evidence_skips_malformed_json(tmp_path, capsys):
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    _write_ev(tmp_path, "good.json", {
        "url": "https://example.com/x", "title": "X",
        "fetched_at": "2026-06-02T00:00:00Z", "extracted_text": "t",
    })
    ev = render.load_web_evidence(tmp_path)
    assert list(ev) == ["https://example.com/x"]
    assert "bad.json" in capsys.readouterr().err


def test_load_web_evidence_skips_missing_required_keys(tmp_path, capsys):
    _write_ev(tmp_path, "01.json", {"url": "https://x.com/", "title": "X"})
    assert render.load_web_evidence(tmp_path) == {}
    assert "01.json" in capsys.readouterr().err


def test_compute_excerpt_middle(tmp_path):
    text = "a" * 200 + "QUOTE" + "b" * 200
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert "QUOTE" in excerpt
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"


def test_compute_excerpt_quote_at_start(tmp_path):
    text = "QUOTE" + "x" * 500
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert off == 0
    assert excerpt.startswith("QUOTE")


def test_compute_excerpt_quote_at_end(tmp_path):
    text = "x" * 500 + "QUOTE"
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert excerpt.endswith("QUOTE")
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"


def test_compute_excerpt_short_text_returns_whole(tmp_path):
    excerpt, off = render.compute_excerpt("short QUOTE here", "QUOTE", window=150)
    assert excerpt == "short QUOTE here"
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"
```

**Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_render_web.py -v
```

Expected: ImportError or AttributeError for `load_web_evidence` /
`compute_excerpt` — they don't exist yet.

**Step 3: Implement the helpers**

Add to `skill/scripts/render.py` above `main()`:

```python
def load_web_evidence(web_dir: Path) -> dict[str, dict]:
    """Glob <web_dir>/*.json and return {url: evidence_dict}.

    Malformed files and files missing required keys are skipped with
    a warning to stderr."""
    if not web_dir.exists():
        return {}
    REQUIRED = {"url", "title", "fetched_at", "extracted_text"}
    out: dict[str, dict] = {}
    for p in sorted(web_dir.glob("*.json")):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warn: skipping {p.name}: {exc}", file=sys.stderr)
            continue
        missing = REQUIRED - payload.keys()
        if missing:
            print(f"warn: skipping {p.name}: missing keys {sorted(missing)}",
                  file=sys.stderr)
            continue
        out[payload["url"]] = payload
    return out


def compute_excerpt(text: str, quote: str, window: int = 150) -> tuple[str, int]:
    """Locate `quote` in `text`, return (excerpt, quote_offset_in_excerpt).

    Excerpt is `text` sliced to ±window chars around the quote span,
    clamped to text bounds."""
    pos = text.index(quote)
    start = max(0, pos - window)
    end = min(len(text), pos + len(quote) + window)
    excerpt = text[start:end]
    return excerpt, pos - start
```

**Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_render_web.py -v
```

Expected: all 8 tests pass.

**Step 5: Commit**

```bash
git add tests/test_render_web.py skill/scripts/render.py
git commit -m "feat(skill): add web evidence loader + excerpt helpers"
```

---

## Task 2: Web marker validation in render.py main flow

Replace the existing skeletal web branch (current
`skill/scripts/render.py:79-90`) with full validation against
deposited evidence. Counters gain `missing_evidence` and
`invalid_quote_web`.

**Files:**
- Modify: `skill/scripts/render.py` (web branch in `main()` + counters)
- Test: `tests/test_render_web.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_render_web.py`:

```python
import subprocess


def _run_render(tmp_path, answer_md, web_dir=None, prep_dir=None, corpus=None):
    answer = tmp_path / "answer.md"
    answer.write_text(answer_md, encoding="utf-8")
    out = tmp_path / "answer.html"
    cmd = ["python", str(Path(__file__).resolve().parents[1]
                          / "skill" / "scripts" / "render.py"),
           "--answer", str(answer), "--out", str(out)]
    if web_dir: cmd += ["--web-dir", str(web_dir)]
    if prep_dir: cmd += ["--prep-dir", str(prep_dir)]
    if corpus: cmd += ["--corpus", str(corpus)]
    return subprocess.run(cmd, capture_output=True, text=True), out


def test_web_marker_valid_produces_cite(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "Foo bar baz the quoted text more words",
    })
    md = '[claim](web://https://example.com/a "the quoted text")'
    proc, out = _run_render(tmp_path, md, web_dir=web)
    assert proc.returncode == 0, proc.stderr
    assert "validated=1" in proc.stderr
    assert "missing_evidence=0" in proc.stderr
    assert "invalid_quote_web=0" in proc.stderr
    html = out.read_text(encoding="utf-8")
    assert 'data-kind="web"' in html


def test_web_marker_missing_evidence_counter(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    md = '[c](web://https://nowhere.example/x "anything")'
    proc, _ = _run_render(tmp_path, md, web_dir=web)
    assert "missing_evidence=1" in proc.stderr
    assert proc.returncode == 5  # zero valid cites


def test_web_marker_invalid_quote_counter(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "this text does not contain the quote",
    })
    md = '[c](web://https://example.com/a "totally not present")'
    proc, _ = _run_render(tmp_path, md, web_dir=web)
    assert "invalid_quote_web=1" in proc.stderr
    assert proc.returncode == 5
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_render_web.py::test_web_marker_valid_produces_cite -v
```

Expected: argparse error (no `--web-dir` flag yet) OR cite-records
shape mismatch.

**Step 3: Update render.py main flow**

In `skill/scripts/render.py`:

1. Update counters dict to include the new keys:
   ```python
   counters = {"validated": 0, "invalid_chunk": 0, "invalid_quote": 0,
               "invalid_url": 0, "missing_evidence": 0,
               "invalid_quote_web": 0}
   ```

2. Load evidence near top of `main()` (after `markers = parse_markers(...)`):
   ```python
   web_evidence = load_web_evidence(args.web_dir) if args.web_dir else {}
   ```

3. Replace the existing `else:  # web` branch (current lines 79-90) with:
   ```python
   else:  # web
       if not (m.url and m.url.startswith(("http://", "https://"))):
           counters["invalid_url"] += 1
           continue
       ev = web_evidence.get(m.url)
       if ev is None:
           counters["missing_evidence"] += 1
           continue
       if m.quote not in ev["extracted_text"]:
           counters["invalid_quote_web"] += 1
           continue
       excerpt, q_off = compute_excerpt(ev["extracted_text"], m.quote)
       next_id += 1
       cite_records.append({
           "marker": m, "cite_id": next_id, "kind": "web",
           "url": m.url,
           "title": ev["title"],
           "fetched_at": ev["fetched_at"],
           "marker_quote": m.quote,
           "claim_text": m.claim_text,
           "excerpt": excerpt,
           "quote_offset_in_excerpt": q_off,
       })
       counters["validated"] += 1
   ```

4. Extend the stderr counters print line to include the new counters.

**Step 4: Run tests to verify passing**

```
uv run pytest tests/test_render_web.py -v
```

Expected: all tests pass (CLI flag tests will still fail until Task 3
adds the flag — that's fine, those are in Task 3).

**Step 5: Commit**

```bash
git add tests/test_render_web.py skill/scripts/render.py
git commit -m "feat(skill): validate web markers against deposited evidence"
```

---

## Task 3: CLI — add `--web-dir`, relax `--prep-dir`

Either-or-both: at least one must yield content. Both omitted → exit
2 with clear error.

**Files:**
- Modify: `skill/scripts/render.py` (argparse + arg handling)
- Test: `tests/test_render_web.py` (append)

**Step 1: Write the failing tests**

Append:

```python
def test_render_web_only_succeeds(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "the quoted text appears here",
    })
    md = '[c](web://https://example.com/a "the quoted text")'
    proc, out = _run_render(tmp_path, md, web_dir=web)
    assert proc.returncode == 0
    assert out.exists()


def test_render_neither_flag_errors(tmp_path):
    answer = tmp_path / "answer.md"; answer.write_text("hi")
    out = tmp_path / "answer.html"
    cmd = ["python", str(Path(__file__).resolve().parents[1]
                          / "skill" / "scripts" / "render.py"),
           "--answer", str(answer), "--out", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "at least one" in proc.stderr.lower() or "required" in proc.stderr.lower()
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_render_web.py::test_render_web_only_succeeds -v
```

Expected: error about `--prep-dir` being required, or `--corpus`.

**Step 3: Update argparse and routing**

In `skill/scripts/render.py`:

```python
p.add_argument("--prep-dir", type=Path, default=None)
p.add_argument("--corpus", type=Path, default=None)
p.add_argument("--web-dir", type=Path, default=None)
p.add_argument("--answer", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
args = p.parse_args()

if not args.prep_dir and not args.web_dir:
    p.error("at least one of --prep-dir or --web-dir is required")
if args.prep_dir and not args.corpus:
    p.error("--corpus is required when --prep-dir is given")
```

Guard the PDF state loader so it returns None when `prep_dir` is None
(should already be handled by the existing `chunks_json.exists()`
check, but make the contract explicit by checking
`args.prep_dir is not None` upfront in `_load_pdf_state`).

**Step 4: Run all render-web tests**

```
uv run pytest tests/test_render_web.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add tests/test_render_web.py skill/scripts/render.py
git commit -m "feat(skill): --web-dir flag, --prep-dir now optional"
```

---

## Task 4: `answer_html_inline.py` — `excerpt_html` builder for web cites

Compute server-side: HTML-escape `excerpt`, then splice
`<mark>...</mark>` around the quote span using
`quote_offset_in_excerpt` + `len(quote)`. Web cites do NOT consume
image slots.

**Files:**
- Modify: `src/groundling/answer_html_inline.py`
- Test: `tests/test_answer_html_inline.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_answer_html_inline.py`:

```python
def test_inline_html_web_cite_renders_excerpt_with_mark(tmp_path):
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
    # The excerpt appears with <mark> around the quote span.
    assert "before <mark>the quote</mark> after" in html
    # fetched_at is surfaced.
    assert "2026-06-02" in html
    # Live URL is linked.
    assert 'href="https://example.com/a"' in html


def test_inline_html_web_cite_does_not_inflate_img_registry(tmp_path):
    """Web cites must not allocate image slots."""
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
    # Empty registry — no base64 PNG bytes.
    assert "window.IMG_REGISTRY = []" in html or '"data:image/png;base64,' not in html


def test_inline_html_web_cite_escapes_excerpt_html(tmp_path):
    """A `<script>` in the excerpt must be escaped, not rendered."""
    cite_records = [{
        "cite_id": 1, "kind": "web",
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "marker_quote": "x", "claim_text": "c",
        "excerpt": "<script>evil()</script> x rest",
        "quote_offset_in_excerpt": 23,
    }]
    html = build_inline_answer_html(
        answer_md='[c](cite://1 "x")', cite_records=cite_records,
        image_paths={}, image_dims={}, scale=2.0,
    )
    assert "&lt;script&gt;evil()&lt;/script&gt;" in html
    # The <mark> around 'x' should still render (server-side splice).
    assert "<mark>x</mark>" in html
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_answer_html_inline.py -v -k web
```

Expected: failures — no excerpt/excerpt_html support in the inline
builder yet.

**Step 3: Implement**

In `src/groundling/answer_html_inline.py`:

1. Add helper above the main build function:
   ```python
   import html as _html

   def _build_excerpt_html(excerpt: str, quote: str, q_off: int) -> str:
       """Server-side splice: HTML-escape excerpt, then wrap quote span
       in <mark>. Returns ready-to-render HTML."""
       before = _html.escape(excerpt[:q_off])
       middle = _html.escape(quote)
       after = _html.escape(excerpt[q_off + len(quote):])
       return f"{before}<mark>{middle}</mark>{after}"
   ```

2. In the main builder, when iterating `cite_records` to build the
   inline-cite dicts for the template: for each web cite, add
   `excerpt_html`, `url`, `title`, `fetched_at` to the dict (alongside
   `quote`, `claim`, `cite_id`, `kind`).

3. Ensure web cites are skipped in the image-slot allocation loop
   (only PDF cites with image paths should populate `image_slots`).

**Step 4: Run tests to verify passing**

```
uv run pytest tests/test_answer_html_inline.py -v
```

All tests should pass (existing + new web tests).

**Step 5: Commit**

```bash
git add src/groundling/answer_html_inline.py tests/test_answer_html_inline.py
git commit -m "feat(html): server-render web cite excerpts with <mark> highlight"
```

---

## Task 5: Template — web cite hover preview + dialog excerpt

The dialog's `{% else %}` branch (currently shows URL only) gets the
excerpt + fetched_at. The cite anchor needs a new `.preview-text` div
for web hover (separate from the existing `.preview` background-image
hack used for PDFs).

**Files:**
- Modify: `src/groundling/templates/answer_inline.html.j2`
- Test: `tests/test_answer_html_inline.py` (append, two more
  assertions)

**Step 1: Write the failing tests**

```python
def test_inline_html_web_cite_has_hover_preview(tmp_path):
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
    # A typographic hover popover exists for the web cite anchor.
    assert 'class="preview-text"' in html


def test_inline_html_web_cite_deep_link_still_works(tmp_path):
    """A web cite's #cite-N hash link opens the dialog the same way
    PDF cites do."""
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
    # Dialog id matches the deep-link target regex.
    assert 'id="cite-1"' in html
    assert "window.location.hash.match" in html
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_answer_html_inline.py -v -k web
```

Expected: missing `.preview-text` class.

**Step 3: Update template**

In `src/groundling/templates/answer_inline.html.j2`:

1. Inside the cite anchor (where the `.preview` div currently lives),
   for web cites also emit:
   ```jinja
   {% if cite.kind == "web" %}
     <span class="preview preview-text">{{ cite.excerpt_html | safe }}</span>
   {% endif %}
   ```
   Add this alongside (not replacing) the existing `.preview` div used
   for PDFs. The PDF branch keeps its `<span class="preview">` empty
   div for the background-image hack.

2. In the `{% else %}` branch of the dialog body (web cite dialog),
   replace the current minimal content with:
   ```jinja
   <h3>Cite {{ cite.cite_id }} — {{ cite.title }}</h3>
   {% if cite.claim %}<div class="quote"><strong>Claim:</strong> {{ cite.claim }}</div>{% endif %}
   <div class="quote excerpt-quote">{{ cite.excerpt_html | safe }}</div>
   <p class="source">
     <a href="{{ cite.url }}" target="_blank" rel="noopener">{{ cite.url }}</a>
     <span class="fetched-at"> (fetched {{ cite.fetched_at }})</span>
   </p>
   ```

Note: the cite-dict shape passed in is `{cite_id, kind, claim, quote,
excerpt_html, url, title, fetched_at}` per Task 4 builder.

**Step 4: Run tests**

```
uv run pytest tests/test_answer_html_inline.py -v
```

All pass.

**Step 5: Commit**

```bash
git add src/groundling/templates/answer_inline.html.j2 tests/test_answer_html_inline.py
git commit -m "feat(html): web cite hover popover + dialog excerpt"
```

---

## Task 6: CSS — `.preview-text` popover + globe icon

Tighten the visual treatment so web cites look distinct from PDF
cites at a glance and the hover is readable text-mode.

**Files:**
- Modify: `src/groundling/templates/answer_inline.html.j2` (`<style>`
  block only)
- Test: `tests/test_answer_html_inline.py` (append, classname assertions)

**Step 1: Write the failing test**

```python
def test_inline_html_web_cite_has_css(tmp_path):
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
    # New popover styles + globe icon glyph somewhere in the stylesheet.
    assert ".preview-text" in html
    assert 'a.cite[data-kind="web"]' in html
    assert "mark" in html.lower()  # the mark styling block
```

**Step 2: Run to verify failure**

Expected: assertions on selectors that don't exist.

**Step 3: Add CSS rules**

Inside the existing `<style>` block in
`src/groundling/templates/answer_inline.html.j2`:

```css
a.cite[data-kind="web"]::before {
  content: "🌐";
  font-size: 0.75em;
  margin-right: 2px;
  opacity: 0.7;
}
a.cite .preview-text {
  display: none;
  position: absolute;
  bottom: 1.6em; left: 0;
  width: 360px;
  max-height: 200px;
  overflow: auto;
  padding: 8px 10px;
  border: 1px solid #bbb;
  border-radius: 4px;
  background: #fff;
  box-shadow: 0 6px 24px rgba(0,0,0,0.2);
  font-size: 14px;
  line-height: 1.5;
  color: #333;
  z-index: 100;
}
a.cite:hover .preview-text { display: block; }
a.cite mark, dialog.cite-detail mark {
  background: #fff200;
  padding: 0 2px;
}
dialog.cite-detail .excerpt-quote { font-style: normal; }
dialog.cite-detail .fetched-at { opacity: 0.55; font-size: 12px; }
```

**Step 4: Run tests to verify passing**

```
uv run pytest tests/test_answer_html_inline.py -v
```

All pass.

**Step 5: Commit**

```bash
git add src/groundling/templates/answer_inline.html.j2 tests/test_answer_html_inline.py
git commit -m "style(html): web cite popover + globe icon"
```

---

## Task 7: `SKILL.md` — Step 2b + web marker contract

Documentation only. Drills evidence-deposit discipline on the model
side, promotes `web://` to a peer of `chunk://` in the marker
contract section, updates the render command line.

**Files:**
- Modify: `skill/SKILL.md`

**Step 1 (no test):** Documentation change, validated empirically in
Task 8.

**Step 2: Apply edits**

1. After "Step 2: Find the user's PDFs", insert "Step 2b: Web evidence
   (if using web sources)":

   ```markdown
   ### Step 2b: Web evidence (if using web sources)

   For each web source you intend to cite, deposit one JSON evidence
   file in `/tmp/groundling-web/`. Use sequential numeric filenames:

       mkdir -p /tmp/groundling-web
       cat > /tmp/groundling-web/01.json <<'EOF'
       {
         "url": "https://example.com/article",
         "title": "Article Title",
         "fetched_at": "2026-06-02T14:30:00Z",
         "extracted_text": "<verbatim copy of the readable text you
                            got back from web_search / web_fetch>"
       }
       EOF

   Critical:
   - Copy `extracted_text` verbatim. Do not paraphrase or truncate.
     The renderer will fail to validate any quote not present here as
     an exact substring.
   - Use the same URL string in the marker and the evidence file. If
     they differ even by trailing slash, the cite will be dropped.
   - Only deposit sources you will actually cite. Speculative deposits
     waste sandbox space.
   - If the search-result snippet is too short to contain the quote
     you want to cite, call web_fetch on the URL for full content.
   ```

2. In "Marker contract", add `web://` as a peer:

   ```markdown
   **Web cite (wrapping):**

       [<claim text>](web://<full-url> "exact verbatim quote")

   **Web cite (point):**

       [url="<full-url>" quote="exact verbatim quote"]

   The URL must match a `url` field in some `/tmp/groundling-web/`
   evidence file. The quote must be a verbatim substring of that
   file's `extracted_text`.
   ```

3. Update Step 5 to show the new flag set:

   ```bash
   python /skills/groundling/scripts/render.py \
       --prep-dir /tmp/groundling-prep \
       --corpus <pdf-dir> \
       --web-dir /tmp/groundling-web \
       --answer /tmp/answer.md \
       --out /tmp/answer.html
   ```

   With a note: "Pass `--prep-dir` and `--corpus` only if you have
   PDFs. Pass `--web-dir` only if you have web evidence. At least one
   side must be present."

   Update the stderr counter example line to include
   `missing_evidence=N invalid_quote_web=N`.

**Step 3: Commit**

```bash
git add skill/SKILL.md
git commit -m "docs(skill): document web evidence deposit + web marker contract"
```

---

## Task 8: `api_smoke_web.py` — end-to-end real API test

Adapts the existing `skill/api_smoke.py` for a web QA scenario.
Tests the protocol against the real Anthropic API + code-execution
sandbox.

**Files:**
- Create: `skill/api_smoke_web.py`

**Step 1: Implement the smoke script**

Model it on `skill/api_smoke.py`. Differences:

- No PDF upload step. The question itself should require web search.
- A current-events-ish prompt: "What were the most recent quarterly
  earnings reported by Saudi Aramco? Cite your sources." (Pick
  something the model will reliably need to web_search for —
  something past its training cutoff if possible.)
- After invocation, extract surfaced `answer.html` file_id from
  `bash_code_execution_tool_result.content[].file_id` the same way
  `api_smoke.py` does today.
- Print stderr counters from render so we can see protocol health.
- Download the artifact and assert it contains:
  - `data-kind="web"` (at least one web cite)
  - `class="preview-text"` (hover popover rendered)
  - `<mark>` (quote highlight present)
  - At least one `href="http`

**Step 2: Run it**

```
uv run python skill/api_smoke_web.py
```

Expected output (stderr from render, surfaced through model):
```
validated=N invalid_chunk=0 invalid_quote=0 invalid_url=0
missing_evidence=0 invalid_quote_web=0
```

If counters surface protocol violations, the fix is almost always in
SKILL.md wording. Iterate on Step 2b language, rebuild zip, retest.

**Step 3: Commit**

```bash
git add skill/api_smoke_web.py
git commit -m "test(skill): api_smoke_web.py — end-to-end web QA smoke"
```

---

## Task 9: Build skill zip + tag v0.2.0

**Files:**
- Existing build scripts; no code changes
- Update version refs in CHANGELOG/README if applicable

**Step 1: Build the zip**

```bash
./skill/build_zip.sh v0.2.0
```

Expected: produces `skill/dist/groundling-skill-v0.2.0.zip` and the
stable-name `skill/dist/groundling-skill.zip`.

**Step 2: Update README example version reference if any**

Search for "v0.1" or "0.1.1" in README and update to "v0.2.0" where
appropriate (the install snippet uses the stable URL — no version
bump needed there).

**Step 3: Tag and push release**

```bash
git tag v0.2.0
git push origin main --tags
gh release create v0.2.0 \
    skill/dist/groundling-skill-v0.2.0.zip \
    skill/dist/groundling-skill.zip \
    --title "v0.2.0 — web evidence skill" \
    --notes "..."
```

Release notes summary:
- Web cites now first-class alongside PDF cites
- New `--web-dir` flag on `render.py`; `--prep-dir` now optional
- Evidence-deposit protocol documented in SKILL.md Step 2b
- Hover popover + dialog excerpt UI for web cites
- New counters: `missing_evidence`, `invalid_quote_web`

**Step 4 (manual verification):**

Download the just-published stable-name zip and re-run
`api_smoke_web.py` against the released artifact (not the local
build) to confirm the published artifact is healthy.

---

## Done criteria

- All tests pass (`uv run pytest -v`)
- `api_smoke_web.py` returns a real-API answer.html with healthy
  validation counters
- `groundling-skill.zip` from the v0.2.0 release installs and runs in
  Claude.ai web sandbox for a web-only question
- A hybrid PDF + web question produces a single answer.html with both
  cite kinds visually distinguished
