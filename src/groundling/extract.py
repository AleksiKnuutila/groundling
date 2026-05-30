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
