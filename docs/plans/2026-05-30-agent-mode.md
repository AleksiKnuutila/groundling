# groundling agent-driven mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `groundling prep` + `groundling render` commands that let Claude Code answer corpus questions using subscription inference (no `ANTHROPIC_API_KEY` required), reusing v1's cite-HTML machinery unchanged.

**Architecture:** `prep` chunks PDFs (PyMuPDF blocks + `find_tables()` cells) and writes per-PDF linearized text + dispatch hint. Agent reads the prep, answers with `[chunk=ID quote="..."]` / `[url=... quote="..."]` markers. `render` validates markers, resolves to bboxes via v1's word offset_map, generates cites/N.html via v1's existing `render_cite_pdf` / `render_cite_web`, rewrites markdown to use `[N]` file:// references.

**Tech Stack:** Python 3.11+, Typer, PyMuPDF (fitz), Jinja2, pytest. No new deps beyond v1.

**Reference design doc:** `docs/plans/2026-05-30-agent-mode-design.md`

**Reference v1 modules (used unchanged):**
- `extract_words(pdf_path, *, cache_dir)` → `list[{content, bbox, page}]`
- `linearize_words(words)` → `(text, offset_map)`; `resolve_range(entries, start, end)`
- `render_cite_pdf(...)`, `render_cite_web(...)`, `build_text_fragment_url(url, cited_text)`

Branch: `feature/agent-mode`, off `feature/v1`. Baseline: 67 tests pass.

---

## Task 1: Chunker — prose blocks via PyMuPDF

Walks a PDF page, partitions words into `b<n>` chunks based on PyMuPDF's block segmentation. Tables come later in Task 2.

**Files:**
- Create: `src/groundling/chunker.py`
- Create: `tests/test_chunker.py`

**Step 1: Write failing tests**

```python
# tests/test_chunker.py
from __future__ import annotations

from groundling.chunker import chunk_pdf


def test_chunk_pdf_returns_chunks_with_ids(text_pdf):
    chunks = chunk_pdf(text_pdf, detect_tables=False)
    assert len(chunks) > 0
    c = chunks[0]
    # Per-PDF chunk_id has form "p<page>:b<n>"
    assert c["chunk_id"].startswith("p1:b") or c["chunk_id"].startswith("p2:b")
    assert isinstance(c["text"], str) and c["text"]
    assert c["page"] in (1, 2)
    assert len(c["bbox"]) == 4
    # word_idx_start/end refer to indices into the flat word list
    assert c["word_idx_start"] < c["word_idx_end"]


def test_chunk_pdf_word_indices_are_contiguous(text_pdf):
    """Word index ranges should be monotonically increasing and
    non-overlapping (each word belongs to exactly one chunk)."""
    chunks = chunk_pdf(text_pdf, detect_tables=False)
    prev_end = 0
    for c in chunks:
        assert c["word_idx_start"] >= prev_end
        prev_end = c["word_idx_end"]


def test_chunk_pdf_text_concatenates_words_with_spaces(text_pdf):
    """A chunk's `text` field should match the words it covers, joined
    with single spaces (so the existing linearize_words convention
    holds inside a chunk)."""
    from groundling.extract import extract_words
    chunks = chunk_pdf(text_pdf, detect_tables=False)
    words = extract_words(text_pdf, cache_dir=None)
    for c in chunks:
        expected = " ".join(
            w["content"] for w in words[c["word_idx_start"]:c["word_idx_end"]]
        )
        assert c["text"] == expected
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_chunker.py -v
```
Expected: `ModuleNotFoundError: groundling.chunker`.

**Step 3: Implement**

```python
# src/groundling/chunker.py
"""Chunk a PDF into per-page units: prose blocks + (optionally) table cells.

Each chunk has a stable ID, page, bbox, and a word-index range into the
flat word list produced by extract_words. The render-time validation
uses these ranges to map a cited quote back to specific word bboxes.

Chunk ID grammar (per-PDF, mirrors groundswell's convention):
- `p<page>:b<n>` for prose blocks (PyMuPDF blocks)
- `p<page>:t<i>r<r>c<c>` for table cells (added in Task 2)
"""
from __future__ import annotations

from pathlib import Path

import fitz

from groundling.extract import extract_words


def _bbox_contains_point(bbox: list[float], x: float, y: float) -> bool:
    """True iff (x, y) is inside bbox = [x0, y0, x1, y1]."""
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def chunk_pdf(pdf_path: Path, *, detect_tables: bool = True) -> list[dict]:
    """Return per-PDF chunks: [{chunk_id, page, bbox, word_idx_start,
    word_idx_end, text}, ...] sorted by (page, reading order)."""
    words = extract_words(pdf_path, cache_dir=None)
    # word_idx_by_page: page → list of (idx, word) preserving extract order
    word_idx_by_page: dict[int, list[tuple[int, dict]]] = {}
    for idx, w in enumerate(words):
        word_idx_by_page.setdefault(w["page"], []).append((idx, w))

    chunks: list[dict] = []
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            page_words = word_idx_by_page.get(page_num, [])
            if not page_words:
                continue
            # PyMuPDF blocks: [(x0, y0, x1, y1, text, block_no, block_type)]
            blocks = page.get_text("blocks")
            for b_idx, block in enumerate(blocks):
                bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
                # Words whose bbox center falls inside this block.
                block_words: list[tuple[int, dict]] = []
                for idx, w in page_words:
                    wx0, wy0, wx1, wy1 = w["bbox"]
                    cx = (wx0 + wx1) / 2
                    cy = (wy0 + wy1) / 2
                    if _bbox_contains_point([bx0, by0, bx1, by1], cx, cy):
                        block_words.append((idx, w))
                if not block_words:
                    continue
                start = block_words[0][0]
                end = block_words[-1][0] + 1
                text = " ".join(w["content"] for _, w in block_words)
                chunks.append({
                    "chunk_id": f"p{page_num}:b{b_idx:02d}",
                    "page": page_num,
                    "bbox": [bx0, by0, bx1, by1],
                    "word_idx_start": start,
                    "word_idx_end": end,
                    "text": text,
                })
    chunks.sort(key=lambda c: (c["page"], c["word_idx_start"]))
    return chunks
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_chunker.py -v
```
Expected: 3 passed.

Full suite: `uv run pytest tests/ -q` → 70 passed (67 + 3).

**Step 5: Commit**

```
git add src/groundling/chunker.py tests/test_chunker.py
git commit -m "feat(chunker): PyMuPDF block-based prose chunking"
```

---

## Task 2: Chunker — table cell detection

Adds `find_tables()` integration. Words inside a table cell go into `t<i>r<r>c<c>` chunks; remaining words on the page still use the `b<n>` path.

**Files:**
- Modify: `src/groundling/chunker.py`
- Modify: `tests/test_chunker.py` (add tests + fixture)
- Modify: `tests/conftest.py` (add `table_pdf` fixture)

**Step 1: Add fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def table_pdf(tmp_path: Path) -> Path:
    """PDF with one prose paragraph + one 2x2 grid-drawn table."""
    doc = fitz.open()
    page = doc.new_page()
    # Prose paragraph
    page.insert_text((72, 72), "Some intro paragraph here.")
    # Draw a 2x2 table at y=120..200
    # Header row
    page.insert_text((100, 130), "Header A")
    page.insert_text((200, 130), "Header B")
    # Body row
    page.insert_text((100, 170), "Value 1")
    page.insert_text((200, 170), "Value 2")
    # Draw cell borders so PyMuPDF can detect the table.
    page.draw_rect(fitz.Rect(80, 120, 180, 150))  # A header
    page.draw_rect(fitz.Rect(180, 120, 280, 150))  # B header
    page.draw_rect(fitz.Rect(80, 150, 180, 200))  # A value
    page.draw_rect(fitz.Rect(180, 150, 280, 200))  # B value
    out = tmp_path / "with_table.pdf"
    doc.save(out)
    doc.close()
    return out
```

**Step 2: Write failing tests**

Append to `tests/test_chunker.py`:

```python
def test_chunk_pdf_emits_table_cells(table_pdf):
    chunks = chunk_pdf(table_pdf, detect_tables=True)
    cell_ids = [c["chunk_id"] for c in chunks if "t" in c["chunk_id"]]
    # At least the four cells of the 2x2 table.
    expected = {"p1:t0r0c0", "p1:t0r0c1", "p1:t0r1c0", "p1:t0r1c1"}
    assert expected.issubset(set(cell_ids))


def test_chunk_pdf_cell_text_matches_cell_content(table_pdf):
    chunks = {c["chunk_id"]: c for c in chunk_pdf(table_pdf, detect_tables=True)}
    assert "Header A" in chunks["p1:t0r0c0"]["text"]
    assert "Value 2" in chunks["p1:t0r1c1"]["text"]


def test_detect_tables_false_skips_cells(table_pdf):
    chunks = chunk_pdf(table_pdf, detect_tables=False)
    assert not any("t" in c["chunk_id"] for c in chunks)
```

**Step 3: Run to verify failure**

```
uv run pytest tests/test_chunker.py -v
```
Expected: 3 new tests fail (no table-cell branch yet).

**Step 4: Implement**

Replace `chunk_pdf` in `src/groundling/chunker.py`:

```python
def chunk_pdf(pdf_path: Path, *, detect_tables: bool = True) -> list[dict]:
    words = extract_words(pdf_path, cache_dir=None)
    word_idx_by_page: dict[int, list[tuple[int, dict]]] = {}
    for idx, w in enumerate(words):
        word_idx_by_page.setdefault(w["page"], []).append((idx, w))

    chunks: list[dict] = []
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            page_words = word_idx_by_page.get(page_num, [])
            if not page_words:
                continue

            # Step 1: detect tables and consume their cells first.
            consumed_word_indices: set[int] = set()
            if detect_tables:
                try:
                    tables = page.find_tables()
                except Exception:
                    tables = []
                for t_idx, table in enumerate(getattr(tables, "tables", []) or list(tables)):
                    for r_idx, row in enumerate(table.rows):
                        for c_idx, cell in enumerate(row.cells):
                            if cell is None:
                                continue
                            cell_bbox = list(cell)  # (x0, y0, x1, y1)
                            cell_words: list[tuple[int, dict]] = []
                            for idx, w in page_words:
                                if idx in consumed_word_indices:
                                    continue
                                wx0, wy0, wx1, wy1 = w["bbox"]
                                cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
                                if _bbox_contains_point(cell_bbox, cx, cy):
                                    cell_words.append((idx, w))
                            if not cell_words:
                                continue
                            for idx, _ in cell_words:
                                consumed_word_indices.add(idx)
                            start = cell_words[0][0]
                            end = cell_words[-1][0] + 1
                            text = " ".join(w["content"] for _, w in cell_words)
                            chunks.append({
                                "chunk_id": f"p{page_num}:t{t_idx}r{r_idx}c{c_idx}",
                                "page": page_num,
                                "bbox": cell_bbox,
                                "word_idx_start": start,
                                "word_idx_end": end,
                                "text": text,
                            })

            # Step 2: remaining words → prose blocks.
            blocks = page.get_text("blocks")
            for b_idx, block in enumerate(blocks):
                bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
                block_words: list[tuple[int, dict]] = []
                for idx, w in page_words:
                    if idx in consumed_word_indices:
                        continue
                    wx0, wy0, wx1, wy1 = w["bbox"]
                    cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
                    if _bbox_contains_point([bx0, by0, bx1, by1], cx, cy):
                        block_words.append((idx, w))
                if not block_words:
                    continue
                start = block_words[0][0]
                end = block_words[-1][0] + 1
                text = " ".join(w["content"] for _, w in block_words)
                chunks.append({
                    "chunk_id": f"p{page_num}:b{b_idx:02d}",
                    "page": page_num,
                    "bbox": [bx0, by0, bx1, by1],
                    "word_idx_start": start,
                    "word_idx_end": end,
                    "text": text,
                })

    chunks.sort(key=lambda c: (c["page"], c["word_idx_start"]))
    return chunks
```

**Step 5: Run to verify passes**

```
uv run pytest tests/test_chunker.py -v && uv run pytest tests/ -q
```
Expected: 6 chunker tests pass; full suite 73 passed.

**Step 6: Commit**

```
git add src/groundling/chunker.py tests/test_chunker.py tests/conftest.py
git commit -m "feat(chunker): table cell detection via page.find_tables()"
```

---

## Task 3: Agent module — dispatch_hint + subagent prompt

Constants + a `compute_dispatch_hint(prep_records)` function that returns the recommendation. Plus the subagent prompt template as a module constant so AGENTS.md can reference one source of truth.

**Files:**
- Create: `src/groundling/agent.py`
- Create: `tests/test_agent.py`

**Step 1: Write failing tests**

```python
# tests/test_agent.py
from __future__ import annotations

from groundling.agent import (
    MAX_PDFS_IN_SESSION,
    MAX_TOKENS_IN_SESSION,
    SUBAGENT_PROMPT_TEMPLATE,
    compute_dispatch_hint,
)


def _record(n_chunks=10, linearized_tokens=1000):
    return {"n_chunks": n_chunks, "linearized_tokens": linearized_tokens}


def test_small_corpus_recommends_in_session():
    hint = compute_dispatch_hint([_record(), _record()])
    assert hint["recommend"] == "in_session"
    assert hint["n_pdfs"] == 2


def test_many_pdfs_recommends_fanout():
    records = [_record() for _ in range(MAX_PDFS_IN_SESSION + 1)]
    hint = compute_dispatch_hint(records)
    assert hint["recommend"] == "subagent_fanout"
    assert hint["n_pdfs"] == MAX_PDFS_IN_SESSION + 1


def test_many_tokens_recommends_fanout():
    records = [_record(linearized_tokens=MAX_TOKENS_IN_SESSION + 1)]
    hint = compute_dispatch_hint(records)
    assert hint["recommend"] == "subagent_fanout"


def test_dispatch_hint_includes_aggregate_counts():
    records = [_record(n_chunks=10, linearized_tokens=500),
               _record(n_chunks=15, linearized_tokens=800)]
    hint = compute_dispatch_hint(records)
    assert hint["n_chunks"] == 25
    assert hint["linearized_tokens"] == 1300


def test_subagent_prompt_template_has_required_placeholders():
    """The prompt template is shipped as a string with {pdf_path} and
    {question} placeholders that AGENTS.md fills at dispatch time."""
    assert "{pdf_path}" in SUBAGENT_PROMPT_TEMPLATE
    assert "{question}" in SUBAGENT_PROMPT_TEMPLATE
    # And it carries the marker contract verbatim.
    assert "[chunk=" in SUBAGENT_PROMPT_TEMPLATE
    assert "[url=" in SUBAGENT_PROMPT_TEMPLATE
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_agent.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/agent.py
"""Dispatch-hint thresholds + subagent prompt template.

Single source of truth for AGENTS.md's branching logic. Tuning happens
here, in module constants, so docs and behaviour can't drift.
"""
from __future__ import annotations


MAX_PDFS_IN_SESSION = 4
MAX_TOKENS_IN_SESSION = 120_000


def compute_dispatch_hint(prep_records: list[dict]) -> dict:
    """Compute the dispatch_hint dict written by `groundling prep`.

    prep_records is one dict per PDF with at least
    {"n_chunks": int, "linearized_tokens": int}.
    """
    n_pdfs = len(prep_records)
    n_chunks = sum(r["n_chunks"] for r in prep_records)
    n_tokens = sum(r["linearized_tokens"] for r in prep_records)
    fits_in_session = (
        n_pdfs <= MAX_PDFS_IN_SESSION
        and n_tokens <= MAX_TOKENS_IN_SESSION
    )
    return {
        "n_pdfs": n_pdfs,
        "n_chunks": n_chunks,
        "linearized_tokens": n_tokens,
        "recommend": "in_session" if fits_in_session else "subagent_fanout",
        "thresholds": {
            "max_pdfs_in_session": MAX_PDFS_IN_SESSION,
            "max_tokens_in_session": MAX_TOKENS_IN_SESSION,
        },
    }


SUBAGENT_PROMPT_TEMPLATE = """\
You are answering a question about a single document.

Read this file with the Read tool:
{pdf_path}

It contains chunked text from one PDF. Each chunk is on its own line(s),
prefixed by a bracketed ID like `[p2:b01]` for prose blocks or
`[p2:t0r1c1]` for table cells. Tables are rendered as markdown grids
with one ID per cell.

Answer this question, citing the chunks you drew from:
{question}

Marker contract (mandatory; deviating breaks citation validation):

When citing a chunk in this PDF:
  [chunk=<stem>:<chunk_id> quote="exact verbatim substring of the chunk"]

The chunk_id is the bracketed label as it appears in the linearized
text (the part after `<stem>:`). The quote MUST be a verbatim substring
of that chunk's text — not paraphrased.

When citing a web source (via your WebSearch / WebFetch tools):
  [url="https://full-url" quote="exact verbatim sentence from page"]

The quote MUST be a verbatim substring of the fetched page.

Write your per-document answer as markdown. Embed markers inline next
to the claims they support. If the document doesn't answer the
question, say so plainly without inventing citations.
"""
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_agent.py -v
```
Expected: 5 passed.

**Step 5: Commit**

```
git add src/groundling/agent.py tests/test_agent.py
git commit -m "feat(agent): dispatch_hint thresholds + subagent prompt template"
```

---

## Task 4: Prep module — chunks.json + linearized.txt writers

Per-PDF artefacts: `<stem>.chunks.json` from `chunk_pdf` output; `<stem>.linearized.txt` with bracketed chunk IDs inline.

**Files:**
- Create: `src/groundling/prep.py`
- Create: `tests/test_prep.py`

**Step 1: Write failing tests**

```python
# tests/test_prep.py
from __future__ import annotations

import json
import shutil
from pathlib import Path

from groundling.prep import write_pdf_artifacts


def _seed(tmp_path, text_pdf) -> Path:
    out = tmp_path / "prep"
    out.mkdir()
    shutil.copy(text_pdf, tmp_path / "sample.pdf")
    return out


def test_write_pdf_artifacts_writes_chunks_json(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    record = write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    chunks_file = out / "sample.chunks.json"
    assert chunks_file.exists()
    chunks = json.loads(chunks_file.read_text())
    assert isinstance(chunks, list) and len(chunks) > 0
    assert {"chunk_id", "page", "bbox", "word_idx_start", "word_idx_end", "text"}.issubset(
        chunks[0].keys()
    )


def test_write_pdf_artifacts_writes_linearized_txt(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    linearized = (out / "sample.linearized.txt").read_text()
    # Every line should be prefixed by a bracketed chunk ID like
    # `[sample:p1:b00]`.
    chunks = json.loads((out / "sample.chunks.json").read_text())
    for c in chunks:
        assert f"[sample:{c['chunk_id']}]" in linearized


def test_write_pdf_artifacts_returns_record(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    record = write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    assert record["pdf_stem"] == "sample"
    assert record["n_chunks"] > 0
    assert record["linearized_tokens"] > 0
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_prep.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/prep.py
"""Per-PDF prep artefacts: chunks.json + linearized.txt + record dict."""
from __future__ import annotations

import json
from pathlib import Path

from groundling.chunker import chunk_pdf


def _approx_tokens(text: str) -> int:
    """Rough token count for dispatch heuristics. ~1 token per 4 chars
    is a defensible ballpark for English text."""
    return max(1, len(text) // 4)


def write_pdf_artifacts(
    pdf_path: Path, *, out_dir: Path, detect_tables: bool = True,
) -> dict:
    """Write <stem>.chunks.json + <stem>.linearized.txt under out_dir.
    Return a record describing the PDF for the dispatch_hint."""
    stem = pdf_path.stem
    chunks = chunk_pdf(pdf_path, detect_tables=detect_tables)

    (out_dir / f"{stem}.chunks.json").write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False)
    )

    # Render linearized text with full chunk IDs like `[sample:p1:b00]`.
    # For table cells, render the table grid by grouping cells of the
    # same (page, table_idx).
    lines: list[str] = []
    # Group prose blocks and table cells by (page, table_idx-or-None)
    grouped: dict[tuple[int, int | None], list[dict]] = {}
    for c in chunks:
        # Cell IDs look like "p<p>:t<i>rN cM"; prose like "p<p>:b<n>"
        cid = c["chunk_id"]
        if ":t" in cid:
            # Extract table_idx
            t_part = cid.split(":t", 1)[1]
            table_idx = int(t_part.split("r", 1)[0])
            key = (c["page"], table_idx)
        else:
            key = (c["page"], None)
        grouped.setdefault(key, []).append(c)

    last_page: int | None = None
    for (page, table_idx), group in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1] if x[0][1] is not None else -1)):
        if last_page is not None and page != last_page:
            lines.append("")
        last_page = page
        if table_idx is None:
            for c in group:
                lines.append(f"[{stem}:{c['chunk_id']}] {c['text']}")
        else:
            # Render as a markdown grid. Determine row/col counts.
            cells: dict[tuple[int, int], dict] = {}
            for c in group:
                # cid like "p1:t0r0c0"
                rc = c["chunk_id"].split("t", 1)[1].split("r", 1)[1]
                r, c_idx = rc.split("c", 1)
                cells[(int(r), int(c_idx))] = c
            n_rows = max(r for r, _ in cells) + 1
            n_cols = max(c for _, c in cells) + 1
            grid: list[list[str]] = []
            for r in range(n_rows):
                row: list[str] = []
                for col in range(n_cols):
                    c = cells.get((r, col))
                    if c is None:
                        row.append("")
                        continue
                    content = c["text"].replace("\n", " ").replace("|", r"\|").strip()
                    row.append(f"[{stem}:{c['chunk_id']}] {content}")
                grid.append(row)
            lines.append("")
            lines.append("| " + " | ".join(grid[0]) + " |")
            lines.append("| " + " | ".join(["---"] * n_cols) + " |")
            for row in grid[1:]:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

    linearized = "\n".join(lines).strip() + "\n"
    (out_dir / f"{stem}.linearized.txt").write_text(linearized, encoding="utf-8")

    return {
        "pdf_stem": stem,
        "pdf_path": str(pdf_path.resolve()),
        "n_chunks": len(chunks),
        "linearized_tokens": _approx_tokens(linearized),
    }
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_prep.py -v && uv run pytest tests/ -q
```
Expected: 3 prep tests pass; full suite 81 passed.

**Step 5: Commit**

```
git add src/groundling/prep.py tests/test_prep.py
git commit -m "feat(prep): per-PDF chunks.json + linearized.txt writer"
```

---

## Task 5: Prep orchestration + `groundling prep` CLI

`run_prep(corpus_dir, out_dir, detect_tables)` walks PDFs, calls `write_pdf_artifacts` per PDF, computes + writes dispatch_hint.json, returns the prep dir path. Plus the Typer subcommand.

**Files:**
- Modify: `src/groundling/prep.py`
- Modify: `src/groundling/cli.py`
- Create: `tests/test_prep_orchestration.py`

**Step 1: Write failing tests**

```python
# tests/test_prep_orchestration.py
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.errors import ZeroCorpusError
from groundling.prep import run_prep


def _seed_corpus(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    return corpus


def test_run_prep_creates_prep_dir(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    assert prep_dir.parent == corpus / ".groundling-prep"
    assert (prep_dir / "sample.linearized.txt").exists()
    assert (prep_dir / "sample.chunks.json").exists()
    hint = json.loads((prep_dir / "dispatch_hint.json").read_text())
    assert hint["n_pdfs"] == 1
    assert hint["recommend"] in ("in_session", "subagent_fanout")


def test_run_prep_zero_corpus_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ZeroCorpusError):
        run_prep(empty, out_dir=None, detect_tables=False)


def test_cli_prep_prints_dir_to_stdout(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    runner = CliRunner()
    result = runner.invoke(app, ["prep", "--corpus", str(corpus), "--no-tables"])
    assert result.exit_code == 0
    # stdout is the prep dir path (single line).
    out_path = Path(result.stdout.strip())
    assert out_path.exists()
    assert (out_path / "dispatch_hint.json").exists()


def test_cli_prep_zero_corpus_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["prep", "--corpus", str(empty)])
    assert result.exit_code == 2
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_prep_orchestration.py -v
```
Expected: ImportError on `run_prep`.

**Step 3: Implement orchestration**

Append to `src/groundling/prep.py`:

```python
import datetime as dt

from groundling.agent import compute_dispatch_hint
from groundling.errors import ZeroCorpusError


DEFAULT_PREP_SUBDIR = ".groundling-prep"


def run_prep(
    corpus_dir: Path,
    *,
    out_dir: Path | None,
    detect_tables: bool,
) -> Path:
    pdfs = sorted(corpus_dir.glob("*.pdf"))
    if not pdfs:
        raise ZeroCorpusError(f"No PDFs found in {corpus_dir}")
    if out_dir is None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        out_dir = corpus_dir / DEFAULT_PREP_SUBDIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for pdf in pdfs:
        records.append(write_pdf_artifacts(
            pdf, out_dir=out_dir, detect_tables=detect_tables,
        ))

    hint = compute_dispatch_hint(records)
    hint["pdfs"] = [r["pdf_stem"] for r in records]
    (out_dir / "dispatch_hint.json").write_text(
        json.dumps(hint, indent=2)
    )
    return out_dir
```

**Step 4: Wire CLI**

Append to `src/groundling/cli.py`:

```python
@app.command()
def prep(
    corpus: Path = typer.Option(
        ..., "--corpus", exists=True, file_okay=False, dir_okay=True,
    ),
    out: Path = typer.Option(None, "--out"),
    no_tables: bool = typer.Option(
        False, "--no-tables",
        help="Skip page.find_tables() — for debugging or prose-only corpora.",
    ),
):
    """Build a prep dir from a corpus of PDFs (for agent-driven mode)."""
    from groundling.prep import run_prep
    try:
        prep_dir = run_prep(
            corpus, out_dir=out, detect_tables=not no_tables,
        )
    except ZeroCorpusError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)
    typer.echo(str(prep_dir))
```

**Step 5: Run to verify passes**

```
uv run pytest tests/test_prep_orchestration.py -v && uv run pytest tests/ -q
```
Expected: 4 new tests pass; full suite 85 passed.

**Step 6: Commit**

```
git add src/groundling/prep.py src/groundling/cli.py tests/test_prep_orchestration.py
git commit -m "feat(prep): run_prep orchestration + groundling prep CLI"
```

---

## Task 6: Markers parser

Parses the two marker forms out of agent-emitted markdown. No validation against the corpus yet — that's Task 7. Just lexing.

**Files:**
- Create: `src/groundling/markers.py`
- Create: `tests/test_markers.py`

**Step 1: Write failing tests**

```python
# tests/test_markers.py
from __future__ import annotations

from groundling.markers import Marker, parse_markers


def test_parses_pdf_chunk_marker():
    md = 'revenue was X[chunk=BYD-Q1:p2:t0r1c1 quote="170,360,448,000.00"].'
    markers = parse_markers(md)
    assert len(markers) == 1
    m = markers[0]
    assert m.kind == "pdf"
    assert m.pdf_stem == "BYD-Q1"
    assert m.chunk_id == "p2:t0r1c1"
    assert m.quote == "170,360,448,000.00"
    assert m.span_start < m.span_end
    assert md[m.span_start:m.span_end].startswith("[chunk=")


def test_parses_web_marker():
    md = 'analysts agree[url="https://example.com/x" quote="some sentence"].'
    markers = parse_markers(md)
    assert len(markers) == 1
    m = markers[0]
    assert m.kind == "web"
    assert m.url == "https://example.com/x"
    assert m.quote == "some sentence"


def test_parses_mixed_markers():
    md = ('first[chunk=A:p1:b00 quote="hi"] and second'
          '[url="https://x/" quote="bye"].')
    markers = parse_markers(md)
    assert [m.kind for m in markers] == ["pdf", "web"]


def test_quotes_with_escaped_inner_quotes():
    md = r'see [chunk=A:p1:b00 quote="he said \"yes\""] there.'
    markers = parse_markers(md)
    assert markers[0].quote == 'he said "yes"'


def test_skips_malformed_markers():
    md = "garbage [chunk=A] more [url=missing-quote] end."
    markers = parse_markers(md)
    assert markers == []
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_markers.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/markers.py
"""Marker parser for agent-emitted citation markers.

PDF marker: [chunk=<stem>:<chunk_id> quote="..."]
Web marker: [url="<url>" quote="..."]

Quotes can contain escaped double quotes (\"). Other escapes are
passed through verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Marker:
    kind: str               # "pdf" or "web"
    quote: str
    span_start: int         # offset into the source markdown
    span_end: int
    pdf_stem: str | None = None
    chunk_id: str | None = None
    url: str | None = None


# Compiled regexes. We match the brackets, then parse internals manually
# so we can handle escaped quotes inside the quote= field.
_MARKER_RE = re.compile(r"\[(?:chunk|url)=[^\[\]]*?\"(?:[^\"\\]|\\.)*\"[^\[\]]*?\]")
_CHUNK_INNER_RE = re.compile(
    r"^chunk=(?P<stem>[^:\s]+):(?P<chunk_id>[^\s]+)\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)
_URL_INNER_RE = re.compile(
    r"^url=\"(?P<url>[^\"]+)\"\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)


def _unescape(s: str) -> str:
    return s.replace(r'\"', '"').replace(r"\\", "\\")


def parse_markers(markdown: str) -> list[Marker]:
    out: list[Marker] = []
    for m in _MARKER_RE.finditer(markdown):
        inner = markdown[m.start() + 1 : m.end() - 1]  # strip [ ]
        if inner.startswith("chunk="):
            mm = _CHUNK_INNER_RE.match(inner)
            if not mm:
                continue
            out.append(Marker(
                kind="pdf",
                quote=_unescape(mm.group("quote")),
                span_start=m.start(),
                span_end=m.end(),
                pdf_stem=mm.group("stem"),
                chunk_id=mm.group("chunk_id"),
            ))
        elif inner.startswith("url="):
            mm = _URL_INNER_RE.match(inner)
            if not mm:
                continue
            out.append(Marker(
                kind="web",
                quote=_unescape(mm.group("quote")),
                span_start=m.start(),
                span_end=m.end(),
                url=mm.group("url"),
            ))
    return out
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_markers.py -v && uv run pytest tests/ -q
```
Expected: 5 passed; full suite 90 passed.

**Step 5: Commit**

```
git add src/groundling/markers.py tests/test_markers.py
git commit -m "feat(markers): parser for [chunk=...] and [url=...] markers"
```

---

## Task 7: Marker validation + chunk → spans resolution

Given a parsed Marker and the chunks.json for its PDF stem, validate (chunk exists + quote is substring) and resolve to `[{page, bbox}, ...]` via the word offset_map.

**Files:**
- Modify: `src/groundling/markers.py`
- Modify: `tests/test_markers.py`

**Step 1: Write failing tests**

Append to `tests/test_markers.py`:

```python
from groundling.markers import resolve_marker_to_spans


def _chunks_fixture():
    return [
        {"chunk_id": "p1:b00", "page": 1, "bbox": [10, 10, 200, 30],
         "word_idx_start": 0, "word_idx_end": 3,
         "text": "Hello world today"},
        {"chunk_id": "p1:t0r0c0", "page": 1, "bbox": [10, 50, 100, 70],
         "word_idx_start": 3, "word_idx_end": 4,
         "text": "Revenue"},
        {"chunk_id": "p1:t0r0c1", "page": 1, "bbox": [100, 50, 200, 70],
         "word_idx_start": 4, "word_idx_end": 5,
         "text": "170,360,448,000.00"},
    ]


def _words_fixture():
    return [
        {"content": "Hello", "page": 1, "bbox": [10, 10, 50, 30]},
        {"content": "world", "page": 1, "bbox": [55, 10, 100, 30]},
        {"content": "today", "page": 1, "bbox": [105, 10, 200, 30]},
        {"content": "Revenue", "page": 1, "bbox": [10, 50, 100, 70]},
        {"content": "170,360,448,000.00", "page": 1, "bbox": [100, 50, 200, 70]},
    ]


def test_resolve_marker_finds_quote_returns_spans():
    m = Marker(kind="pdf", quote="170,360,448,000.00",
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:t0r0c1")
    spans = resolve_marker_to_spans(m, _chunks_fixture(), _words_fixture())
    assert spans == [{"page": 1, "bbox": [100, 50, 200, 70]}]


def test_resolve_marker_unknown_chunk_returns_none():
    m = Marker(kind="pdf", quote="x",
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:bZZ")
    assert resolve_marker_to_spans(m, _chunks_fixture(), _words_fixture()) is None


def test_resolve_marker_quote_not_in_chunk_returns_none():
    m = Marker(kind="pdf", quote="not present",
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:b00")
    assert resolve_marker_to_spans(m, _chunks_fixture(), _words_fixture()) is None


def test_resolve_marker_quote_inside_block_returns_subset_of_words():
    """Quote 'world today' should resolve to the second + third word."""
    m = Marker(kind="pdf", quote="world today",
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:b00")
    spans = resolve_marker_to_spans(m, _chunks_fixture(), _words_fixture())
    assert spans == [
        {"page": 1, "bbox": [55, 10, 100, 30]},
        {"page": 1, "bbox": [105, 10, 200, 30]},
    ]
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_markers.py -v
```
Expected: ImportError on `resolve_marker_to_spans`.

**Step 3: Implement**

Append to `src/groundling/markers.py`:

```python
def _normalised(text: str) -> str:
    return " ".join(text.split())


def resolve_marker_to_spans(
    marker: Marker,
    chunks: list[dict],
    words: list[dict],
) -> list[dict] | None:
    """Look up the marker's chunk, verify the quote is a substring, and
    map the matched range to a list of {page, bbox} word entries.

    Returns None when the chunk is unknown or the quote isn't in it.
    """
    if marker.kind != "pdf":
        return None
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    chunk = chunks_by_id.get(marker.chunk_id)
    if chunk is None:
        return None

    chunk_text = chunk["text"]
    quote_norm = _normalised(marker.quote)
    text_norm = _normalised(chunk_text)
    if quote_norm not in text_norm:
        return None

    # Walk the chunk's words and find the slice whose joined text
    # contains the quote. We pick the smallest window that contains
    # the quote.
    chunk_words = words[chunk["word_idx_start"]:chunk["word_idx_end"]]
    best: tuple[int, int] | None = None
    for i in range(len(chunk_words)):
        for j in range(i + 1, len(chunk_words) + 1):
            window = _normalised(" ".join(w["content"] for w in chunk_words[i:j]))
            if quote_norm in window:
                if best is None or (j - i) < (best[1] - best[0]):
                    best = (i, j)
                break  # smallest j for this i is enough
    if best is None:
        return None
    i, j = best
    return [{"page": w["page"], "bbox": list(w["bbox"])} for w in chunk_words[i:j]]
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_markers.py -v && uv run pytest tests/ -q
```
Expected: 9 marker tests pass (5 prior + 4 new); full suite 94 passed.

**Step 5: Commit**

```
git add src/groundling/markers.py tests/test_markers.py
git commit -m "feat(markers): chunk lookup + quote substring → bbox spans"
```

---

## Task 8: Render command — orchestration

Reads agent answer, parses markers, validates, resolves to spans, generates cite HTML via v1's existing functions, rewrites markdown so each marker becomes a `[N]` reference. CLI wiring.

**Files:**
- Create: `src/groundling/render_cmd.py`
- Modify: `src/groundling/cli.py`
- Create: `tests/test_render_cmd.py`

**Step 1: Write failing tests**

```python
# tests/test_render_cmd.py
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.prep import run_prep
from groundling.render_cmd import run_render


def _seeded_prep(tmp_path, text_pdf) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    return corpus, prep_dir


def _chunk_id_from_prep(prep_dir: Path, stem: str) -> tuple[str, str]:
    chunks = json.loads((prep_dir / f"{stem}.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    return first["chunk_id"], first["text"].split()[0]  # first word as quote


def test_run_render_valid_pdf_marker_creates_cite(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'The first word is [chunk=sample:{chunk_id} quote="{quote}"] indeed.'
    )
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert "[1]" in result.markdown
    assert "(no citations" not in result.markdown
    assert (result.run_dir / "cites" / "1.html").exists()
    assert result.counters["validated"] == 1
    assert result.counters["invalid_chunk"] == 0
    assert result.counters["invalid_quote"] == 0


def test_run_render_invalid_chunk_dropped(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    answer = 'fake [chunk=sample:p99:bFF quote="x"] cite.'
    # Pair with one valid cite so we don't trigger zero-cites exit.
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer += f' real [chunk=sample:{chunk_id} quote="{quote}"] one.'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert result.counters["invalid_chunk"] == 1
    assert result.counters["validated"] == 1
    # The fake marker is gone from the rewritten markdown.
    assert "p99:bFF" not in result.markdown


def test_run_render_web_marker(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'doc [chunk=sample:{chunk_id} quote="{quote}"] and '
        'web [url="https://example.com/x" quote="cited text"].'
    )
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert "[1]" in result.markdown and "[2]" in result.markdown
    web_html = (result.run_dir / "cites" / "2.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html


def test_run_render_zero_markers_returns_zero_cites_counter(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    answer = 'no cites here.'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert result.counters["validated"] == 0


def test_cli_render_reads_answer_from_stdin(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'see [chunk=sample:{chunk_id} quote="{quote}"] here.'
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(prep_dir), "--answer", "-"], input=answer,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "[1]" in result.stdout
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_render_cmd.py -v
```
Expected: ModuleNotFoundError on `render_cmd`.

**Step 3: Implement**

```python
# src/groundling/render_cmd.py
"""groundling render: agent answer + prep dir → cite HTML + rewritten markdown."""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote as urlquote

from groundling.extract import extract_words
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_cite_pdf, render_cite_web


DEFAULT_STATE_SUBDIR = "qa-runs"


@dataclass
class RenderResult:
    run_dir: Path
    markdown: str
    counters: dict = field(default_factory=dict)


def _new_run_id(prefix: str = "render") -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    return f"{stamp}_{prefix}_{secrets.token_hex(2)}"


def _load_chunks(prep_dir: Path, stem: str) -> list[dict] | None:
    p = prep_dir / f"{stem}.chunks.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _file_url(run_dir: Path, cite_id: int) -> str:
    return f"file://{run_dir.resolve()}/cites/{cite_id}.html"


def run_render(
    *,
    prep_dir: Path,
    answer_md: str,
    state_dir: Path | None,
) -> RenderResult:
    # Default state dir is sibling to prep dir, under the corpus root.
    if state_dir is None:
        # prep_dir = <corpus>/.groundling-prep/<stamp>; state default
        # is <corpus>/qa-runs
        state_dir = prep_dir.parent.parent / DEFAULT_STATE_SUBDIR
    state_dir.mkdir(parents=True, exist_ok=True)
    run_dir = state_dir / _new_run_id()
    (run_dir / "cites").mkdir(parents=True)

    markers = parse_markers(answer_md)

    counters = {
        "validated": 0,
        "invalid_chunk": 0,
        "invalid_quote": 0,
        "invalid_url": 0,
    }

    # PDF stem → (words, chunks); load lazily, cache.
    pdf_state: dict[str, tuple[list[dict], list[dict], Path]] = {}

    def _load_pdf_state(stem: str):
        if stem in pdf_state:
            return pdf_state[stem]
        # Find pdf_path via chunks.json (no — chunks.json has just chunks).
        # Read the PDF path from dispatch_hint? It only carries stems.
        # We accept that for v1 the PDF lives next to the prep dir's
        # corpus_dir: prep_dir.parent.parent / f"{stem}.pdf".
        candidate = prep_dir.parent.parent / f"{stem}.pdf"
        if not candidate.exists():
            return None
        words = extract_words(candidate, cache_dir=None)
        chunks = _load_chunks(prep_dir, stem) or []
        pdf_state[stem] = (words, chunks, candidate)
        return pdf_state[stem]

    cite_records: list[dict] = []  # for substitution + html rendering
    next_id = 0

    for m in markers:
        if m.kind == "pdf":
            state = _load_pdf_state(m.pdf_stem)
            if state is None:
                counters["invalid_chunk"] += 1
                continue
            words, chunks, pdf_path = state
            spans = resolve_marker_to_spans(m, chunks, words)
            if spans is None:
                # Distinguish chunk-not-found from quote-not-found.
                if m.chunk_id not in {c["chunk_id"] for c in chunks}:
                    counters["invalid_chunk"] += 1
                else:
                    counters["invalid_quote"] += 1
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "pdf",
                "spans": spans, "pdf_path": pdf_path,
            })
            counters["validated"] += 1
        else:  # web
            if not (m.url and m.url.startswith(("http://", "https://"))):
                counters["invalid_url"] += 1
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "web",
            })
            counters["validated"] += 1

    # Generate HTML for each surviving cite.
    rendered_pages: dict[tuple[Path, int], int] = {}
    total = len(cite_records)
    for i, rec in enumerate(cite_records):
        cid = rec["cite_id"]
        prev_id = cite_records[i - 1]["cite_id"] if i > 0 else None
        next_id_link = cite_records[i + 1]["cite_id"] if i + 1 < total else None
        if rec["kind"] == "pdf":
            page = rec["spans"][0]["page"]
            key = (rec["pdf_path"], page)
            owner = rendered_pages.get(key)
            if owner is None:
                rendered_pages[key] = cid
                image_path = run_dir / "cites" / f"{cid}.png"
            else:
                image_path = run_dir / "cites" / f"{owner}.png"
            render_cite_pdf(
                pdf_path=rec["pdf_path"],
                out_html=run_dir / "cites" / f"{cid}.html",
                image_path=image_path,
                cite_id=cid, total=total,
                question="",
                cited_text=rec["marker"].quote,
                spans=rec["spans"],
                prev_id=prev_id, next_id=next_id_link,
            )
        else:
            from groundling.render import render_cite_web
            render_cite_web(
                out_path=run_dir / "cites" / f"{cid}.html",
                url=rec["marker"].url,
                title=rec["marker"].url,
                cited_text=rec["marker"].quote,
            )

    # Rewrite the answer markdown: replace each surviving marker with
    # [N]; drop invalid markers entirely. Walk right-to-left so offsets
    # stay valid.
    survivors = {id(r["marker"]): r["cite_id"] for r in cite_records}
    out = answer_md
    # First, drop dead markers (parsed but didn't survive).
    surviving_markers = {id(r["marker"]) for r in cite_records}
    all_marker_spans = sorted(
        ((m.span_start, m.span_end, id(m)) for m in markers),
        key=lambda t: -t[0],
    )
    for s, e, mid in all_marker_spans:
        if mid in surviving_markers:
            cite_id = survivors[mid]
            out = out[:s] + f"[{cite_id}]" + out[e:]
        else:
            out = out[:s] + out[e:]

    # Append reference block.
    if cite_records:
        refs = "\n".join(
            f"[{r['cite_id']}]: {_file_url(run_dir, r['cite_id'])}"
            for r in cite_records
        )
        out = f"{out.rstrip()}\n\n{refs}\n"

    # Write manifest.json for parity with v1's run dir shape.
    manifest = {
        "run_id": run_dir.name,
        "prep_dir": str(prep_dir.resolve()),
        "counters": counters,
        "citations": [
            {
                "cite_id": r["cite_id"],
                "source_type": r["kind"],
                "cited_text": r["marker"].quote,
                **({
                    "doc_stem": r["marker"].pdf_stem,
                    "chunk_id": r["marker"].chunk_id,
                    "spans": r["spans"],
                } if r["kind"] == "pdf" else {
                    "url": r["marker"].url,
                }),
            }
            for r in cite_records
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "answer.md").write_text(out, encoding="utf-8")

    return RenderResult(run_dir=run_dir, markdown=out, counters=counters)
```

**Step 4: Wire CLI**

Append to `src/groundling/cli.py`:

```python
@app.command()
def render(
    prep_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, dir_okay=True,
    ),
    answer: str = typer.Option(
        ..., "--answer",
        help="Path to answer markdown file, or `-` for stdin.",
    ),
    state_dir: Path = typer.Option(None, "--state-dir"),
):
    """Validate agent markers, generate cite HTML, rewrite markdown."""
    import sys
    from groundling.render_cmd import run_render
    if answer == "-":
        answer_md = sys.stdin.read()
    else:
        answer_md = Path(answer).read_text(encoding="utf-8")
    result = run_render(
        prep_dir=prep_dir, answer_md=answer_md, state_dir=state_dir,
    )
    typer.echo(result.markdown)
    parts = [f"{k}={v}" for k, v in result.counters.items()]
    typer.echo(" ".join(parts), err=True)
    if result.counters["validated"] == 0:
        raise typer.Exit(code=5)
```

**Step 5: Run to verify passes**

```
uv run pytest tests/test_render_cmd.py -v && uv run pytest tests/ -q
```
Expected: 5 new tests; full suite 99 passed.

**Step 6: Commit**

```
git add src/groundling/render_cmd.py src/groundling/cli.py tests/test_render_cmd.py
git commit -m "feat(render): validate markers → cite HTML + rewritten markdown"
```

---

## Task 9: AGENTS.md — two-mode rewrite

Rewrite the existing AGENTS.md to have a top-level branch on `ANTHROPIC_API_KEY` and describe Mode B (agent-driven) with the marker contract.

**Files:**
- Modify: `AGENTS.md`

**Step 1: Rewrite**

Replace the entire `AGENTS.md` with:

```markdown
# Grounded Q&A — groundling

This project has two modes for answering corpus questions. Pick based on
whether `ANTHROPIC_API_KEY` is set in your environment.

---

## Mode A: API-backed (when `ANTHROPIC_API_KEY` is set)

When the user asks a research question and there's a `docs/` folder of PDFs,
answer it by running:

    groundling ask --corpus docs/ "<question>"

The command prints markdown to stdout. Each cited claim is a clickable link.
Pass the markdown through to the user verbatim. PDF citations open a local
HTML page with the rendered PDF page and the cited text highlighted; web
citations (opt-in via `--web-search`) open the source URL with the cited
sentence highlighted natively by the browser.

If the user wants the answer to also draw on current web sources, add
`--web-search`. Default is docs-only.

Exit codes: 0 success, 2 no PDFs, 3 unextractable PDF (scan), 5 zero
citations.

---

## Mode B: Agent-driven (no API key, or you prefer using your subscription)

When `ANTHROPIC_API_KEY` is NOT set, or the user wants to use their Claude
subscription instead of paying per-token, answer corpus questions via
prep + render instead of `groundling ask`. The marker contract below is
mandatory: deviating breaks citation validation and produces no clickable
links.

### Step 1: prep

    groundling prep --corpus docs/

Capture stdout (the prep dir path). Read `<prep_dir>/dispatch_hint.json`.

### Step 2: dispatch decision

If `recommend == "in_session"`:
- Read each `<pdf-stem>.linearized.txt` in this session via the Read tool.
- Answer the question in your next turn, using the marker contract.

If `recommend == "subagent_fanout"`:
- For each PDF, dispatch a Task subagent. The subagent prompt template is
  in `src/groundling/agent.py` as `SUBAGENT_PROMPT_TEMPLATE`; paste it
  verbatim, filling `{pdf_path}` and `{question}`.
- Collect each subagent's marked-up per-doc answer.
- In your next turn, synthesise a final answer. **Preserve every
  `[chunk=...]` and `[url=...]` marker verbatim from the subagent
  outputs.** Do not invent new markers; do not paraphrase quoted text
  inside markers.

### Marker contract

When you cite a PDF chunk:

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim substring of the chunk"]

The chunk_id is the bracketed label in the linearized text (e.g.
`p2:b01`, `p2:t0r1c1`). The quote MUST be a verbatim substring of that
chunk's text — not paraphrased. Render-time validation drops cites where
the chunk is unknown or the quote is not found.

When you cite a web source (via your WebSearch / WebFetch tools):

    [url="https://full-url" quote="exact verbatim sentence from page"]

The quote MUST be a verbatim substring of the fetched page.

### Step 3: render

    echo "<your answer markdown>" | groundling render <prep_dir> --answer -

Render rewrites your markdown so each marker becomes a `[N]` link
pointing at a local cites/N.html. Print the rewritten markdown to the
user verbatim — that is the final answer. stderr carries
`validated=N invalid_chunk=N invalid_quote=N invalid_url=N`; consider
surfacing the counts if any cites were dropped.

Exit code 5 means zero markers survived validation — your answer is
ungrounded. Consider rephrasing or asking the user.

---

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`; prep dirs under `<corpus>/.groundling-prep/`.
Run dirs are self-contained — `tar` one to share.
```

**Step 2: Verify the full suite still passes**

```
uv run pytest tests/ -q
```
Expected: 99 passed.

**Step 3: Commit**

```
git add AGENTS.md
git commit -m "docs(agents): two-mode rewrite — API-backed + agent-driven"
```

---

## Task 10: End-to-end smoke

One integration test that drives the full prep + (hand-crafted answer) + render flow against the text_pdf fixture.

**Files:**
- Create: `tests/test_agent_mode_e2e.py`

**Step 1: Write the test**

```python
# tests/test_agent_mode_e2e.py
"""End-to-end smoke: prep → hand-crafted agent answer → render."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from groundling.prep import run_prep
from groundling.render_cmd import run_render


def test_full_agent_mode_flow(tmp_path, text_pdf):
    # 1. Seed corpus.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")

    # 2. prep.
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    linearized = (prep_dir / "sample.linearized.txt").read_text()
    chunks = json.loads((prep_dir / "sample.chunks.json").read_text())
    assert any("[sample:" in line for line in linearized.splitlines())
    assert len(chunks) >= 1

    # 3. Hand-craft an "agent answer" using the first chunk's first word
    #    as a verbatim quote.
    first = next(c for c in chunks if c["text"])
    quote = first["text"].split()[0]
    agent_answer = (
        f'The document begins with the word '
        f'[chunk=sample:{first["chunk_id"]} quote="{quote}"] '
        f'and continues with prose.'
    )

    # 4. render.
    result = run_render(
        prep_dir=prep_dir, answer_md=agent_answer, state_dir=None,
    )
    assert "[1]" in result.markdown
    assert (result.run_dir / "cites" / "1.html").exists()
    assert (result.run_dir / "cites" / "1.png").exists()
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "pdf"
    assert manifest["citations"][0]["chunk_id"] == first["chunk_id"]
    assert result.counters["validated"] == 1
```

**Step 2: Run + full suite**

```
uv run pytest tests/test_agent_mode_e2e.py -v && uv run pytest tests/ -q
```
Expected: 1 new test; full suite 100 passed.

**Step 3: Commit**

```
git add tests/test_agent_mode_e2e.py
git commit -m "test(agent-mode): e2e prep → hand-crafted answer → render"
```

---

## Out of scope (do not implement in v1 of this feature)

Mirrors the design doc's out-of-scope list:

- Real Claude Code subagent integration testing (requires live session).
- Synthesis-step quality measurement on real questions.
- Web archive snapshots of cited URLs.
- Refinekit as a hard dep.
- Multi-page chunk support (chunks are page-bounded by construction).
- A `--mode` flag on existing `ask`.
- OCR fallback in prep.
- LLM-driven verification of cited_text on the source page.
- A `groundling preview` command for deterministic prep+render testing.

---

## Done criteria

- `groundling prep --corpus DIR` writes a prep dir with one
  `<stem>.linearized.txt` per PDF (tables as markdown grids with
  `[t<i>r<r>c<c>]` IDs), matching `<stem>.chunks.json`, and a
  `dispatch_hint.json`.
- `groundling render <prep-dir> --answer FILE-or-stdin` validates
  markers, generates `cites/*.html`, rewrites markdown.
- The E2E test in Task 10 passes — prep + hand-crafted answer + render
  round-trips against a real fixture PDF.
- `pytest tests/ -q` is green; v1's 67 tests still pass; ~33 new tests
  for chunker, agent, prep, markers, render command, e2e.
- AGENTS.md has Mode A and Mode B sections.
- The CLI surface includes `groundling prep --help` and
  `groundling render --help` with documented options.
- Manual verification (outside the test suite): open Claude Code in a
  project containing the new AGENTS.md and a `docs/` folder, ask a
  question, observe the agent run prep, read the linearized text,
  emit an answer with markers, run render, and surface markdown with
  clickable `file://` citation links.
