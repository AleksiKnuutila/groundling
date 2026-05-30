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
