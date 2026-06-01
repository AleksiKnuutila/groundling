#!/usr/bin/env python3
"""Skill prep: chunk every PDF in --corpus into linearized text + chunks.json.

Writes per-PDF outputs to --out/:
  <stem>.linearized.txt   — chunk-id-bracketed text Claude reads
  <stem>.chunks.json      — chunk metadata for render-time validation

Exits 2 if --corpus has no PDFs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from groundling.prep import write_pdf_artifacts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--no-tables", action="store_true",
                   help="Skip table detection (faster, less precise).")
    args = p.parse_args()

    pdfs = sorted(args.corpus.glob("*.pdf"))
    if not pdfs:
        print(f"error: no PDFs in {args.corpus}", file=sys.stderr)
        sys.exit(2)

    args.out.mkdir(parents=True, exist_ok=True)
    for pdf_path in pdfs:
        record = write_pdf_artifacts(
            pdf_path, out_dir=args.out, detect_tables=not args.no_tables,
        )
        print(
            f"prepared {record['pdf_stem']}: {record['n_chunks']} chunks",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
