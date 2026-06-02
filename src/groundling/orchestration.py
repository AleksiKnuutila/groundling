"""Top-level orchestration for `groundling ask`."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from groundling.citations import build_manifest
from groundling.corpus import collect_corpus
from groundling.errors import ZeroCitationsError
from groundling.llm import ask_with_citations
from groundling.markdown import format_answer
from groundling.render import (
    render_cite_pdf,
    render_cite_web,
)
from groundling.run import write_run_dir


DEFAULT_STATE_SUBDIR = "qa-runs"
DEFAULT_CACHE_SUBDIR = ".groundling-cache"


@dataclass
class AskResult:
    run_dir: Path
    answer_md: str


def _response_to_jsonable(response: Any) -> dict:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return {"_repr": repr(response)}


def _file_url_for(run_dir: Path):
    """Return a cite_url_for callable bound to this run dir."""
    abs_run = run_dir.resolve()
    def url_for(c: dict) -> str:
        # Uniform file:// link target for all cites. Web cites get the
        # redirect stub written to cites/N.html.
        return f"file://{abs_run}/cites/{c['cite_id']}.html"
    return url_for


def _render_cites(
    *,
    run_dir: Path,
    docs_by_idx: dict,
    manifest: dict,
    question: str,
) -> None:
    """Write cites/N.html (+ N.png for PDF cites) for every manifest citation.

    Deduplicates page renders within a run: when two cites land on the same
    (pdf_path, page), the PNG is rendered once and reused.
    """
    cites = manifest["citations"]
    total = len(cites)
    # (pdf_path, page) → first cite_id whose PNG owns this page.
    rendered_pages: dict[tuple[Path, int], int] = {}
    for i, c in enumerate(cites):
        cite_id = c["cite_id"]
        prev_id = cites[i - 1]["cite_id"] if i > 0 else None
        next_id = cites[i + 1]["cite_id"] if i + 1 < total else None
        if c["source_type"] == "pdf":
            entry = docs_by_idx[c["doc_idx"]]
            page = c["spans"][0]["page"] if c["spans"] else 1
            key = (entry.pdf_path, page)
            owner_cite = rendered_pages.get(key)
            if owner_cite is None:
                rendered_pages[key] = cite_id
                image_path = run_dir / "cites" / f"{cite_id}.png"
            else:
                image_path = run_dir / "cites" / f"{owner_cite}.png"
            render_cite_pdf(
                pdf_path=entry.pdf_path,
                out_html=run_dir / "cites" / f"{cite_id}.html",
                image_path=image_path,
                cite_id=cite_id,
                total=total,
                question=question,
                cited_text=c["cited_text"],
                spans=c["spans"],
                prev_id=prev_id,
                next_id=next_id,
            )
        else:  # web
            render_cite_web(
                out_path=run_dir / "cites" / f"{cite_id}.html",
                url=c["url"],
                title=c.get("title") or c["url"],
                cited_text=c["cited_text"],
            )


def run_ask(
    *,
    corpus_dir: Path,
    question: str,
    model: str = "claude-sonnet-4-6",
    state_dir: Path | None = None,
    cache_dir: Path | None = None,
    web_search: bool = False,
    client: Any = None,
) -> AskResult:
    state = state_dir or (corpus_dir / DEFAULT_STATE_SUBDIR)
    cache = cache_dir or (corpus_dir / DEFAULT_CACHE_SUBDIR)
    state.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    entries = collect_corpus(corpus_dir, cache_dir=cache)
    docs_payload = [(e.pdf_path.name, e.linearized) for e in entries]
    docs_for_manifest = [
        {"doc_idx": i, "pdf_path": str(e.pdf_path.resolve()),
         "offset_map": e.offset_map}
        for i, e in enumerate(entries)
    ]
    docs_by_idx = {i: e for i, e in enumerate(entries)}

    if client is None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ImportError(
                "groundling Mode A (`ask`) needs the anthropic package. "
                "Install with: pip install 'groundling[api]'"
            ) from exc
        from dotenv import load_dotenv
        load_dotenv()
        client = Anthropic()

    response = ask_with_citations(
        client=client, model=model, docs=docs_payload,
        question=question, web_search=web_search,
    )

    manifest = build_manifest(
        run_id="pending", model=model, question=question,
        docs=docs_for_manifest, response=response,
        web_search=web_search,
    )
    run_dir = write_run_dir(
        state_dir=state, question=question,
        manifest=manifest, response_json=_response_to_jsonable(response),
    )
    # Re-read manifest because write_run_dir rewrote run_id.
    persisted = json.loads((run_dir / "manifest.json").read_text())

    # Render per-cite HTML files (and PDF page PNGs).
    _render_cites(
        run_dir=run_dir,
        docs_by_idx=docs_by_idx,
        manifest=persisted,
        question=question,
    )

    # Build the stdout markdown — file:// URLs into cites/.
    answer_md = format_answer(
        response, manifest=persisted,
        cite_url_for=_file_url_for(run_dir),
    )
    if len(persisted["citations"]) == 0:
        raise ZeroCitationsError(run_dir=run_dir, answer_md=answer_md)
    return AskResult(run_dir=run_dir, answer_md=answer_md)
