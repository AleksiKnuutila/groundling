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
from groundling.markers import parse_markers, resolve_marker_to_spans
from groundling.render import render_pdf_page


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prep-dir", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--answer", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    answer_md = args.answer.read_text(encoding="utf-8")
    markers = parse_markers(answer_md)

    counters = {"validated": 0, "invalid_chunk": 0, "invalid_quote": 0, "invalid_url": 0}

    pdf_state = {}

    def _load_pdf_state(stem):
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
            next_id += 1
            cite_records.append({
                "marker": m, "cite_id": next_id, "kind": "web",
                "url": m.url,
                "marker_quote": m.quote,
                "claim_text": m.claim_text,
            })
            counters["validated"] += 1

    print(
        f"validated={counters['validated']} "
        f"invalid_chunk={counters['invalid_chunk']} "
        f"invalid_quote={counters['invalid_quote']} "
        f"invalid_url={counters['invalid_url']}",
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
        html = build_inline_answer_html(
            answer_md=out_md,
            cite_records=cite_records,
            image_paths=image_paths,
            image_dims=image_dims,
            scale=2.0,
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
