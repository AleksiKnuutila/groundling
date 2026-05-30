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
