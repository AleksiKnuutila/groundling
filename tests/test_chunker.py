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
