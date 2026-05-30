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
