from __future__ import annotations

from groundling.markers import Marker, parse_markers, resolve_marker_to_spans


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


def test_resolve_marker_curly_apostrophe_matches_straight():
    """LLMs routinely substitute ASCII apostrophes for curly ones when
    "quoting verbatim". Validation should accept the substitution rather
    than dropping the cite."""
    chunks = [{
        "chunk_id": "p1:b00", "page": 1, "bbox": [0, 0, 100, 30],
        "word_idx_start": 0, "word_idx_end": 4,
        "text": "the Group’s revenue increased",  # U+2019 RIGHT SINGLE QUOTE
    }]
    words = [
        {"content": "the", "page": 1, "bbox": [0, 0, 20, 30]},
        {"content": "Group’s", "page": 1, "bbox": [25, 0, 60, 30]},
        {"content": "revenue", "page": 1, "bbox": [65, 0, 85, 30]},
        {"content": "increased", "page": 1, "bbox": [90, 0, 100, 30]},
    ]
    m = Marker(kind="pdf",
               quote="the Group's revenue",   # ASCII apostrophe
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:b00")
    spans = resolve_marker_to_spans(m, chunks, words)
    assert spans is not None
    assert len(spans) == 3  # "the", "Group’s", "revenue"


def test_resolve_marker_em_dash_folds_to_hyphen():
    chunks = [{
        "chunk_id": "p1:b00", "page": 1, "bbox": [0, 0, 100, 30],
        "word_idx_start": 0, "word_idx_end": 3,
        "text": "growth—substantial—overall",  # em dashes
    }]
    words = [
        {"content": "growth—substantial—overall", "page": 1, "bbox": [0, 0, 100, 30]},
    ]
    # Word slice for the chunk is one entry — adjust to single word.
    chunks[0]["word_idx_end"] = 1
    m = Marker(kind="pdf",
               quote="growth-substantial-overall",  # ASCII hyphens
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:b00")
    spans = resolve_marker_to_spans(m, chunks, words)
    assert spans is not None


def test_resolve_marker_nbsp_folds_to_space():
    chunks = [{
        "chunk_id": "p1:b00", "page": 1, "bbox": [0, 0, 100, 30],
        "word_idx_start": 0, "word_idx_end": 2,
        "text": "RMB 170 billion",  # NBSPs
    }]
    words = [
        {"content": "RMB", "page": 1, "bbox": [0, 0, 30, 30]},
        {"content": "170 billion", "page": 1, "bbox": [35, 0, 100, 30]},
    ]
    m = Marker(kind="pdf",
               quote="RMB 170 billion",  # regular spaces
               span_start=0, span_end=0,
               pdf_stem="x", chunk_id="p1:b00")
    spans = resolve_marker_to_spans(m, chunks, words)
    assert spans is not None
