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


def test_unknown_doc_idx_drops_the_citation():
    """When document_index points at no known doc, the citation has
    nowhere to highlight, so it's dropped rather than emitted as an
    orphan [N] link pointing at a missing cites/N.html file."""
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
    assert manifest["citations"] == []


def test_pdf_citation_with_no_resolved_spans_is_dropped():
    """A char range that falls between offset_map entries (e.g. on the
    inter-word space) drops the citation rather than emitting an orphan."""
    words = [
        {"content": "Hello", "page": 1, "bbox": [0, 0, 10, 5]},
        {"content": "world.", "page": 1, "bbox": [11, 0, 25, 5]},
    ]
    _, offset_map = linearize_words(words)
    doc = {"doc_idx": 0, "pdf_path": "/abs/x.pdf", "offset_map": offset_map}
    # Char 5 is the separator between "Hello" and "world." — no overlap.
    response = _ns(content=[
        _ns(type="text", text="hi", citations=[
            _ns(type="char_location", document_index=0,
                document_title="x.pdf", cited_text="?",
                start_char_index=5, end_char_index=6),
        ]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[doc], response=response,
    )
    assert manifest["citations"] == []


def test_duplicate_char_location_collapses_to_single_cite():
    """Two response blocks citing the same (doc_idx, char range) should
    produce one manifest entry, not two. Otherwise the markdown formatter
    would emit [1] for both blocks and orphan [2] in the reference list."""
    words = [
        {"content": "Hello", "page": 1, "bbox": [0, 0, 10, 5]},
    ]
    _, offset_map = linearize_words(words)
    doc = {"doc_idx": 0, "pdf_path": "/abs/x.pdf", "offset_map": offset_map}
    cit = _ns(
        type="char_location", document_index=0,
        document_title="x.pdf", cited_text="Hello",
        start_char_index=0, end_char_index=5,
    )
    response = _ns(content=[
        _ns(type="text", text="first", citations=[cit]),
        _ns(type="text", text="second", citations=[cit]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[doc], response=response,
    )
    assert len(manifest["citations"]) == 1
    assert manifest["citations"][0]["cite_id"] == 1


def test_duplicate_web_citation_collapses_to_single_cite():
    cit = _ns(
        type="web_search_result_location",
        url="https://example.com/x", title="t",
        cited_text="quote", encrypted_index="EncIdx",
    )
    response = _ns(content=[
        _ns(type="text", text="first", citations=[cit]),
        _ns(type="text", text="second", citations=[cit]),
    ])
    manifest = build_manifest(
        run_id="r", model="m", question="q", docs=[], response=response,
    )
    assert len(manifest["citations"]) == 1
