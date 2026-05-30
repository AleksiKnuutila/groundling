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


# Compiled regexes. We match the brackets, then parse internals manually
# so we can handle escaped quotes inside the quote= field.
_MARKER_RE = re.compile(r"\[(?:chunk|url)=[^\[\]]*?\"(?:[^\"\\]|\\.)*\"[^\[\]]*?\]")
_CHUNK_INNER_RE = re.compile(
    r"^chunk=(?P<stem>[^:\s]+):(?P<chunk_id>[^\s]+)\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)
_URL_INNER_RE = re.compile(
    r"^url=\"(?P<url>[^\"]+)\"\s+quote=\"(?P<quote>(?:[^\"\\]|\\.)*)\"$"
)


def _unescape(s: str) -> str:
    return s.replace(r'\"', '"').replace(r"\\", "\\")


def parse_markers(markdown: str) -> list[Marker]:
    out: list[Marker] = []
    for m in _MARKER_RE.finditer(markdown):
        inner = markdown[m.start() + 1 : m.end() - 1]  # strip [ ]
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
    return out


def _normalised(text: str) -> str:
    return " ".join(text.split())


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
