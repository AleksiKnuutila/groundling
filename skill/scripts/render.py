#!/usr/bin/env python3
"""Skill render: validate markers + produce single-file answer.html.

Reads:
  --prep-dir   produced by prep.py
  --corpus     directory of original PDFs (for rendering page images)
  --answer     markdown file with cite markers
  --out        path to write the single-file answer.html

Exits 0 on success. Exits 5 if zero markers survived validation.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from groundling.answer_html_inline import build_inline_answer_html
from groundling.extract import extract_words
from groundling.judge import load_uncited, load_verdicts
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_pdf_page
from groundling.uncited import apply_wraps, find_uncited_spans


def load_web_evidence(web_dir: Path) -> dict[str, dict]:
    """Glob <web_dir>/*.json and return {url: evidence_dict}.

    Malformed files and files missing required keys are skipped with
    a warning to stderr."""
    if not web_dir.exists():
        return {}
    REQUIRED = {"url", "title", "fetched_at", "extracted_text"}
    out: dict[str, dict] = {}
    for p in sorted(web_dir.glob("*.json")):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warn: skipping {p.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(payload, dict):
            print(f"warn: skipping {p.name}: not a JSON object",
                  file=sys.stderr)
            continue
        missing = REQUIRED - payload.keys()
        if missing:
            print(f"warn: skipping {p.name}: missing keys {sorted(missing)}",
                  file=sys.stderr)
            continue
        out[payload["url"]] = payload
    return out


def compute_excerpt(text: str, quote: str, window: int = 150) -> tuple[str, int]:
    """Locate `quote` in `text`, return (excerpt, quote_offset_in_excerpt).

    Excerpt is `text` sliced to ±window chars around the quote span,
    clamped to text bounds."""
    pos = text.index(quote)
    start = max(0, pos - window)
    end = min(len(text), pos + len(quote) + window)
    excerpt = text[start:end]
    return excerpt, pos - start


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prep-dir", type=Path, default=None)
    p.add_argument("--corpus", type=Path, default=None)
    p.add_argument("--web-dir", type=Path, default=None)
    p.add_argument(
        "--question", default=None,
        help="The question being answered. Becomes the page <h1>.",
    )
    p.add_argument(
        "--source-summary", default=None, dest="source_summary",
        help="One-line summary under the title "
             "(e.g. 'Verified answer · 17 claims checked against ...').",
    )
    p.add_argument("--answer", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--judge-dir", type=Path, default=None, dest="judge_dir",
        help="Directory containing verdicts.json (Pass 2 — cited verdicts). "
             "Default: no judge decoration.",
    )
    args = p.parse_args()

    if not args.prep_dir and not args.web_dir:
        p.error("at least one of --prep-dir or --web-dir is required")
    if args.prep_dir and not args.corpus:
        p.error("--corpus is required when --prep-dir is given")

    answer_md = args.answer.read_text(encoding="utf-8")
    markers = parse_markers(answer_md)

    verdicts = load_verdicts(args.judge_dir)
    uncited_entries = load_uncited(args.judge_dir)

    counters = {"validated": 0, "invalid_chunk": 0, "invalid_quote": 0,
                "invalid_url": 0, "missing_evidence": 0,
                "invalid_quote_web": 0,
                "verdicts_missing": 0, "verdicts_unmapped": 0,
                "uncited_matched": 0, "uncited_unmatched": 0,
                "uncited_overlap": 0}

    web_evidence = load_web_evidence(args.web_dir) if args.web_dir else {}

    pdf_state = {}

    def _load_pdf_state(stem):
        if args.prep_dir is None or args.corpus is None:
            return None
        if stem in pdf_state:
            return pdf_state[stem]
        pdf_path = args.corpus / f"{stem}.pdf"
        chunks_json = args.prep_dir / f"{stem}.chunks.json"
        if not pdf_path.exists() or not chunks_json.exists():
            return None
        chunks = json.loads(chunks_json.read_text(encoding="utf-8"))
        words = extract_words(pdf_path, cache_dir=None)
        pdf_state[stem] = (words, chunks, pdf_path)
        return pdf_state[stem]

    cite_records = []
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
                "marker_quote": m.quote,
                "claim_text": m.claim_text,
                "pdf_filename": pdf_path.name,
            })
            counters["validated"] += 1
        else:  # web
            if not (m.url and m.url.startswith(("http://", "https://"))):
                counters["invalid_url"] += 1
                continue
            ev = web_evidence.get(m.url)
            if ev is None:
                counters["missing_evidence"] += 1
                continue
            if m.quote not in ev["extracted_text"]:
                counters["invalid_quote_web"] += 1
                continue
            excerpt, q_off = compute_excerpt(ev["extracted_text"], m.quote)
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "web",
                "url": m.url,
                "title": ev["title"],
                "fetched_at": ev["fetched_at"],
                "marker_quote": m.quote,
                "claim_text": m.claim_text,
                "excerpt": excerpt,
                "quote_offset_in_excerpt": q_off,
            })
            counters["validated"] += 1

    # PR 2: cross-reference verdicts against this render's cite_records.
    if verdicts:
        verdict_cite_ids = set(verdicts.keys())
        record_cite_ids = {r["cite_id"] for r in cite_records}
        counters["verdicts_missing"] = len(record_cite_ids - verdict_cite_ids)
        counters["verdicts_unmapped"] = len(verdict_cite_ids - record_cite_ids)

    print(
        f"validated={counters['validated']} "
        f"invalid_chunk={counters['invalid_chunk']} "
        f"invalid_quote={counters['invalid_quote']} "
        f"invalid_url={counters['invalid_url']} "
        f"missing_evidence={counters['missing_evidence']} "
        f"invalid_quote_web={counters['invalid_quote_web']} "
        f"verdicts_missing={counters['verdicts_missing']} "
        f"verdicts_unmapped={counters['verdicts_unmapped']} "
        f"uncited_matched={counters['uncited_matched']} "
        f"uncited_unmatched={counters['uncited_unmatched']} "
        f"uncited_overlap={counters['uncited_overlap']}",
        file=sys.stderr,
    )

    if not cite_records:
        print("error: zero valid cites in answer", file=sys.stderr)
        sys.exit(5)

    image_paths = {}
    image_dims = {}
    page_owners = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for rec in cite_records:
            if rec["kind"] != "pdf":
                continue
            page = rec["spans"][0]["page"]
            key = (rec["pdf_path"], page)
            if key not in page_owners:
                page_owners[key] = rec["cite_id"]
                img = tmp_dir / f"{rec['cite_id']}.png"
                w, h = render_pdf_page(rec["pdf_path"], page=page,
                                       out_path=img, scale=2.0)
                image_paths[rec["cite_id"]] = img
                image_dims[rec["cite_id"]] = (w, h)
            else:
                owner_id = page_owners[key]
                image_paths[rec["cite_id"]] = image_paths[owner_id]
                image_dims[rec["cite_id"]] = image_dims[owner_id]

        out_md = _rewrite_to_cite_scheme(answer_md, markers, cite_records)

        # PR 3: locate + wrap uncited spans (Pass 1) before passing to
        # the HTML builder. The pre-wrapped anchors carry data-cite-id
        # values like "u1" so the hover-card JS can look them up in the
        # GROUNDLING_CITES map.
        uncited_wraps = []
        if uncited_entries:
            uncited_wraps, uc_counters = find_uncited_spans(
                out_md, uncited_entries,
            )
            counters.update(uc_counters)
            out_md = apply_wraps(out_md, uncited_wraps)

        html = build_inline_answer_html(
            answer_md=out_md,
            cite_records=cite_records,
            image_paths=image_paths,
            image_dims=image_dims,
            scale=2.0,
            page_title=args.question,
            subtitle=args.source_summary,
            verdicts=verdicts,
            uncited_wraps=uncited_wraps,
        )

    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(cite_records)} cites)", file=sys.stderr)


def _rewrite_to_cite_scheme(answer_md, markers, cite_records):
    """Rewrite surviving markers to [text](cite://N "quote"); drop
    invalid markers entirely."""
    survivors = {id(r["marker"]): r["cite_id"] for r in cite_records}
    out = answer_md
    surviving_ids = set(survivors)
    all_spans = sorted(
        ((m.span_start, m.span_end, id(m), m) for m in markers),
        key=lambda t: -t[0],
    )
    for s, e, mid, m in all_spans:
        if mid in surviving_ids:
            cid = survivors[mid]
            if m.wrap_kind == "wrap":
                quote_escaped = m.quote.replace('"', '\\"')
                out = (out[:s]
                       + f'[{m.claim_text}](cite://{cid} "{quote_escaped}")'
                       + out[e:])
            else:
                quote_escaped = m.quote.replace('"', '\\"')
                out = (out[:s]
                       + f'[{cid}](cite://{cid} "{quote_escaped}")'
                       + out[e:])
        else:
            out = out[:s] + out[e:]
    return out


if __name__ == "__main__":
    main()
