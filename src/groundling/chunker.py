"""Chunk a PDF into per-page units: prose blocks + (optionally) table cells.

Each chunk has a stable ID, page, bbox, and a word-index range into the
flat word list produced by extract_words. The render-time validation
uses these ranges to map a cited quote back to specific word bboxes.

Chunk ID grammar (per-PDF, mirrors groundswell's convention):
- `p<page>:b<n>` for prose blocks (PyMuPDF blocks)
- `p<page>:t<i>r<r>c<c>` for table cells (added in Task 2)
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

import fitz

from groundling.extract import extract_words


def _bbox_contains_point(bbox: list[float], x: float, y: float) -> bool:
    """True iff (x, y) is inside bbox = [x0, y0, x1, y1]."""
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


@contextlib.contextmanager
def _silence_native_stdout():
    """Suppress stdout writes from PyMuPDF (e.g. find_tables() advisory
    messages) at both the Python and OS levels so `groundling prep`'s
    stdout stays exactly the prep dir path. AGENTS.md captures it as
    `dir=$(groundling prep ...)` and PyMuPDF leaks would break that.

    Belt + braces: redirect_stdout catches Python-level `print()` writes;
    the fd dup2 catches C-level writes from PyMuPDF's underlying MuPDF.
    We flush Python's buffer before restoring fd 1 so any buffered
    writes go to /dev/null rather than the restored fd."""
    saved_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os.dup2(saved_fd, 1)
        os.close(devnull_fd)
        os.close(saved_fd)


def chunk_pdf(pdf_path: Path, *, detect_tables: bool = True) -> list[dict]:
    """Return per-PDF chunks: [{chunk_id, page, bbox, word_idx_start,
    word_idx_end, text}, ...] sorted by (page, reading order).

    When `detect_tables` is True, PyMuPDF's `page.find_tables()` is run
    first; words falling inside detected table cells become
    `p<page>:t<i>r<r>c<c>` chunks. Remaining words then fall through to
    the prose `p<page>:b<n>` block pass.
    """
    words = extract_words(pdf_path, cache_dir=None)
    # word_idx_by_page: page -> list of (idx, word) preserving extract order
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
                    with _silence_native_stdout():
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
