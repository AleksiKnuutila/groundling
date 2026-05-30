"""Dispatch-hint thresholds + subagent prompt template.

Single source of truth for AGENTS.md's branching logic. Tuning happens
here, in module constants, so docs and behaviour can't drift.
"""
from __future__ import annotations


MAX_PDFS_IN_SESSION = 4
MAX_TOKENS_IN_SESSION = 120_000


def compute_dispatch_hint(prep_records: list[dict]) -> dict:
    """Compute the dispatch_hint dict written by `groundling prep`.

    prep_records is one dict per PDF with at least
    {"n_chunks": int, "linearized_tokens": int}.
    """
    n_pdfs = len(prep_records)
    n_chunks = sum(r["n_chunks"] for r in prep_records)
    n_tokens = sum(r["linearized_tokens"] for r in prep_records)
    fits_in_session = (
        n_pdfs <= MAX_PDFS_IN_SESSION
        and n_tokens <= MAX_TOKENS_IN_SESSION
    )
    return {
        "n_pdfs": n_pdfs,
        "n_chunks": n_chunks,
        "linearized_tokens": n_tokens,
        "recommend": "in_session" if fits_in_session else "subagent_fanout",
        "thresholds": {
            "max_pdfs_in_session": MAX_PDFS_IN_SESSION,
            "max_tokens_in_session": MAX_TOKENS_IN_SESSION,
        },
    }


SUBAGENT_PROMPT_TEMPLATE = """\
You are answering a question about a single document.

Read this file with the Read tool:
{pdf_path}

It contains chunked text from one PDF. Each chunk is on its own line(s),
prefixed by a bracketed ID like `[p2:b01]` for prose blocks or
`[p2:t0r1c1]` for table cells. Tables are rendered as markdown grids
with one ID per cell.

Answer this question, citing the chunks you drew from:
{question}

Marker contract (mandatory; deviating breaks citation validation):

When citing a chunk in this PDF:
  [chunk=<stem>:<chunk_id> quote="exact verbatim substring of the chunk"]

The chunk_id is the bracketed label as it appears in the linearized
text (the part after `<stem>:`). The quote MUST be a verbatim substring
of that chunk's text — not paraphrased.

When citing a web source (via your WebSearch / WebFetch tools):
  [url="https://full-url" quote="exact verbatim sentence from page"]

The quote MUST be a verbatim substring of the fetched page.

Write your per-document answer as markdown. Embed markers inline next
to the claims they support. If the document doesn't answer the
question, say so plainly without inventing citations.
"""
