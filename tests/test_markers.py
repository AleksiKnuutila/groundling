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
