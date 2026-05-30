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
