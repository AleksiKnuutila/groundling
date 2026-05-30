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
