"""Concatenate response.content text blocks + append [N] markers per
cited block + emit reference-style [N]: url at the bottom."""
from __future__ import annotations

from typing import Any, Callable


def _annotate_text_block(text: str, cite_ids: list[int]) -> str:
    """Append [N] markers at end of `text`. cite_ids is dense + ordered."""
    if not cite_ids:
        return text
    markers = "".join(f"[{cid}]" for cid in cite_ids)
    return text.rstrip() + markers


def _concat_with_separator_safety(blocks: list[str]) -> str:
    out: list[str] = []
    for t in blocks:
        if not t:
            continue
        if out and out[-1] and not out[-1][-1].isspace() and not t[0].isspace():
            out.append(" ")
        out.append(t)
    return "".join(out)


def _match_block_citations_to_manifest(
    block: Any, manifest_cites: list[dict],
) -> list[int]:
    """Return cite_ids (manifest) corresponding to this block's citations."""
    ids: list[int] = []
    for cit in getattr(block, "citations", None) or []:
        ctype = getattr(cit, "type", None)
        if ctype == "char_location":
            for mc in manifest_cites:
                if (
                    mc.get("source_type", "pdf") == "pdf"
                    and mc.get("doc_idx") == cit.document_index
                    and mc.get("char_start") == cit.start_char_index
                    and mc.get("char_end") == cit.end_char_index
                ):
                    ids.append(mc["cite_id"])
                    break
        elif ctype == "web_search_result_location":
            for mc in manifest_cites:
                if (
                    mc.get("source_type") == "web"
                    and mc.get("url") == getattr(cit, "url", None)
                    and mc.get("encrypted_index") == getattr(cit, "encrypted_index", None)
                ):
                    ids.append(mc["cite_id"])
                    break
    return ids


def format_answer(
    response: Any,
    *,
    manifest: dict,
    cite_url_for: Callable[[dict], str],
) -> str:
    """Return reference-style markdown.

    cite_url_for(manifest_citation_dict) -> URL string. Lets the caller
    decide the URL scheme (file:// for local cites HTML, or anything else).
    """
    manifest_cites = manifest.get("citations", [])
    cites_by_id = {c["cite_id"]: c for c in manifest_cites}

    annotated_blocks: list[str] = []
    cited_ids_in_order: list[int] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "text":
            continue
        block_ids = _match_block_citations_to_manifest(block, manifest_cites)
        cited_ids_in_order.extend(block_ids)
        annotated_blocks.append(_annotate_text_block(block.text, block_ids))

    body = _concat_with_separator_safety(annotated_blocks)

    # Reference list at the bottom, sorted by cite_id, dedup'd.
    seen: set[int] = set()
    ref_lines: list[str] = []
    for cid in sorted(cited_ids_in_order):
        if cid in seen:
            continue
        seen.add(cid)
        c = cites_by_id.get(cid)
        if c is None:
            continue
        ref_lines.append(f"[{cid}]: {cite_url_for(c)}")
    if ref_lines:
        return f"{body}\n\n" + "\n".join(ref_lines) + "\n"
    return body
