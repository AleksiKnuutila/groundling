# groundling v1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship `groundling ask --corpus DIR "question"` — a pipx-installable CLI that answers free-form questions over a folder of PDFs with Anthropic citations, generates static HTML cite viewers with PyMuPDF-rendered pages + bbox highlights, and optionally uses Anthropic's server-side web_search tool for web citations rendered via Chrome Text Fragments.

**Architecture:** Single Python CLI, three deps (anthropic, pymupdf, jinja2), no backend. PyMuPDF extracts word-level bboxes from PDFs and rasterises cited pages. The Anthropic Messages API with citations enabled returns char-level cites into the linearized text; resolve_range maps each cite back to bbox(es) via an offset_map. At write time, the CLI generates one static HTML file per citation (PDF cites: image + sidebar; web cites: meta-redirect stub to a Text Fragments URL). Markdown answer prints to stdout for Claude Code to render.

**Tech Stack:** Python 3.11+, Typer (CLI), Anthropic SDK, PyMuPDF (fitz), Jinja2, pytest. Hatchling build backend.

**Reference design doc:** `docs/plans/2026-05-30-groundling-design.md` (on `main`).

**Reference implementation:** Many modules port from the groundswell worktree at `~/.../groundswell/.worktrees/grounded-qa/src/groundswell_ask/`. The plan calls out what to crib vs what to change. The biggest swaps: Azure DI sidecar reading → PyMuPDF extraction; FastAPI viewer → static HTML at write time; `<corpus>/.groundswell_ask/` → `<corpus>/qa-runs/`.

**Test patterns:** pytest from repo root; `pythonpath = ["src"]` in `pyproject.toml`. Tests under `tests/` as `test_<module>.py`.

---

## Task 0: Project skeleton + errors module

**Files:**
- Create: `pyproject.toml`
- Create: `src/groundling/__init__.py`
- Create: `src/groundling/errors.py`
- Create: `tests/test_smoke.py`
- Create: `tests/test_errors.py`

**Step 1: Write failing smoke test**

```python
# tests/test_smoke.py
"""Smoke test: package imports."""
import groundling


def test_package_importable():
    assert groundling.__name__ == "groundling"
```

```python
# tests/test_errors.py
"""Errors module: public exception types."""
from groundling.errors import (
    NoTextError,
    ZeroCorpusError,
    ZeroCitationsError,
)


def test_no_text_error_is_exception():
    exc = NoTextError("scan.pdf")
    assert isinstance(exc, Exception)


def test_zero_corpus_error_is_exception():
    exc = ZeroCorpusError("/empty")
    assert isinstance(exc, Exception)


def test_zero_citations_error_carries_payload(tmp_path):
    exc = ZeroCitationsError(run_dir=tmp_path, answer_md="hello\n")
    assert exc.run_dir == tmp_path
    assert exc.answer_md == "hello\n"
```

**Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_smoke.py tests/test_errors.py -v
```
Expected: `ModuleNotFoundError: No module named 'groundling'`.

**Step 3: Implement**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "groundling"
version = "0.0.1"
description = "Grounded Q&A over PDFs with clickable citation viewers."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "anthropic>=0.40",
  "pymupdf>=1.24",
  "jinja2>=3.1",
  "typer>=0.12",
  "python-dotenv>=1.0",
]

[dependency-groups]
dev = [
  "pytest>=8.0",
]

[project.scripts]
groundling = "groundling.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

`src/groundling/__init__.py`:

```python
"""groundling: grounded Q&A over PDFs with clickable citation viewers.

See docs/plans/2026-05-30-groundling-design.md for design.
"""
```

`src/groundling/errors.py`:

```python
"""Public exception types for groundling."""
from __future__ import annotations

from pathlib import Path


class NoTextError(Exception):
    """A PDF returned no extractable text (probably a scan)."""


class ZeroCorpusError(Exception):
    """Corpus directory contains no PDFs."""


class ZeroCitationsError(Exception):
    """The model returned a response but didn't cite anything."""

    def __init__(self, *, run_dir: Path, answer_md: str):
        super().__init__("Model returned no citations.")
        self.run_dir = run_dir
        self.answer_md = answer_md
```

Run `uv sync`. Note: README.md doesn't exist yet — create a one-line placeholder so Hatchling doesn't choke:

```bash
echo "# groundling" > README.md
```

(The real README comes in Task 11.)

**Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_smoke.py tests/test_errors.py -v
```
Expected: 4 passed.

**Step 5: Commit**

```
git add pyproject.toml uv.lock README.md src/groundling/__init__.py src/groundling/errors.py tests/test_smoke.py tests/test_errors.py
git commit -m "feat: package skeleton + errors module"
```

---

## Task 1: PyMuPDF word extraction + per-PDF cache

Reads a single PDF, returns the flat list of word dicts the linearizer expects. Caches results next to the PDF in `<corpus>/.groundling-cache/<stem>.json`, keyed by PDF mtime. Hard-fails on PDFs with no extractable text.

**Files:**
- Create: `src/groundling/extract.py`
- Create: `tests/test_extract.py`
- Create: `tests/fixtures/sample.pdf` (generated in setup; see Step 0 below)

**Step 0: Generate a fixture PDF**

Since we don't want to commit a binary fixture, generate it in a `conftest.py` helper. Create `tests/conftest.py`:

```python
"""Test fixtures."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    """Two-page text-native PDF with known content."""
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Hello world.\nRevenue grew 20%.")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Page two content.")
    out = tmp_path / "sample.pdf"
    doc.save(out)
    doc.close()
    return out


@pytest.fixture
def empty_pdf(tmp_path: Path) -> Path:
    """One-page PDF with no text — simulates a scan."""
    doc = fitz.open()
    doc.new_page()
    out = tmp_path / "scan.pdf"
    doc.save(out)
    doc.close()
    return out
```

**Step 1: Write failing tests**

```python
# tests/test_extract.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundling.errors import NoTextError
from groundling.extract import extract_words


def test_extract_returns_word_entries_with_bboxes(text_pdf):
    words = extract_words(text_pdf, cache_dir=None)
    assert len(words) > 0
    w = words[0]
    assert isinstance(w["content"], str)
    assert len(w["bbox"]) == 4         # x0, y0, x1, y1
    assert w["page"] >= 1


def test_extract_pages_are_1_indexed(text_pdf):
    words = extract_words(text_pdf, cache_dir=None)
    pages = {w["page"] for w in words}
    assert pages == {1, 2}


def test_empty_pdf_raises_no_text_error(empty_pdf):
    with pytest.raises(NoTextError, match="scan.pdf"):
        extract_words(empty_pdf, cache_dir=None)


def test_cache_hit_skips_reextraction(text_pdf, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    extract_words(text_pdf, cache_dir=cache_dir)
    cache_file = cache_dir / "sample.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text())
    assert payload["mtime_ns"] == text_pdf.stat().st_mtime_ns
    # Mutate cache content; second call should return mutated payload.
    payload["words"] = [{"content": "MUTATED", "bbox": [0, 0, 1, 1], "page": 1}]
    cache_file.write_text(json.dumps(payload))
    words = extract_words(text_pdf, cache_dir=cache_dir)
    assert words == [{"content": "MUTATED", "bbox": [0, 0, 1, 1], "page": 1}]


def test_cache_invalidated_on_mtime_change(text_pdf, tmp_path):
    import os
    import time
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    extract_words(text_pdf, cache_dir=cache_dir)
    # Bump PDF mtime to invalidate cache.
    future = time.time() + 10
    os.utime(text_pdf, (future, future))
    words = extract_words(text_pdf, cache_dir=cache_dir)
    # Words list is the genuine extraction, not the (untouched) cache.
    assert any(w["content"] == "Hello" or w["content"] == "Hello world." for w in words)
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_extract.py -v
```
Expected: ModuleNotFoundError on `groundling.extract`.

**Step 3: Implement**

```python
# src/groundling/extract.py
"""PyMuPDF word extraction with per-PDF cache.

Returns a flat list of word dicts:
    {"content": str, "bbox": [x0, y0, x1, y1], "page": int}

Pages are 1-indexed. Bboxes are PDF user-space points.

Cache: <cache_dir>/<pdf_stem>.json with {"mtime_ns": int, "words": [...]}.
Invalidated when PDF mtime is newer than the cached mtime.

Raises NoTextError if the PDF has no extractable text (likely a scan).
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz

from groundling.errors import NoTextError


def _read_cache(cache_path: Path, pdf_mtime_ns: int) -> list[dict] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("mtime_ns") != pdf_mtime_ns:
        return None
    return payload.get("words")


def _write_cache(cache_path: Path, pdf_mtime_ns: int, words: list[dict]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "mtime_ns": pdf_mtime_ns,
        "words": words,
    }))


def _raw_extract(pdf_path: Path) -> list[dict]:
    """Run PyMuPDF on the file; raise NoTextError if empty."""
    words: list[dict] = []
    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            # get_text("words") returns (x0, y0, x1, y1, content, block, line, word_no)
            for x0, y0, x1, y1, content, *_ in page.get_text("words"):
                words.append({
                    "content": content,
                    "bbox": [x0, y0, x1, y1],
                    "page": page_idx + 1,
                })
    if not words:
        raise NoTextError(
            f"{pdf_path.name}: no extractable text. This looks like a scanned "
            f"PDF; groundling v1 doesn't OCR. Either OCR it externally first, "
            f"or use a text-native version."
        )
    return words


def extract_words(pdf_path: Path, *, cache_dir: Path | None) -> list[dict]:
    pdf_mtime_ns = pdf_path.stat().st_mtime_ns
    if cache_dir is not None:
        cache_path = cache_dir / f"{pdf_path.stem}.json"
        cached = _read_cache(cache_path, pdf_mtime_ns)
        if cached is not None:
            return cached
        words = _raw_extract(pdf_path)
        _write_cache(cache_path, pdf_mtime_ns, words)
        return words
    return _raw_extract(pdf_path)
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_extract.py -v
```
Expected: 5 passed.

**Step 5: Commit**

```
git add src/groundling/extract.py tests/test_extract.py tests/conftest.py
git commit -m "feat: PyMuPDF word extraction + per-PDF cache"
```

---

## Task 2: Linearizer + resolve_range

Concatenates word content into flat text with single spaces; emits a sorted offset_map keyed by char ranges → `(page, bbox)`. `resolve_range` does a bisect-based lookup for citation char ranges.

**Files:**
- Create: `src/groundling/linearize.py`
- Create: `tests/test_linearize.py`

**Step 1: Write failing tests**

```python
# tests/test_linearize.py
from __future__ import annotations

from groundling.linearize import linearize_words, resolve_range


def _words(*tuples):
    """tuples of (content, page, x0, y0, x1, y1) — concise test helper."""
    return [
        {"content": c, "page": p, "bbox": [x0, y0, x1, y1]}
        for (c, p, x0, y0, x1, y1) in tuples
    ]


def test_linearize_joins_words_with_single_space():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 1, 11, 0, 25, 5),
    )
    text, entries = linearize_words(words)
    assert text == "Hello world."
    assert len(entries) == 2


def test_first_entry_starts_at_zero():
    words = _words(("Hello", 1, 0, 0, 10, 5))
    text, entries = linearize_words(words)
    assert entries[0]["char_start"] == 0
    assert entries[0]["char_end"] == len("Hello")


def test_second_entry_starts_after_separator():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 1, 11, 0, 25, 5),
    )
    text, entries = linearize_words(words)
    assert entries[1]["char_start"] == len("Hello ")
    assert entries[1]["char_end"] == len(text)


def test_entries_carry_page_and_bbox():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 2, 30, 40, 50, 45),
    )
    _, entries = linearize_words(words)
    assert entries[0]["page"] == 1
    assert entries[0]["bbox"] == [0, 0, 10, 5]
    assert entries[1]["page"] == 2
    assert entries[1]["bbox"] == [30, 40, 50, 45]


def test_empty_words_yields_empty_text():
    text, entries = linearize_words([])
    assert text == ""
    assert entries == []


# resolve_range tests --------------------------------------------------

def _fixture_entries():
    # Three entries: "Hello" [0,5), "world." [6,12), "Page two" [14,22)
    return [
        {"char_start": 0, "char_end": 5, "page": 1, "bbox": [0]*4},
        {"char_start": 6, "char_end": 12, "page": 1, "bbox": [0]*4},
        {"char_start": 14, "char_end": 22, "page": 2, "bbox": [0]*4},
    ]


def test_resolve_inside_one_entry():
    hits = resolve_range(_fixture_entries(), 1, 4)
    assert [h["char_start"] for h in hits] == [0]


def test_resolve_exact_one_entry():
    hits = resolve_range(_fixture_entries(), 0, 5)
    assert [h["char_start"] for h in hits] == [0]


def test_resolve_overlapping_two_entries():
    hits = resolve_range(_fixture_entries(), 3, 9)
    assert [h["char_start"] for h in hits] == [0, 6]


def test_resolve_separator_returns_empty():
    # Char 5 is the space between "Hello" and "world.".
    hits = resolve_range(_fixture_entries(), 5, 6)
    assert hits == []


def test_resolve_past_end_returns_empty():
    hits = resolve_range(_fixture_entries(), 500, 600)
    assert hits == []


def test_resolve_inverted_range_returns_empty():
    hits = resolve_range(_fixture_entries(), 10, 5)
    assert hits == []
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_linearize.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/linearize.py
"""Word linearization + char-range to span lookup.

linearize_words([{content, page, bbox}, ...]) -> (linearized_text, offset_map)

offset_map entries:
    {"char_start": int, "char_end": int, "page": int, "bbox": [x0, y0, x1, y1]}

Char ranges are measured against the joined text (words separated by single
spaces). Anthropic returns char_location citations with offsets into this
exact text; resolve_range maps a citation's (start, end) to the list of
overlapping entries.
"""
from __future__ import annotations

import bisect


def linearize_words(words: list[dict]) -> tuple[str, list[dict]]:
    """Return (text, offset_map). text is words joined by single spaces."""
    parts: list[str] = []
    entries: list[dict] = []
    cursor = 0
    for i, w in enumerate(words):
        content = w["content"]
        if i > 0:
            parts.append(" ")
            cursor += 1
        parts.append(content)
        entries.append({
            "char_start": cursor,
            "char_end": cursor + len(content),
            "page": w["page"],
            "bbox": list(w["bbox"]),
        })
        cursor += len(content)
    return "".join(parts), entries


def resolve_range(entries: list[dict], char_start: int, char_end: int) -> list[dict]:
    """Return entries whose [char_start, char_end) overlaps the query range.

    Entries are assumed sorted by char_start (as linearize_words returns).
    """
    if not entries or char_end <= char_start:
        return []
    starts = [e["char_start"] for e in entries]
    i = bisect.bisect_right(starts, char_start) - 1
    if i < 0:
        i = 0
    hits: list[dict] = []
    for e in entries[i:]:
        if e["char_start"] >= char_end:
            break
        if e["char_end"] > char_start:
            hits.append(e)
    return hits
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_linearize.py -v
```
Expected: 11 passed.

**Step 5: Commit**

```
git add src/groundling/linearize.py tests/test_linearize.py
git commit -m "feat: linearize + resolve_range"
```

---

## Task 3: Corpus walker

Walks `*.pdf` under a directory, calls `extract_words` + `linearize_words` per PDF, returns a list of `CorpusEntry(pdf_path, words, linearized, offset_map)`. Raises `ZeroCorpusError` if empty.

**Files:**
- Create: `src/groundling/corpus.py`
- Create: `tests/test_corpus.py`

**Step 1: Write failing tests**

```python
# tests/test_corpus.py
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from groundling.corpus import collect_corpus, CorpusEntry
from groundling.errors import ZeroCorpusError


def test_collect_single_pdf(text_pdf, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    entries = collect_corpus(corpus, cache_dir=tmp_path / "cache")
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, CorpusEntry)
    assert e.pdf_path == corpus / "sample.pdf"
    assert "Hello" in e.linearized or "world" in e.linearized
    assert len(e.offset_map) == len(e.linearized.split(" "))


def test_collect_sorted_by_name(text_pdf, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "zzz.pdf")
    shutil.copy(text_pdf, corpus / "aaa.pdf")
    entries = collect_corpus(corpus, cache_dir=tmp_path / "cache")
    names = [e.pdf_path.name for e in entries]
    assert names == ["aaa.pdf", "zzz.pdf"]


def test_empty_corpus_raises_zero_corpus_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ZeroCorpusError, match=str(empty)):
        collect_corpus(empty, cache_dir=tmp_path / "cache")
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_corpus.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/corpus.py
"""Walk a corpus directory: PDF → extracted words → linearized text + offset_map."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from groundling.errors import ZeroCorpusError
from groundling.extract import extract_words
from groundling.linearize import linearize_words


@dataclass
class CorpusEntry:
    pdf_path: Path
    words: list[dict]
    linearized: str
    offset_map: list[dict]


def collect_corpus(corpus_dir: Path, *, cache_dir: Path) -> list[CorpusEntry]:
    pdfs = sorted(corpus_dir.glob("*.pdf"))
    if not pdfs:
        raise ZeroCorpusError(f"No PDFs found in {corpus_dir}")
    entries: list[CorpusEntry] = []
    for pdf in pdfs:
        words = extract_words(pdf, cache_dir=cache_dir)
        text, offset_map = linearize_words(words)
        entries.append(CorpusEntry(
            pdf_path=pdf,
            words=words,
            linearized=text,
            offset_map=offset_map,
        ))
    return entries
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_corpus.py -v
```
Expected: 3 passed.

**Step 5: Commit**

```
git add src/groundling/corpus.py tests/test_corpus.py
git commit -m "feat: corpus walker — pdf → linearized text + offset map"
```

---

## Task 4: Anthropic API client

Wraps the Messages API call. Takes a list of `(filename, linearized_text)` tuples, a question, and a `web_search: bool`. Returns the raw response. Tests use a MagicMock — no real API contact.

**Files:**
- Create: `src/groundling/llm.py`
- Create: `tests/test_llm.py`

**Step 1: Write failing tests**

```python
# tests/test_llm.py
from __future__ import annotations

from unittest.mock import MagicMock

from groundling.llm import (
    DEFAULT_SYSTEM_PROMPT,
    ask_with_citations,
    build_documents_payload,
)


def test_build_documents_payload_shape():
    blocks = build_documents_payload([("BYD.pdf", "Hello world.")])
    assert len(blocks) == 1
    b = blocks[0]
    assert b["type"] == "document"
    assert b["source"] == {
        "type": "text", "media_type": "text/plain", "data": "Hello world.",
    }
    assert b["title"] == "BYD.pdf"
    assert b["citations"] == {"enabled": True}
    assert b["cache_control"] == {"type": "ephemeral"}


def test_build_documents_payload_preserves_order():
    blocks = build_documents_payload([("a.pdf", "AAA"), ("b.pdf", "BBB")])
    assert [b["title"] for b in blocks] == ["a.pdf", "b.pdf"]


def test_ask_with_citations_calls_client_without_tools():
    fake = MagicMock()
    fake.messages.create.return_value = "RESP"
    out = ask_with_citations(
        client=fake, model="claude-sonnet-4-6",
        docs=[("a.pdf", "AAA")], question="what?",
    )
    assert out == "RESP"
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system"] == DEFAULT_SYSTEM_PROMPT
    # No tools by default.
    assert kwargs.get("tools") in (None, [])
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[-1] == {"type": "text", "text": "what?"}


def test_ask_with_citations_adds_web_search_tool():
    fake = MagicMock()
    fake.messages.create.return_value = "RESP"
    ask_with_citations(
        client=fake, model="m", docs=[("a.pdf", "x")],
        question="q", web_search=True,
    )
    tools = fake.messages.create.call_args.kwargs.get("tools")
    assert tools and tools[0]["type"] == "web_search_20250305"
    assert tools[0]["name"] == "web_search"
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_llm.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/llm.py
"""Anthropic Messages API call with native citations + optional web_search."""
from __future__ import annotations

from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are answering questions about a set of documents.\n"
    "Cite every concrete claim back to the documents using the "
    "built-in citations feature.\n"
    "\n"
    "Block splitting for fine-grained attribution: emit each distinct "
    "factual claim — every figure, date, name, or assertion — as its "
    "own text block, attached to the citation that supports it. Use "
    "unattributed text blocks only for connective phrases that carry "
    "no factual claim. This lets each cited figure link to its exact "
    "source span instead of dragging a whole sentence with it.\n"
    "\n"
    "Prefer the shortest contiguous source range that grounds each claim "
    "— not the whole table or paragraph around it.\n"
    "Do not invent figures, names, dates, or facts not in the documents.\n"
    "Be concise."
)


def build_documents_payload(docs: list[tuple[str, str]]) -> list[dict]:
    """One document block per (filename, linearized_text). Citations enabled,
    ephemeral cache control on each block so multi-question sessions hit cache."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": text},
            "title": filename,
            "citations": {"enabled": True},
            "cache_control": {"type": "ephemeral"},
        }
        for filename, text in docs
    ]


def ask_with_citations(
    *,
    client: Any,
    model: str,
    docs: list[tuple[str, str]],
    question: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 4096,
    web_search: bool = False,
    web_search_max_uses: int = 5,
) -> Any:
    """Make the API call. Returns the raw response."""
    document_blocks = build_documents_payload(docs)
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": document_blocks + [{"type": "text", "text": question}],
        }],
    )
    if web_search:
        kwargs["tools"] = [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": web_search_max_uses,
        }]
    return client.messages.create(**kwargs)
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_llm.py -v
```
Expected: 4 passed.

**Step 5: Commit**

```
git add src/groundling/llm.py tests/test_llm.py
git commit -m "feat: anthropic messages api client with optional web_search"
```

---

## Task 5: Citation walker

Walks response.content blocks; for each citation, produces a manifest entry. `char_location` cites resolve via offset_map to a spans list; `web_search_result_location` cites carry url/title/cited_text/encrypted_index. Other types are skipped silently.

**Files:**
- Create: `src/groundling/citations.py`
- Create: `tests/test_citations.py`

**Step 1: Write failing tests**

```python
# tests/test_citations.py
from __future__ import annotations

from types import SimpleNamespace

from groundling.citations import build_manifest
from groundling.linearize import linearize_words


def _ns(**kw):
    return SimpleNamespace(**kw)


def _doc_with_offset_map():
    words = [
        {"content": "Hello", "page": 1, "bbox": [0, 0, 10, 5]},
        {"content": "world.", "page": 1, "bbox": [11, 0, 25, 5]},
    ]
    _, offset_map = linearize_words(words)
    return {
        "doc_idx": 0,
        "pdf_path": "/abs/sample.pdf",
        "offset_map": offset_map,
    }


def test_char_location_resolves_to_spans():
    response = _ns(content=[
        _ns(type="text", text="claim",
            citations=[_ns(
                type="char_location", document_index=0,
                document_title="sample.pdf", cited_text="Hello",
                start_char_index=0, end_char_index=5,
            )]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q",
        docs=[_doc_with_offset_map()],
        response=response,
    )
    assert len(manifest["citations"]) == 1
    c = manifest["citations"][0]
    assert c["cite_id"] == 1
    assert c["source_type"] == "pdf"
    assert c["doc_idx"] == 0
    assert c["char_start"] == 0
    assert c["char_end"] == 5
    assert len(c["spans"]) == 1
    assert c["spans"][0]["page"] == 1
    assert c["spans"][0]["bbox"] == [0, 0, 10, 5]


def test_web_search_citation_carries_url_and_encrypted_index():
    response = _ns(content=[
        _ns(type="text", text="claim",
            citations=[_ns(
                type="web_search_result_location",
                url="https://example.com/article",
                title="Title",
                cited_text="cited quote",
                encrypted_index="EncIdx",
            )]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[], response=response,
    )
    c = manifest["citations"][0]
    assert c["source_type"] == "web"
    assert c["url"] == "https://example.com/article"
    assert c["title"] == "Title"
    assert c["cited_text"] == "cited quote"
    assert c["encrypted_index"] == "EncIdx"


def test_mixed_pdf_and_web_citations_get_dense_1_indexed_ids():
    response = _ns(content=[
        _ns(type="text", text="claim", citations=[
            _ns(type="char_location", document_index=0,
                document_title="sample.pdf", cited_text="x",
                start_char_index=0, end_char_index=1),
            _ns(type="web_search_result_location",
                url="https://example.com/", title="t",
                cited_text="q", encrypted_index="i"),
        ]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q",
        docs=[_doc_with_offset_map()], response=response,
    )
    ids = [c["cite_id"] for c in manifest["citations"]]
    types = [c["source_type"] for c in manifest["citations"]]
    assert ids == [1, 2]
    assert types == ["pdf", "web"]


def test_non_text_blocks_ignored():
    response = _ns(content=[
        _ns(type="server_tool_use", id="srv1", name="web_search", input={}),
        _ns(type="text", text="ok", citations=None),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[], response=response,
    )
    assert manifest["citations"] == []


def test_no_citations_yields_empty_list():
    response = _ns(content=[_ns(type="text", text="hi", citations=None)])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[], response=response,
    )
    assert manifest["citations"] == []


def test_unknown_doc_idx_yields_empty_spans():
    response = _ns(content=[
        _ns(type="text", text="hi", citations=[
            _ns(type="char_location", document_index=99,
                document_title="x.pdf", cited_text="x",
                start_char_index=0, end_char_index=1),
        ]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[], response=response,
    )
    assert manifest["citations"][0]["spans"] == []
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_citations.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/citations.py
"""Walk Anthropic response content → manifest entries with resolved spans."""
from __future__ import annotations

from typing import Any

from groundling.linearize import resolve_range


def _iter_text_blocks(response: Any):
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            yield block


def _spans_for(doc: dict, char_start: int, char_end: int) -> list[dict]:
    return [dict(e) for e in resolve_range(
        doc["offset_map"], char_start, char_end,
    )]


def build_manifest(
    *,
    run_id: str,
    model: str,
    question: str,
    docs: list[dict],
    response: Any,
    web_search: bool = False,
) -> dict:
    """Build the manifest dict.

    docs is a list of {doc_idx, pdf_path, offset_map}.
    """
    docs_by_idx = {d["doc_idx"]: d for d in docs}
    citations_out: list[dict] = []
    cite_id = 0
    for block in _iter_text_blocks(response):
        for cit in getattr(block, "citations", None) or []:
            ctype = getattr(cit, "type", None)
            if ctype == "char_location":
                cite_id += 1
                doc = docs_by_idx.get(cit.document_index)
                spans = _spans_for(doc, cit.start_char_index, cit.end_char_index) if doc else []
                citations_out.append({
                    "cite_id": cite_id,
                    "source_type": "pdf",
                    "doc_idx": cit.document_index,
                    "char_start": cit.start_char_index,
                    "char_end": cit.end_char_index,
                    "cited_text": cit.cited_text,
                    "spans": spans,
                })
            elif ctype == "web_search_result_location":
                cite_id += 1
                citations_out.append({
                    "cite_id": cite_id,
                    "source_type": "web",
                    "url": getattr(cit, "url", ""),
                    "title": getattr(cit, "title", ""),
                    "cited_text": getattr(cit, "cited_text", ""),
                    "encrypted_index": getattr(cit, "encrypted_index", ""),
                })
            # Other types silently skipped.
    # Strip offset_map from docs before persistence — only doc_idx and
    # pdf_path are needed by the viewer.
    docs_for_manifest = [
        {"doc_idx": d["doc_idx"], "pdf_path": d["pdf_path"]}
        for d in docs
    ]
    return {
        "run_id": run_id,
        "model": model,
        "question": question,
        "web_search": web_search,
        "docs": docs_for_manifest,
        "citations": citations_out,
    }
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_citations.py -v
```
Expected: 6 passed.

**Step 5: Commit**

```
git add src/groundling/citations.py tests/test_citations.py
git commit -m "feat: citation walker — char_location + web_search_result_location"
```

---

## Task 6: Markdown formatter

Concatenates response.content text blocks; appends `[N]` markers at the end of each cited block; emits reference-style `[N]: URL` at the bottom. Whitespace-safety check inserts a space between adjacent blocks. PDF cites → `file://run_dir/cites/N.html`; web cites → same shape (the redirect stub in Task 8 does the dispatch).

**Files:**
- Create: `src/groundling/markdown.py`
- Create: `tests/test_markdown.py`

**Step 1: Write failing tests**

```python
# tests/test_markdown.py
from __future__ import annotations

from types import SimpleNamespace

from groundling.markdown import format_answer


def _ns(**kw):
    return SimpleNamespace(**kw)


def test_plain_text_passes_through():
    response = _ns(content=[_ns(type="text", text="Hello.", citations=None)])
    md = format_answer(response, manifest={"citations": []},
                       cite_url_for=lambda c: "")
    assert md.strip() == "Hello."


def test_cited_block_gets_trailing_marker():
    response = _ns(content=[
        _ns(type="text", text="Revenue grew 20%.",
            citations=[_ns(type="char_location", document_index=0,
                           document_title="d.pdf", cited_text="source quote",
                           start_char_index=0, end_char_index=12)]),
    ])
    manifest = {"citations": [{
        "cite_id": 1, "source_type": "pdf", "doc_idx": 0,
        "char_start": 0, "char_end": 12,
        "cited_text": "source quote", "spans": [],
    }]}
    md = format_answer(
        response, manifest=manifest,
        cite_url_for=lambda c: f"file:///run/cites/{c['cite_id']}.html",
    )
    assert "Revenue grew 20%.[1]" in md
    assert "[1]: file:///run/cites/1.html" in md


def test_multiple_blocks_concatenate_with_separator_safety():
    """When adjacent text blocks both lack separating whitespace, insert
    a single space to avoid running them together."""
    response = _ns(content=[
        _ns(type="text", text="ABC", citations=None),
        _ns(type="text", text="DEF", citations=None),
    ])
    md = format_answer(
        response, manifest={"citations": []}, cite_url_for=lambda c: "",
    )
    # Either contiguous (if model emitted no break) or space-separated
    # by our safety check. We require the safety check to add the space.
    assert "ABC DEF" in md


def test_block_ending_in_whitespace_does_not_get_extra_space():
    response = _ns(content=[
        _ns(type="text", text="ABC ", citations=None),
        _ns(type="text", text="DEF", citations=None),
    ])
    md = format_answer(
        response, manifest={"citations": []}, cite_url_for=lambda c: "",
    )
    # Only one space between ABC and DEF.
    assert "ABC DEF" in md
    assert "ABC  DEF" not in md


def test_multi_citation_block_emits_dense_markers():
    response = _ns(content=[
        _ns(type="text", text="A and B.", citations=[
            _ns(type="char_location", document_index=0,
                document_title="d.pdf", cited_text="qA",
                start_char_index=0, end_char_index=2),
            _ns(type="char_location", document_index=0,
                document_title="d.pdf", cited_text="qB",
                start_char_index=10, end_char_index=12),
        ]),
    ])
    manifest = {"citations": [
        {"cite_id": 1, "source_type": "pdf", "doc_idx": 0,
         "char_start": 0, "char_end": 2, "cited_text": "qA", "spans": []},
        {"cite_id": 2, "source_type": "pdf", "doc_idx": 0,
         "char_start": 10, "char_end": 12, "cited_text": "qB", "spans": []},
    ]}
    md = format_answer(
        response, manifest=manifest,
        cite_url_for=lambda c: f"file:///run/cites/{c['cite_id']}.html",
    )
    assert "A and B.[1][2]" in md
    assert "[1]: file:///run/cites/1.html" in md
    assert "[2]: file:///run/cites/2.html" in md


def test_empty_response_returns_empty_string():
    response = _ns(content=[])
    md = format_answer(
        response, manifest={"citations": []}, cite_url_for=lambda c: "",
    )
    assert md == ""


def test_content_none_returns_empty_string():
    response = _ns(content=None)
    md = format_answer(
        response, manifest={"citations": []}, cite_url_for=lambda c: "",
    )
    assert md == ""
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_markdown.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/markdown.py
"""Concatenate response.content text blocks + append [N] markers per
cited block + emit reference-style [N]: url at the bottom."""
from __future__ import annotations

from typing import Any, Callable


def _annotate_text_block(text: str, cite_ids: list[int]) -> str:
    """Append [N] markers at end of `text`. cite_ids is dense + ordered."""
    if not cite_ids:
        return text
    markers = "".join(f"[{cid}]" for cid in cite_ids)
    return text.rstrip() + markers


def _concat_with_separator_safety(blocks: list[str]) -> str:
    out: list[str] = []
    for t in blocks:
        if not t:
            continue
        if out and out[-1] and not out[-1][-1].isspace() and not t[0].isspace():
            out.append(" ")
        out.append(t)
    return "".join(out)


def _match_block_citations_to_manifest(
    block: Any, manifest_cites: list[dict],
) -> list[int]:
    """Return cite_ids (manifest) corresponding to this block's citations."""
    ids: list[int] = []
    for cit in getattr(block, "citations", None) or []:
        ctype = getattr(cit, "type", None)
        if ctype == "char_location":
            for mc in manifest_cites:
                if (
                    mc.get("source_type", "pdf") == "pdf"
                    and mc.get("doc_idx") == cit.document_index
                    and mc.get("char_start") == cit.start_char_index
                    and mc.get("char_end") == cit.end_char_index
                ):
                    ids.append(mc["cite_id"])
                    break
        elif ctype == "web_search_result_location":
            for mc in manifest_cites:
                if (
                    mc.get("source_type") == "web"
                    and mc.get("url") == getattr(cit, "url", None)
                    and mc.get("encrypted_index") == getattr(cit, "encrypted_index", None)
                ):
                    ids.append(mc["cite_id"])
                    break
    return ids


def format_answer(
    response: Any,
    *,
    manifest: dict,
    cite_url_for: Callable[[dict], str],
) -> str:
    """Return reference-style markdown.

    cite_url_for(manifest_citation_dict) -> URL string. Lets the caller
    decide the URL scheme (file:// for local cites HTML, or anything else).
    """
    manifest_cites = manifest.get("citations", [])
    cites_by_id = {c["cite_id"]: c for c in manifest_cites}

    annotated_blocks: list[str] = []
    cited_ids_in_order: list[int] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "text":
            continue
        block_ids = _match_block_citations_to_manifest(block, manifest_cites)
        cited_ids_in_order.extend(block_ids)
        annotated_blocks.append(_annotate_text_block(block.text, block_ids))

    body = _concat_with_separator_safety(annotated_blocks)

    # Reference list at the bottom, sorted by cite_id, dedup'd.
    seen: set[int] = set()
    ref_lines: list[str] = []
    for cid in sorted(cited_ids_in_order):
        if cid in seen:
            continue
        seen.add(cid)
        c = cites_by_id.get(cid)
        if c is None:
            continue
        ref_lines.append(f"[{cid}]: {cite_url_for(c)}")
    if ref_lines:
        return f"{body}\n\n" + "\n".join(ref_lines) + "\n"
    return body
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_markdown.py -v
```
Expected: 7 passed.

**Step 5: Commit**

```
git add src/groundling/markdown.py tests/test_markdown.py
git commit -m "feat: markdown formatter — block-trailing cite markers + ref list"
```

---

## Task 7: PDF page rendering + cite-page dedupe

Rasterises a single PDF page to PNG at 2× scale; tracks (pdf_path, page) → output filename so callers can dedupe.

**Files:**
- Create: `src/groundling/render.py`
- Create: `tests/test_render_page.py`

**Step 1: Write failing tests**

```python
# tests/test_render_page.py
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
    img = fitz.open(out)
    assert img[0].rect.width == width_px
    assert img[0].rect.height == height_px
    img.close()


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
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_render_page.py -v
```
Expected: ModuleNotFoundError on `render`.

**Step 3: Implement**

```python
# src/groundling/render.py
"""Static-HTML cite viewer generation.

Two responsibilities (split across helpers):

1. Rasterise a PDF page to PNG (render_pdf_page).
2. Generate per-cite HTML files (render_cite_html and render_web_redirect,
   added in later tasks).
"""
from __future__ import annotations

from pathlib import Path

import fitz


def render_pdf_page(
    pdf_path: Path,
    *,
    page: int,
    out_path: Path,
    scale: float = 2.0,
) -> tuple[int, int]:
    """Rasterise `pdf_path` page `page` (1-indexed) to PNG at `out_path`.

    Returns (width_px, height_px) — the dimensions of the saved PNG.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        pdf_page = doc.load_page(page - 1)
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        pix.save(out_path)
        return pix.width, pix.height
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_render_page.py -v
```
Expected: 2 passed.

**Step 5: Commit**

```
git add src/groundling/render.py tests/test_render_page.py
git commit -m "feat: PDF page rendering via PyMuPDF at 2x scale"
```

---

## Task 8: Cite HTML generation (PDF + web stub) + Jinja templates

PDF cite: image + sidebar + prev/next nav, with bbox highlight overlays. Web cite: 5-line meta-redirect stub. Uses Jinja for both. URL building (Text Fragments) handled by helpers.

**Files:**
- Create: `src/groundling/templates/cite_pdf.html.j2`
- Create: `src/groundling/templates/cite_web.html.j2`
- Modify: `src/groundling/render.py`
- Create: `tests/test_render_html.py`

**Step 1: Add templates**

`src/groundling/templates/cite_pdf.html.j2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Citation {{ cite_id }} · {{ question }}</title>
<style>
  body { display: flex; font: 14px/1.4 system-ui, sans-serif; margin: 0; color: #222; }
  .sidebar { width: 320px; padding: 20px; border-right: 1px solid #ddd; background: #fafafa; box-sizing: border-box; flex-shrink: 0; }
  .sidebar .eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.6; }
  .sidebar h3 { font-size: 13px; margin: 16px 0 4px; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7; }
  .sidebar p, .sidebar blockquote { margin: 4px 0 0; font-size: 14px; }
  .sidebar blockquote { padding: 8px 12px; border-left: 3px solid #ccc; background: #fff; }
  .sidebar .source { opacity: 0.6; font-size: 12px; margin-top: 12px; }
  .nav { margin-top: 24px; display: flex; gap: 8px; }
  .nav a { padding: 4px 10px; border: 1px solid #ccc; text-decoration: none; color: #444; background: #fff; border-radius: 3px; font-size: 13px; }
  .nav a:hover { background: #eee; }
  .page-wrap { position: relative; padding: 20px; }
  .page-wrap img { display: block; box-shadow: 0 1px 6px rgba(0,0,0,0.15); }
  .highlight { position: absolute; background: rgba(255, 235, 0, 0.35); border: 1px solid rgba(200, 160, 0, 0.6); pointer-events: none; }
</style>
</head>
<body>
<aside class="sidebar">
  <div class="eyebrow">Citation {{ cite_id }} / {{ total }}</div>
  <h3>Question</h3>
  <p>{{ question }}</p>
  <h3>Cited text</h3>
  <blockquote>{{ cited_text }}</blockquote>
  <p class="source">{{ pdf_filename }}, page {{ page }}</p>
  <div class="nav">
    {% if prev_id %}<a href="{{ prev_id }}.html">&larr; prev</a>{% endif %}
    {% if next_id %}<a href="{{ next_id }}.html">next &rarr;</a>{% endif %}
  </div>
</aside>
<div class="page-wrap">
  <img src="{{ image_filename }}" width="{{ image_w }}" height="{{ image_h }}">
  {% for h in highlights %}
  <div class="highlight" style="left: {{ h.left }}px; top: {{ h.top }}px; width: {{ h.width }}px; height: {{ h.height }}px;"></div>
  {% endfor %}
</div>
</body>
</html>
```

`src/groundling/templates/cite_web.html.j2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0;url={{ fragment_url }}">
<title>{{ title }}</title>
</head>
<body>
<p>Redirecting to <a href="{{ fragment_url }}">{{ title }}</a>&hellip;</p>
</body>
</html>
```

**Step 2: Write failing tests**

```python
# tests/test_render_html.py
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
```

**Step 3: Run to verify failure**

```
uv run pytest tests/test_render_html.py -v
```
Expected: ImportError on `build_text_fragment_url`, `render_cite_pdf`, `render_cite_web`.

**Step 4: Implement**

Append to `src/groundling/render.py`:

```python
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _strip_trailing_ellipsis(s: str) -> str:
    s = s.rstrip()
    for sentinel in ("…", "..."):
        if s.endswith(sentinel):
            s = s[: -len(sentinel)].rstrip()
            break
    return s


def build_text_fragment_url(url: str, cited_text: str) -> str:
    needle = _strip_trailing_ellipsis(cited_text)
    return f"{url}#:~:text={quote(needle, safe='')}"


def render_cite_web(
    *,
    out_path: Path,
    url: str,
    title: str,
    cited_text: str,
) -> None:
    fragment_url = build_text_fragment_url(url, cited_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    template = _env.get_template("cite_web.html.j2")
    out_path.write_text(template.render(
        title=title,
        fragment_url=fragment_url,
    ))


def _build_highlights(
    spans: list[dict],
    *,
    scale: float,
    canvas_padding_px: int = 0,
) -> list[dict]:
    """Convert (page, bbox) spans into pixel-space rectangles for the
    HTML overlay. Caller already filtered to one page."""
    highlights = []
    for s in spans:
        x0, y0, x1, y1 = s["bbox"]
        highlights.append({
            "left": x0 * scale + canvas_padding_px,
            "top": y0 * scale + canvas_padding_px,
            "width": (x1 - x0) * scale,
            "height": (y1 - y0) * scale,
        })
    return highlights


def render_cite_pdf(
    *,
    pdf_path: Path,
    out_html: Path,
    image_path: Path,
    cite_id: int,
    total: int,
    question: str,
    cited_text: str,
    spans: list[dict],
    prev_id: int | None,
    next_id: int | None,
    scale: float = 2.0,
) -> None:
    """Render the cited PDF page to PNG (if not present) and write the
    HTML viewer that references it.

    Highlights all spans on the page of the first span. If spans cross
    pages we render the first span's page and overlay only same-page
    spans — multi-page citations are rare for v1; revisit if needed.
    """
    if not spans:
        return
    first_page = spans[0]["page"]
    page_spans = [s for s in spans if s["page"] == first_page]

    # Render page image only if it doesn't already exist (caller may dedupe).
    if not image_path.exists():
        width_px, height_px = render_pdf_page(
            pdf_path, page=first_page, out_path=image_path, scale=scale,
        )
    else:
        # Re-derive dimensions for the HTML <img>.
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(first_page - 1)
            width_px = int(page.rect.width * scale)
            height_px = int(page.rect.height * scale)

    highlights = _build_highlights(page_spans, scale=scale)
    template = _env.get_template("cite_pdf.html.j2")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(template.render(
        cite_id=cite_id,
        total=total,
        question=question,
        cited_text=cited_text,
        pdf_filename=pdf_path.name,
        page=first_page,
        image_filename=image_path.name,
        image_w=width_px,
        image_h=height_px,
        highlights=highlights,
        prev_id=prev_id,
        next_id=next_id,
    ))
```

Also: hatchling needs to know to include `templates/*.j2` in the package. Edit `pyproject.toml` and add at the end:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/groundling"]

[tool.hatch.build.targets.wheel.shared-data]
"src/groundling/templates" = "groundling/templates"
```

Actually simpler — hatchling automatically includes files inside `src/<pkg>/` when `packages` is configured. Just add:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/groundling"]
```

Templates under `src/groundling/templates/` will be included automatically.

**Step 5: Run to verify passes**

```
uv run pytest tests/test_render_html.py -v
```
Expected: 6 passed.

**Step 6: Commit**

```
git add src/groundling/render.py src/groundling/templates/ tests/test_render_html.py pyproject.toml
git commit -m "feat: jinja templates + cite HTML generation (PDF + web stub)"
```

---

## Task 9: Run dir writer with timestamp + slug naming

Creates `<state_dir>/<utc-timestamp>_<question-slug>/` containing `question.txt`, `manifest.json`, `response.json`. Slug derived from the question. Hex fallback on empty slug.

**Files:**
- Create: `src/groundling/run.py`
- Create: `tests/test_run.py`

**Step 1: Write failing tests**

```python
# tests/test_run.py
from __future__ import annotations

import json
import re

from groundling.run import slugify_question, write_run_dir


def test_slugify_normal_question():
    assert slugify_question("What was BYD's Q1 2025 revenue?") == "what-byd-q1-2025-revenue"


def test_slugify_strips_punctuation_and_lowercases():
    assert slugify_question("Hello, World!") == "hello-world"


def test_slugify_caps_length():
    long_q = "a " * 200
    out = slugify_question(long_q)
    assert len(out) <= 50


def test_slugify_empty_falls_back_to_hex():
    out = slugify_question("???   ")
    assert re.fullmatch(r"[0-9a-f]{6}", out)


def test_write_run_dir_creates_files(tmp_path):
    state = tmp_path / "qa-runs"
    state.mkdir()
    docs = [{"doc_idx": 0, "pdf_path": "/abs/a.pdf"}]
    manifest = {
        "run_id": "ignored",
        "model": "m", "question": "q", "web_search": False,
        "docs": docs, "citations": [],
    }
    run_dir = write_run_dir(
        state_dir=state,
        question="what is X?",
        manifest=manifest,
        response_json={"raw": True},
    )
    assert run_dir.parent == state
    assert (run_dir / "question.txt").read_text() == "what is X?"
    persisted = json.loads((run_dir / "manifest.json").read_text())
    assert persisted["run_id"] == run_dir.name
    assert (run_dir / "response.json").exists()
    assert (run_dir / "cites").is_dir()


def test_write_run_dir_unique_run_ids(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    r1 = write_run_dir(
        state_dir=state, question="same question",
        manifest={"citations": []}, response_json={},
    )
    r2 = write_run_dir(
        state_dir=state, question="same question",
        manifest={"citations": []}, response_json={},
    )
    assert r1 != r2


def test_run_dir_name_starts_with_timestamp(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    run = write_run_dir(
        state_dir=state, question="hi",
        manifest={"citations": []}, response_json={},
    )
    # Timestamp pattern YYYY-MM-DDTHH-MM-SS
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_", run.name)
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_run.py -v
```
Expected: ModuleNotFoundError.

**Step 3: Implement**

```python
# src/groundling/run.py
"""Persist one Q&A run to disk: question.txt, manifest.json, response.json + cites/ dir."""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
from pathlib import Path


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "of", "on", "or", "that", "the",
    "to", "was", "were", "what", "which", "who", "with",
}


def slugify_question(question: str, *, max_len: int = 50) -> str:
    """Build a short slug from a question for run-dir naming."""
    # Lowercase, replace non-alphanum with spaces, split, drop stopwords,
    # keep first 5–6 tokens, join with hyphens, cap length.
    cleaned = re.sub(r"[^\w\s]", " ", question.lower())
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS]
    # Drop "what" specifically only when it's the leading token.
    if tokens and tokens[0] == "what":
        tokens = tokens[1:]
    slug = "-".join(tokens[:6])
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    if not slug:
        slug = secrets.token_hex(3)
    return slug


def _new_run_id(question: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    slug = slugify_question(question)
    return f"{stamp}_{slug}"


def write_run_dir(
    *,
    state_dir: Path,
    question: str,
    manifest: dict,
    response_json: dict,
) -> Path:
    run_id = _new_run_id(question)
    run_dir = state_dir / run_id
    # Collide-safety: if the same timestamp+slug somehow exists, suffix with hex.
    if run_dir.exists():
        run_id = f"{run_id}_{secrets.token_hex(2)}"
        run_dir = state_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "cites").mkdir()
    manifest = dict(manifest)
    manifest["run_id"] = run_id
    (run_dir / "question.txt").write_text(question, encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "response.json").write_text(json.dumps(response_json, indent=2))
    return run_dir
```

Look at the stopwords test (`what was BYD's…`). My slugify drops `was`, `at`, etc. and the leading `what`. The remaining tokens are `byd`, `s`, `q1`, `2025`, `revenue` — wait, `byd's` after `re.sub(r"[^\w\s]", " ", …)` becomes `byd s` (apostrophe replaced by space). Token list: `byd`, `s`, `q1`, `2025`, `revenue`. Joined with `-`: `byd-s-q1-2025-revenue`. The test expects `what-byd-q1-2025-revenue` — but `what` is dropped. The test is wrong as written.

**Fix the test before implementing**:

```python
def test_slugify_normal_question():
    # "What" is dropped as a leading question word, "was" as a stopword,
    # "'s" splits into a tiny token kept as part of the slug.
    assert slugify_question("What was BYD's Q1 2025 revenue?") == "byd-s-q1-2025-revenue"
```

**Step 4: Run to verify passes**

```
uv run pytest tests/test_run.py -v
```
Expected: 6 passed.

**Step 5: Commit**

```
git add src/groundling/run.py tests/test_run.py
git commit -m "feat: run dir writer with timestamp + question slug"
```

---

## Task 10: Orchestration + Typer CLI

Wires everything: corpus → linearize → API call → manifest → markdown → run dir → render cite HTMLs. Maps exceptions to exit codes. The `groundling ask` Typer subcommand calls `run_ask` and prints the markdown to stdout.

**Files:**
- Create: `src/groundling/orchestration.py`
- Create: `src/groundling/cli.py`
- Create: `tests/test_orchestration.py`

**Step 1: Write failing tests**

```python
# tests/test_orchestration.py
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.errors import ZeroCorpusError, ZeroCitationsError
from groundling.orchestration import run_ask


def _ns(**kw):
    return SimpleNamespace(**kw)


def _seed_corpus(tmp_path, text_pdf) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    return corpus


def _fake_pdf_citation_response():
    """A response with one PDF citation and one cited text block."""
    return _ns(content=[
        _ns(type="text", text="The first page says ", citations=None),
        _ns(type="text", text="Hello", citations=[_ns(
            type="char_location", document_index=0,
            document_title="sample.pdf", cited_text="some source quote",
            start_char_index=0, end_char_index=5,
        )]),
        _ns(type="text", text=".", citations=None),
    ])


def test_run_ask_writes_run_dir_and_cite_html(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_pdf_citation_response()

    result = run_ask(
        corpus_dir=corpus,
        question="what does the first page say?",
        client=fake_client,
    )
    assert result.run_dir.parent == corpus / "qa-runs"
    # Markdown trails the cited block with [1] and lists the file:// ref.
    assert "[1]" in result.answer_md
    assert f"file://{result.run_dir.resolve()}/cites/1.html" in result.answer_md
    # The cite HTML and the page image both exist on disk.
    assert (result.run_dir / "cites" / "1.html").exists()
    assert (result.run_dir / "cites" / "1.png").exists()
    # Manifest written and consistent with the markdown.
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "pdf"


def test_run_ask_zero_corpus_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    fake_client = MagicMock()
    with pytest.raises(ZeroCorpusError):
        run_ask(corpus_dir=empty, question="q", client=fake_client)


def test_run_ask_zero_citations_raises_with_run_dir_and_md(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _ns(content=[
        _ns(type="text", text="No citations here.", citations=None),
    ])
    with pytest.raises(ZeroCitationsError) as ei:
        run_ask(corpus_dir=corpus, question="q", client=fake_client)
    assert ei.value.run_dir.exists()
    assert "No citations here." in ei.value.answer_md


def test_run_ask_web_search_citation_lands_in_manifest(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _ns(content=[
        _ns(type="text", text="Analysts agree.", citations=[_ns(
            type="web_search_result_location",
            url="https://example.com/x", title="X",
            cited_text="some quote", encrypted_index="EncIdx",
        )]),
    ])
    result = run_ask(
        corpus_dir=corpus, question="q",
        web_search=True, client=fake_client,
    )
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "web"
    # Web cite HTML is a redirect stub.
    web_html = (result.run_dir / "cites" / "1.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html


# --- CLI integration -----------------------------------------------------

def test_cli_zero_corpus_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["ask", "q", "--corpus", str(empty)])
    assert result.exit_code == 2
```

**Step 2: Run to verify failure**

```
uv run pytest tests/test_orchestration.py -v
```
Expected: ModuleNotFoundError on `groundling.cli` / `groundling.orchestration`.

**Step 3: Implement orchestration**

```python
# src/groundling/orchestration.py
"""Top-level orchestration for `groundling ask`."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from groundling.citations import build_manifest
from groundling.corpus import collect_corpus
from groundling.errors import ZeroCitationsError
from groundling.llm import ask_with_citations
from groundling.markdown import format_answer
from groundling.render import (
    build_text_fragment_url,
    render_cite_pdf,
    render_cite_web,
)
from groundling.run import write_run_dir


DEFAULT_STATE_SUBDIR = "qa-runs"
DEFAULT_CACHE_SUBDIR = ".groundling-cache"


@dataclass
class AskResult:
    run_dir: Path
    answer_md: str


def _response_to_jsonable(response: Any) -> dict:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return {"_repr": repr(response)}


def _file_url_for(run_dir: Path) -> "callable":
    """Return a cite_url_for callable bound to this run dir."""
    abs_run = run_dir.resolve()
    def url_for(c: dict) -> str:
        # Uniform file:// link target for all cites. Web cites get the
        # redirect stub written to cites/N.html.
        return f"file://{abs_run}/cites/{c['cite_id']}.html"
    return url_for


def _render_cites(
    *,
    run_dir: Path,
    docs_by_idx: dict[int, "CorpusEntry"],
    manifest: dict,
    question: str,
) -> None:
    """Write cites/N.html (+ N.png for PDF cites) for every manifest citation.

    Deduplicates page renders within a run: when two cites land on the same
    (pdf_path, page), the PNG is rendered once and reused.
    """
    cites = manifest["citations"]
    total = len(cites)
    # (pdf_path, page) → first cite_id whose PNG owns this page.
    rendered_pages: dict[tuple[Path, int], int] = {}
    for i, c in enumerate(cites):
        cite_id = c["cite_id"]
        prev_id = cites[i - 1]["cite_id"] if i > 0 else None
        next_id = cites[i + 1]["cite_id"] if i + 1 < total else None
        if c["source_type"] == "pdf":
            entry = docs_by_idx[c["doc_idx"]]
            page = c["spans"][0]["page"] if c["spans"] else 1
            key = (entry.pdf_path, page)
            owner_cite = rendered_pages.get(key)
            if owner_cite is None:
                rendered_pages[key] = cite_id
                image_path = run_dir / "cites" / f"{cite_id}.png"
            else:
                image_path = run_dir / "cites" / f"{owner_cite}.png"
            render_cite_pdf(
                pdf_path=entry.pdf_path,
                out_html=run_dir / "cites" / f"{cite_id}.html",
                image_path=image_path,
                cite_id=cite_id,
                total=total,
                question=question,
                cited_text=c["cited_text"],
                spans=c["spans"],
                prev_id=prev_id,
                next_id=next_id,
            )
        else:  # web
            render_cite_web(
                out_path=run_dir / "cites" / f"{cite_id}.html",
                url=c["url"],
                title=c.get("title") or c["url"],
                cited_text=c["cited_text"],
            )


def run_ask(
    *,
    corpus_dir: Path,
    question: str,
    model: str = "claude-sonnet-4-6",
    state_dir: Path | None = None,
    cache_dir: Path | None = None,
    web_search: bool = False,
    client: Any = None,
) -> AskResult:
    state = state_dir or (corpus_dir / DEFAULT_STATE_SUBDIR)
    cache = cache_dir or (corpus_dir / DEFAULT_CACHE_SUBDIR)
    state.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    entries = collect_corpus(corpus_dir, cache_dir=cache)
    docs_payload = [(e.pdf_path.name, e.linearized) for e in entries]
    docs_for_manifest = [
        {"doc_idx": i, "pdf_path": str(e.pdf_path.resolve()),
         "offset_map": e.offset_map}
        for i, e in enumerate(entries)
    ]
    docs_by_idx = {i: e for i, e in enumerate(entries)}

    if client is None:
        from anthropic import Anthropic
        from dotenv import load_dotenv
        load_dotenv()
        client = Anthropic()

    response = ask_with_citations(
        client=client, model=model, docs=docs_payload,
        question=question, web_search=web_search,
    )

    manifest = build_manifest(
        run_id="pending", model=model, question=question,
        docs=docs_for_manifest, response=response,
        web_search=web_search,
    )
    run_dir = write_run_dir(
        state_dir=state, question=question,
        manifest=manifest, response_json=_response_to_jsonable(response),
    )
    # Re-read manifest because write_run_dir rewrote run_id.
    persisted = json.loads((run_dir / "manifest.json").read_text())

    # Render per-cite HTML files (and PDF page PNGs).
    _render_cites(
        run_dir=run_dir,
        docs_by_idx=docs_by_idx,
        manifest=persisted,
        question=question,
    )

    # Build the stdout markdown — file:// URLs into cites/.
    answer_md = format_answer(
        response, manifest=persisted,
        cite_url_for=_file_url_for(run_dir),
    )
    if len(persisted["citations"]) == 0:
        raise ZeroCitationsError(run_dir=run_dir, answer_md=answer_md)
    return AskResult(run_dir=run_dir, answer_md=answer_md)
```

**Step 4: Implement CLI**

```python
# src/groundling/cli.py
"""Typer entry point: groundling ask "..." --corpus DIR [--web-search]"""
from __future__ import annotations

from pathlib import Path

import typer

from groundling.errors import (
    NoTextError,
    ZeroCitationsError,
    ZeroCorpusError,
)


app = typer.Typer(help="Grounded Q&A over a folder of PDFs.")


@app.command()
def ask(
    question: str = typer.Argument(..., help="The question to ask."),
    corpus: Path = typer.Option(
        ..., "--corpus", exists=True, file_okay=False, dir_okay=True,
        help="Directory of PDFs to ground the answer in.",
    ),
    model: str = typer.Option("claude-sonnet-4-6", "--model"),
    state_dir: Path = typer.Option(None, "--state-dir"),
    cache_dir: Path = typer.Option(None, "--cache-dir"),
    web_search: bool = typer.Option(
        False, "--web-search",
        help="Enable Anthropic server-side web_search tool.",
    ),
):
    """Answer a free-form question over a folder of PDFs with citations."""
    from groundling.orchestration import run_ask
    try:
        result = run_ask(
            corpus_dir=corpus,
            question=question,
            model=model,
            state_dir=state_dir,
            cache_dir=cache_dir,
            web_search=web_search,
        )
    except ZeroCorpusError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)
    except NoTextError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=3)
    except ZeroCitationsError as exc:
        typer.echo(exc.answer_md)
        typer.echo("(no citations returned)", err=True)
        raise typer.Exit(code=5)
    typer.echo(result.answer_md)
```

Note exit code 4 (Anthropic API failure) isn't wired in v1 — uncaught exceptions still propagate as exit 1; document this in the README. Wire when SDK exception types are pinned.

**Step 5: Run to verify passes**

```
uv run pytest tests/test_orchestration.py -v
```
Expected: 5 passed.

**Step 6: Run the full suite**

```
uv run pytest tests/ -q
```
Expected: all tests pass.

**Step 7: Smoke-test the CLI registers**

```
uv run groundling ask --help
```
Expected: Typer help screen with `--corpus`, `--model`, `--state-dir`, `--cache-dir`, `--web-search` options.

**Step 8: Commit**

```
git add src/groundling/orchestration.py src/groundling/cli.py tests/test_orchestration.py
git commit -m "feat: orchestration + groundling ask CLI subcommand"
```

---

## Task 11: AGENTS.md template and README

**Files:**
- Create: `AGENTS.md`
- Modify: `README.md` (overwrite the placeholder from Task 0)

**Step 1: Write AGENTS.md**

```markdown
# Grounded Q&A — groundling

When a user asks a research question and there's a `docs/` folder of PDFs,
answer it by running:

    groundling ask --corpus docs/ "<question>"

The command prints markdown to stdout. Each cited claim is a clickable
link. Pass the markdown through to the user verbatim — they will click
links to verify sources:

- PDF citations open a local HTML page with the rendered PDF page and
  the cited text highlighted.
- Web citations open the source URL with the cited sentence highlighted
  natively by the browser.

If the user wants the answer to also draw on current web sources, add
`--web-search`:

    groundling ask --corpus docs/ --web-search "<question>"

Default is docs-only — no external lookups. The user should opt in.

Exit codes:
- 0 — success
- 2 — corpus has zero PDFs
- 3 — a PDF couldn't be text-extracted (probably a scan)
- 5 — zero citations returned (the answer is ungrounded — consider
      rephrasing or surfacing this to the user)

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`. Run dirs are self-contained — `tar` one
to share.

Requires `ANTHROPIC_API_KEY` in env or a `.env` in the current dir.
```

**Step 2: Write README**

```markdown
# groundling

Grounded Q&A over a folder of PDFs, with citations you can click to verify.

Designed for use from Claude Code: drop `AGENTS.md` into your project,
set `ANTHROPIC_API_KEY`, ask questions. The tool prints a markdown answer
with clickable citation links — PDF citations open a local HTML page with
the cited page rendered and the cited text highlighted; web citations
(opt-in via `--web-search`) open the source URL with the cited sentence
highlighted natively by the browser.

## Install

    pipx install groundling
    # or:
    uv tool install groundling

## Quick start

    export ANTHROPIC_API_KEY=sk-ant-...
    cd my-research/                          # contains docs/ with PDFs
    curl -O https://.../groundling/AGENTS.md  # one-time template download
    claude

In the agent session: `> what was BYD's Q1 2025 revenue?`

The agent reads `AGENTS.md`, runs `groundling ask --corpus docs/ "..."`,
and shows you the markdown answer with citation links. Click a `[N]` to
open the cited page in your browser.

## CLI

    groundling ask "question" --corpus DIR [--web-search] [--model MODEL]

| Flag | Default | Description |
|---|---|---|
| `--corpus` | (required) | Directory of PDFs |
| `--model` | `claude-sonnet-4-6` | Anthropic model ID |
| `--state-dir` | `<corpus>/qa-runs` | Where run dirs are written |
| `--cache-dir` | `<corpus>/.groundling-cache` | Per-PDF word-extraction cache |
| `--web-search` | off | Enable Anthropic's server-side web_search tool |

Exit codes: 0 success, 2 no PDFs, 3 unextractable PDF (scan), 5 no citations.

## How it works

1. PyMuPDF extracts word-level bboxes from each PDF.
2. Words are concatenated into a flat linearized text per PDF.
3. The Anthropic Messages API is called with citations enabled; the
   linearized text is sent as a document block, the question as user text.
4. The response carries `char_location` citations (and
   `web_search_result_location` citations when `--web-search` is on).
5. Citations resolve back to PDF bboxes via the offset map.
6. A run dir is written under `qa-runs/<timestamp>_<question-slug>/`
   containing one HTML viewer per citation:
   - PDF cites: rendered PDF page + yellow bbox overlay + sidebar.
   - Web cites: meta-redirect stub bouncing to a Chrome Text Fragments
     URL that highlights the cited sentence on the source page.
7. The markdown answer is printed to stdout; each `[N]` link points at a
   local `file://...cites/N.html`.

## Limits

- **No OCR.** PDFs without extractable text (scans) exit 3. OCR them
  externally first.
- **No table-structure inference.** PyMuPDF's reading order is used as-is.
  Complex multi-column layouts may produce garbled linearization; cited
  bboxes are still correct (per-word), but the answer quality drops.
- **No persistent project model.** Each `groundling ask` invocation is a
  fresh, isolated run. Past runs accumulate under `qa-runs/`; delete the
  directory whenever.

## License

TBD.
```

**Step 3: Commit**

```
git add AGENTS.md README.md
git commit -m "docs: AGENTS.md template + README"
```

---

## Task 12: End-to-end smoke test

One test that drives the full pipeline (corpus → API → manifest → cite HTMLs → markdown) with a MagicMock client. Pins the cross-module integration.

**Files:**
- Create: `tests/test_e2e.py`

**Step 1: Write the test**

```python
# tests/test_e2e.py
"""End-to-end smoke: corpus → orchestrator → static HTML files on disk."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from groundling.orchestration import run_ask


def _ns(**kw):
    return SimpleNamespace(**kw)


def _fake_response_with_pdf_and_web_cites():
    return _ns(content=[
        _ns(type="text", text="The first paragraph says ", citations=None),
        _ns(type="text", text="Hello world.",
            citations=[_ns(
                type="char_location", document_index=0,
                document_title="sample.pdf",
                cited_text="some source quote",
                start_char_index=0, end_char_index=12,
            )]),
        _ns(type="text", text=" Analysts confirm.",
            citations=[_ns(
                type="web_search_result_location",
                url="https://example.com/analyst",
                title="Analyst piece",
                cited_text="Hello world reports it",
                encrypted_index="EncIdxFoo",
            )]),
    ])


def test_full_flow(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response_with_pdf_and_web_cites()

    result = run_ask(
        corpus_dir=corpus,
        question="what does the first paragraph say?",
        web_search=True,
        client=fake_client,
    )

    # Markdown ends each cited block with the right [N] marker and
    # lists a file:// reference for each cite.
    md = result.answer_md
    assert "Hello world.[1]" in md
    assert " Analysts confirm.[2]" in md
    base = f"file://{result.run_dir.resolve()}/cites"
    assert f"[1]: {base}/1.html" in md
    assert f"[2]: {base}/2.html" in md

    # PDF cite produced an HTML + PNG; web cite is a redirect stub.
    cites = result.run_dir / "cites"
    assert (cites / "1.html").exists()
    assert (cites / "1.png").exists()
    assert (cites / "2.html").exists()
    assert not (cites / "2.png").exists()  # web cite has no image
    pdf_html = (cites / "1.html").read_text()
    assert "Citation 1 / 2" in pdf_html
    assert "sample.pdf, page 1" in pdf_html
    web_html = (cites / "2.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html
    assert "Hello%20world%20reports%20it" in web_html

    # Manifest is structurally complete.
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["run_id"] == result.run_dir.name
    assert manifest["web_search"] is True
    assert [c["source_type"] for c in manifest["citations"]] == ["pdf", "web"]
```

**Step 2: Run the test**

```
uv run pytest tests/test_e2e.py -v
```
Expected: PASS.

**Step 3: Run the full suite**

```
uv run pytest tests/ -q
```
Expected: all tests pass.

**Step 4: Commit**

```
git add tests/test_e2e.py
git commit -m "test: end-to-end smoke from corpus → cite HTML files"
```

---

## Out of scope (do not implement in v1)

These are listed in the design doc; mirrored here so reviewers don't get tempted:

- Scanned PDFs / OCR fallback (exit 3 with clear message is the v1 surface).
- `groundling research "..."` web-only mode (no corpus).
- `--web-search-domains` / `--web-search-blocked-domains` flags.
- `groundling list`, `groundling replay <run-id>`.
- Shareable `answer.html` for off-Claude-Code sharing.
- Wayback / archive snapshots of cited pages.
- Paragraph segmentation, table structure inference, header/footer filtering.
- Non-Anthropic LLM backends.
- HTML / Markdown / DOCX inputs.
- Anthropic SDK exception → exit 4 mapping (uncaught propagates as 1 for v1).

---

## Done criteria

- `uv run groundling ask --help` shows the CLI surface.
- `uv run pytest tests/ -q` is fully green.
- For a real PDF corpus + ANTHROPIC_API_KEY in env, running `groundling ask
  --corpus DIR "real question"` prints markdown with `[N]` links pointing
  at local `file://...cites/N.html` files. Opening one of those HTMLs in a
  browser shows the cited PDF page rendered with the cited words
  highlighted.
- `--web-search` adds web citations rendered as redirect stubs that bounce
  to Text Fragments URLs.
- `pipx install -e .` from the worktree root succeeds and the resulting
  `groundling` command is on PATH.
