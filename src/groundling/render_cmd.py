"""groundling render: agent answer + prep dir -> cite HTML + rewritten markdown."""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from groundling.extract import extract_words
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_cite_pdf, render_cite_web


DEFAULT_STATE_SUBDIR = "qa-runs"


@dataclass
class RenderResult:
    run_dir: Path
    markdown: str
    counters: dict = field(default_factory=dict)


def _new_run_id(prefix: str = "render") -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    return f"{stamp}_{prefix}_{secrets.token_hex(2)}"


def _load_chunks(prep_dir: Path, stem: str) -> list[dict] | None:
    p = prep_dir / f"{stem}.chunks.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _file_url(run_dir: Path, cite_id: int) -> str:
    return f"file://{run_dir.resolve()}/cites/{cite_id}.html"


def run_render(
    *,
    prep_dir: Path,
    answer_md: str,
    state_dir: Path | None,
) -> RenderResult:
    # Default state dir is sibling to prep dir, under the corpus root.
    if state_dir is None:
        # prep_dir = <corpus>/.groundling-prep/<stamp>; state default
        # is <corpus>/qa-runs
        state_dir = prep_dir.parent.parent / DEFAULT_STATE_SUBDIR
    state_dir.mkdir(parents=True, exist_ok=True)
    run_dir = state_dir / _new_run_id()
    (run_dir / "cites").mkdir(parents=True)

    markers = parse_markers(answer_md)

    counters = {
        "validated": 0,
        "invalid_chunk": 0,
        "invalid_quote": 0,
        "invalid_url": 0,
    }

    # PDF stem -> (words, chunks, pdf_path); load lazily, cache.
    pdf_state: dict[str, tuple[list[dict], list[dict], Path]] = {}

    def _load_pdf_state(stem: str):
        if stem in pdf_state:
            return pdf_state[stem]
        # The PDF lives next to the prep dir's corpus_dir:
        # prep_dir.parent.parent / f"{stem}.pdf".
        candidate = prep_dir.parent.parent / f"{stem}.pdf"
        if not candidate.exists():
            return None
        words = extract_words(candidate, cache_dir=None)
        chunks = _load_chunks(prep_dir, stem) or []
        pdf_state[stem] = (words, chunks, candidate)
        return pdf_state[stem]

    cite_records: list[dict] = []  # for substitution + html rendering
    next_id = 0

    for m in markers:
        if m.kind == "pdf":
            state = _load_pdf_state(m.pdf_stem)
            if state is None:
                counters["invalid_chunk"] += 1
                continue
            words, chunks, pdf_path = state
            spans = resolve_marker_to_spans(m, chunks, words)
            if spans is None:
                # Distinguish chunk-not-found from quote-not-found.
                if m.chunk_id not in {c["chunk_id"] for c in chunks}:
                    counters["invalid_chunk"] += 1
                else:
                    counters["invalid_quote"] += 1
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "pdf",
                "spans": spans, "pdf_path": pdf_path,
            })
            counters["validated"] += 1
        else:  # web
            if not (m.url and m.url.startswith(("http://", "https://"))):
                counters["invalid_url"] += 1
                continue
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "web",
            })
            counters["validated"] += 1

    # Generate HTML for each surviving cite.
    rendered_pages: dict[tuple[Path, int], int] = {}
    total = len(cite_records)
    for i, rec in enumerate(cite_records):
        cid = rec["cite_id"]
        prev_id = cite_records[i - 1]["cite_id"] if i > 0 else None
        next_id_link = cite_records[i + 1]["cite_id"] if i + 1 < total else None
        if rec["kind"] == "pdf":
            page = rec["spans"][0]["page"]
            key = (rec["pdf_path"], page)
            owner = rendered_pages.get(key)
            if owner is None:
                rendered_pages[key] = cid
                image_path = run_dir / "cites" / f"{cid}.png"
            else:
                image_path = run_dir / "cites" / f"{owner}.png"
            render_cite_pdf(
                pdf_path=rec["pdf_path"],
                out_html=run_dir / "cites" / f"{cid}.html",
                image_path=image_path,
                cite_id=cid, total=total,
                question="",
                cited_text=rec["marker"].quote,
                spans=rec["spans"],
                prev_id=prev_id, next_id=next_id_link,
            )
        else:
            render_cite_web(
                out_path=run_dir / "cites" / f"{cid}.html",
                url=rec["marker"].url,
                title=rec["marker"].url,
                cited_text=rec["marker"].quote,
            )

    # Rewrite the answer markdown: replace each surviving marker with
    # [N]; drop invalid markers entirely. Walk right-to-left so offsets
    # stay valid.
    survivors = {id(r["marker"]): r["cite_id"] for r in cite_records}
    out = answer_md
    surviving_markers = {id(r["marker"]) for r in cite_records}
    all_marker_spans = sorted(
        ((m.span_start, m.span_end, id(m)) for m in markers),
        key=lambda t: -t[0],
    )
    for s, e, mid in all_marker_spans:
        if mid in surviving_markers:
            cite_id = survivors[mid]
            out = out[:s] + f"[{cite_id}]" + out[e:]
        else:
            out = out[:s] + out[e:]

    # Append reference block.
    if cite_records:
        refs = "\n".join(
            f"[{r['cite_id']}]: {_file_url(run_dir, r['cite_id'])}"
            for r in cite_records
        )
        out = f"{out.rstrip()}\n\n{refs}\n"

    # Write manifest.json for parity with v1's run dir shape.
    manifest = {
        "run_id": run_dir.name,
        "prep_dir": str(prep_dir.resolve()),
        "counters": counters,
        "citations": [
            {
                "cite_id": r["cite_id"],
                "source_type": r["kind"],
                "cited_text": r["marker"].quote,
                **({
                    "doc_stem": r["marker"].pdf_stem,
                    "chunk_id": r["marker"].chunk_id,
                    "spans": r["spans"],
                } if r["kind"] == "pdf" else {
                    "url": r["marker"].url,
                }),
            }
            for r in cite_records
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "answer.md").write_text(out, encoding="utf-8")

    return RenderResult(run_dir=run_dir, markdown=out, counters=counters)
