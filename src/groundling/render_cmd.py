"""groundling render: agent answer + prep dir -> cite HTML + rewritten markdown."""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from groundling.answer_html import build_answer_html
from groundling.extract import extract_words
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_cite_pdf, render_cite_web


DEFAULT_STATE_SUBDIR = "qa-runs"
DEFAULT_WEB_BASE = "file://"


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


def _cite_url(web_base: str, run_dir: Path, cite_id: int) -> str:
    """Build the URL for cite N. file:// → absolute on-disk path (works
    on double-click). Any other scheme → http-style URL where the path
    is the run-dir name + `/cites/N.html`, assuming the server serves
    state_dir as its root."""
    if web_base.startswith("file://") or web_base == "":
        return f"file://{run_dir.resolve()}/cites/{cite_id}.html"
    return f"{web_base.rstrip('/')}/{run_dir.name}/cites/{cite_id}.html"


def run_render(
    *,
    prep_dir: Path,
    answer_md: str,
    state_dir: Path | None,
    web_base: str = DEFAULT_WEB_BASE,
    question: str | None = None,
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
                "url": m.url,
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

    # Rewrite the answer markdown. Point markers get replaced with
    # `[N]` reference-style footnotes. Wrap markers get their URL
    # rewritten — link text and title attribute (the quote) survive
    # unchanged so the agent's committed claim_text stays visible.
    # Walk right-to-left so offsets stay valid.
    markers_by_id = {id(r["marker"]): r["marker"] for r in cite_records}
    survivors = {id(r["marker"]): r["cite_id"] for r in cite_records}
    out = answer_md
    surviving_markers = set(markers_by_id)
    all_marker_spans = sorted(
        ((m.span_start, m.span_end, id(m)) for m in markers),
        key=lambda t: -t[0],
    )
    for s, e, mid in all_marker_spans:
        if mid in surviving_markers:
            cite_id = survivors[mid]
            mk = markers_by_id[mid]
            if mk.wrap_kind == "wrap":
                href = _cite_url(web_base, run_dir, cite_id)
                quote_escaped = mk.quote.replace('"', '\\"')
                out = (
                    out[:s]
                    + f'[{mk.claim_text}]({href} "{quote_escaped}")'
                    + out[e:]
                )
            else:
                out = out[:s] + f"[{cite_id}]" + out[e:]
        else:
            out = out[:s] + out[e:]

    # Append reference block — only for point-style cites. Wrap-style
    # cites are self-contained inline links and need no appendix.
    point_records = [r for r in cite_records
                     if r["marker"].wrap_kind != "wrap"]
    if point_records:
        refs = "\n".join(
            f"[{r['cite_id']}]: {_cite_url(web_base, run_dir, r['cite_id'])}"
            for r in point_records
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
                "wrap_kind": r["marker"].wrap_kind,
                **({"claim_text": r["marker"].claim_text}
                   if r["marker"].claim_text is not None else {}),
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

    # Also emit answer.html — browser view with hover preview + side
    # pane. Build image_dims from the cite records we already validated.
    image_dims: dict[int, tuple[str, int, int]] = {}
    page_dims_cache: dict[tuple[Path, int], tuple[int, int]] = {}
    for rec in cite_records:
        if rec["kind"] != "pdf":
            continue
        cid = rec["cite_id"]
        page = rec["spans"][0]["page"]
        # Determine which N.png this cite uses (may be a dedupe owner's).
        key = (rec["pdf_path"], page)
        owner = rendered_pages.get(key, cid)
        image_filename = f"{owner}.png"
        # Cache page dims by (pdf_path, page).
        if key not in page_dims_cache:
            with fitz.open(rec["pdf_path"]) as doc:
                p = doc.load_page(page - 1)
                page_dims_cache[key] = (
                    int(p.rect.width * 2.0),
                    int(p.rect.height * 2.0),
                )
        w_px, h_px = page_dims_cache[key]
        image_dims[cid] = (image_filename, w_px, h_px)

    answer_html = build_answer_html(
        answer_md=out,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name=run_dir.name,
        scale=2.0,
        page_title=question,
    )
    (run_dir / "answer.html").write_text(answer_html, encoding="utf-8")

    return RenderResult(run_dir=run_dir, markdown=out, counters=counters)
