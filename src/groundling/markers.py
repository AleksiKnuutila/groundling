"""Marker parser for agent-emitted citation markers.

PDF marker: [chunk=<stem>:<chunk_id> quote="..."]
Web marker: [url="<url>" quote="..."]

Quotes can contain escaped double quotes (\"). Other escapes are
passed through verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Marker:
    kind: str               # "pdf" or "web"
    quote: str
    span_start: int         # offset into the source markdown
    span_end: int
    pdf_stem: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    # "point" markers are dropped/replaced with [N] at render time. "wrap"
    # markers came from a wrapping markdown link `[claim](chunk://...
    # "quote")` — the agent committed to the claim_text as the cite scope;
    # at render time we keep the link text and rewrite just the URL.
    wrap_kind: str = "point"
    claim_text: str | None = None


# Compiled regexes. We match the brackets, then parse internals manually
# so we can handle escaped quotes inside the quote= field.
_MARKER_RE = re.compile(r"\[(?:chunk|url)=[^\[\]]*?\"(?:[^\"\\]|\\.)*\"[^\[\]]*?\]")
_CHUNK_INNER_RE = re.compile(
    r"^chunk=(?P<stem>[^:\s]+):(?P<chunk_id>[^\s]+)\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)
_URL_INNER_RE = re.compile(
    r"^url=\"(?P<url>[^\"]+)\"\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)

# Wrapping markdown-link cite: [claim text](chunk://stem/chunk_id "quote")
# The agent commits to the claim_text as the scope of the citation,
# instead of the conventional "preceding sentence" of point markers.
_WRAP_PDF_RE = re.compile(
    r'\[(?P<claim>[^\]\n]+)\]'
    r'\(chunk://(?P<stem>[^/\s]+)/(?P<chunk_id>[^\s)]+)'
    r'\s+"(?P<quote>(?:[^"\\]|\\.)*)"\)'
)
# Wrapping web cite: [claim text](web://https://full-url "quote")
# Web URL goes in the path after web:// so it doesn't collide with
# ordinary `[text](https://...)` markdown links that aren't cites.
_WRAP_WEB_RE = re.compile(
    r'\[(?P<claim>[^\]\n]+)\]'
    r'\(web://(?P<url>https?://[^\s)]+)'
    r'\s+"(?P<quote>(?:[^"\\]|\\.)*)"\)'
)


def _unescape(s: str) -> str:
    return s.replace(r'\"', '"').replace(r"\\", "\\")


def parse_markers(markdown: str) -> list[Marker]:
    out: list[Marker] = []
    claimed: list[tuple[int, int]] = []  # spans the wrap pass took

    # First pass: wrapping markdown-link cites (more specific, eat first).
    for mm in _WRAP_PDF_RE.finditer(markdown):
        out.append(Marker(
            kind="pdf",
            quote=_unescape(mm.group("quote")),
            span_start=mm.start(),
            span_end=mm.end(),
            pdf_stem=mm.group("stem"),
            chunk_id=mm.group("chunk_id"),
            wrap_kind="wrap",
            claim_text=mm.group("claim"),
        ))
        claimed.append((mm.start(), mm.end()))
    for mm in _WRAP_WEB_RE.finditer(markdown):
        out.append(Marker(
            kind="web",
            quote=_unescape(mm.group("quote")),
            span_start=mm.start(),
            span_end=mm.end(),
            url=mm.group("url"),
            wrap_kind="wrap",
            claim_text=mm.group("claim"),
        ))
        claimed.append((mm.start(), mm.end()))

    def _inside_claimed(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in claimed)

    # Second pass: legacy point markers. Skip any that fall inside the
    # link-text of a wrap marker (otherwise [chunk=...] hidden in a
    # claim string would double-cite).
    for m in _MARKER_RE.finditer(markdown):
        if _inside_claimed(m.start(), m.end()):
            continue
        inner = markdown[m.start() + 1 : m.end() - 1]
        if inner.startswith("chunk="):
            mm = _CHUNK_INNER_RE.match(inner)
            if not mm:
                continue
            out.append(Marker(
                kind="pdf",
                quote=_unescape(mm.group("quote")),
                span_start=m.start(),
                span_end=m.end(),
                pdf_stem=mm.group("stem"),
                chunk_id=mm.group("chunk_id"),
            ))
        elif inner.startswith("url="):
            mm = _URL_INNER_RE.match(inner)
            if not mm:
                continue
            out.append(Marker(
                kind="web",
                quote=_unescape(mm.group("quote")),
                span_start=m.start(),
                span_end=m.end(),
                url=mm.group("url"),
            ))
    out.sort(key=lambda mk: mk.span_start)
    return out


# Unicode characters LLMs commonly substitute for their ASCII equivalents
# when "quoting verbatim". Substring validation collapses both sides via
# this table before comparison so a curly-apostrophe-in-source vs
# straight-apostrophe-in-quote doesn't cost the user a citation.
_UNICODE_FOLDS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",  # single quotes
    "“": '"', "”": '"', "„": '"', "‟": '"',  # double quotes
    "–": "-", "—": "-", "―": "-",                  # en/em/horizontal dashes
    "‐": "-", "‑": "-", "−": "-",                  # hyphen variants + minus
    " ": " ", " ": " ", " ": " ", " ": " ",   # nbsp + thin/hair/narrow-nbsp
})


def _normalised(text: str) -> str:
    """Collapse whitespace and fold LLM-substituted Unicode punctuation
    to ASCII so verbatim-quote validation doesn't fail on curly quotes,
    em dashes, or non-breaking spaces the model normalised on its way
    out."""
    return " ".join(text.translate(_UNICODE_FOLDS).split())


def resolve_marker_to_spans(
    marker: Marker,
    chunks: list[dict],
    words: list[dict],
) -> list[dict] | None:
    """Look up the marker's chunk, verify the quote is a substring, and
    map the matched range to a list of {page, bbox} word entries.

    Returns None when the chunk is unknown or the quote isn't in it.
    """
    if marker.kind != "pdf":
        return None
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    chunk = chunks_by_id.get(marker.chunk_id)
    if chunk is None:
        return None

    chunk_text = chunk["text"]
    quote_norm = _normalised(marker.quote)
    text_norm = _normalised(chunk_text)
    if quote_norm not in text_norm:
        return None

    # Walk the chunk's words and find the slice whose joined text
    # contains the quote. We pick the smallest window that contains
    # the quote.
    chunk_words = words[chunk["word_idx_start"]:chunk["word_idx_end"]]
    best: tuple[int, int] | None = None
    for i in range(len(chunk_words)):
        for j in range(i + 1, len(chunk_words) + 1):
            window = _normalised(" ".join(w["content"] for w in chunk_words[i:j]))
            if quote_norm in window:
                if best is None or (j - i) < (best[1] - best[0]):
                    best = (i, j)
                break  # smallest j for this i is enough
    if best is None:
        return None
    i, j = best
    return [{"page": w["page"], "bbox": list(w["bbox"])} for w in chunk_words[i:j]]
