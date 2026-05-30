"""Per-PDF prep artefacts: chunks.json + linearized.txt + record dict."""
from __future__ import annotations

import json
from pathlib import Path

from groundling.chunker import chunk_pdf


def _approx_tokens(text: str) -> int:
    """Rough token count for dispatch heuristics. ~1 token per 4 chars
    is a defensible ballpark for English text."""
    return max(1, len(text) // 4)


def write_pdf_artifacts(
    pdf_path: Path, *, out_dir: Path, detect_tables: bool = True,
) -> dict:
    """Write <stem>.chunks.json + <stem>.linearized.txt under out_dir.
    Return a record describing the PDF for the dispatch_hint."""
    stem = pdf_path.stem
    chunks = chunk_pdf(pdf_path, detect_tables=detect_tables)

    (out_dir / f"{stem}.chunks.json").write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False)
    )

    # Render linearized text with full chunk IDs like `[sample:p1:b00]`.
    # For table cells, render the table grid by grouping cells of the
    # same (page, table_idx).
    lines: list[str] = []
    # Group prose blocks and table cells by (page, table_idx-or-None)
    grouped: dict[tuple[int, int | None], list[dict]] = {}
    for c in chunks:
        # Cell IDs look like "p<p>:t<i>rN cM"; prose like "p<p>:b<n>"
        cid = c["chunk_id"]
        if ":t" in cid:
            # Extract table_idx
            t_part = cid.split(":t", 1)[1]
            table_idx = int(t_part.split("r", 1)[0])
            key = (c["page"], table_idx)
        else:
            key = (c["page"], None)
        grouped.setdefault(key, []).append(c)

    last_page: int | None = None
    for (page, table_idx), group in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1] if x[0][1] is not None else -1)):
        if last_page is not None and page != last_page:
            lines.append("")
        last_page = page
        if table_idx is None:
            for c in group:
                lines.append(f"[{stem}:{c['chunk_id']}] {c['text']}")
        else:
            # Render as a markdown grid. Determine row/col counts.
            cells: dict[tuple[int, int], dict] = {}
            for c in group:
                # cid like "p1:t0r0c0"
                rc = c["chunk_id"].split("t", 1)[1].split("r", 1)[1]
                r, c_idx = rc.split("c", 1)
                cells[(int(r), int(c_idx))] = c
            n_rows = max(r for r, _ in cells) + 1
            n_cols = max(c for _, c in cells) + 1
            grid: list[list[str]] = []
            for r in range(n_rows):
                row: list[str] = []
                for col in range(n_cols):
                    c = cells.get((r, col))
                    if c is None:
                        row.append("")
                        continue
                    content = c["text"].replace("\n", " ").replace("|", r"\|").strip()
                    row.append(f"[{stem}:{c['chunk_id']}] {content}")
                grid.append(row)
            lines.append("")
            lines.append("| " + " | ".join(grid[0]) + " |")
            lines.append("| " + " | ".join(["---"] * n_cols) + " |")
            for row in grid[1:]:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

    linearized = "\n".join(lines).strip() + "\n"
    (out_dir / f"{stem}.linearized.txt").write_text(linearized, encoding="utf-8")

    return {
        "pdf_stem": stem,
        "pdf_path": str(pdf_path.resolve()),
        "n_chunks": len(chunks),
        "linearized_tokens": _approx_tokens(linearized),
    }
