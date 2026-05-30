"""Word linearization + char-range to span lookup.

linearize_words([{content, page, bbox}, ...]) -> (linearized_text, offset_map)

offset_map entries:
    {"char_start": int, "char_end": int, "page": int, "bbox": [x0, y0, x1, y1]}

Char ranges are measured against the joined text (words separated by single
spaces). Anthropic returns char_location citations with offsets into this
exact text; resolve_range maps a citation's (start, end) to the list of
overlapping entries.
"""
from __future__ import annotations

import bisect


def linearize_words(words: list[dict]) -> tuple[str, list[dict]]:
    """Return (text, offset_map). text is words joined by single spaces."""
    parts: list[str] = []
    entries: list[dict] = []
    cursor = 0
    for i, w in enumerate(words):
        content = w["content"]
        if i > 0:
            parts.append(" ")
            cursor += 1
        parts.append(content)
        entries.append({
            "char_start": cursor,
            "char_end": cursor + len(content),
            "page": w["page"],
            "bbox": list(w["bbox"]),
        })
        cursor += len(content)
    return "".join(parts), entries


def resolve_range(entries: list[dict], char_start: int, char_end: int) -> list[dict]:
    """Return entries whose [char_start, char_end) overlaps the query range.

    Entries are assumed sorted by char_start (as linearize_words returns).
    """
    if not entries or char_end <= char_start:
        return []
    starts = [e["char_start"] for e in entries]
    i = bisect.bisect_right(starts, char_start) - 1
    if i < 0:
        i = 0
    hits: list[dict] = []
    for e in entries[i:]:
        if e["char_start"] >= char_end:
            break
        if e["char_end"] > char_start:
            hits.append(e)
    return hits
