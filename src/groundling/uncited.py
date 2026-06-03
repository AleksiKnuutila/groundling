"""Span-finding for Pass 1 (uncited-claims) judge output.

Each uncited entry from /tmp/groundling-judge/uncited.json is a
{"span_text": "...", "before_context": "...", "after_context": "...",
 "note": "..."} pointing at a factual claim in the answer that the
judge flagged as uncited. We find each span in the rewritten markdown,
disambiguating with surrounding context, and emit wrap instructions
that render.py applies before markdown to HTML conversion.

Spans that overlap an existing cite link (`[text](cite://N)` or `[N]`
reference-style footnotes) are dropped — wrapping them would produce
nested markdown links.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass


# Cite link patterns in the *rewritten* answer.md:
#   wrap-form: [claim text](cite://N)        OR  [claim text](file://… "quote")
#   point-form (reference-style footnote): [N]
# Reference-style footnote definitions at bottom:  [N]: file://…
# We DON'T want to wrap inside any of these.
_CLAIMED_RE = re.compile(
    r"\[[^\]\n]*\]\((?:cite://|file://|http)[^)]*\)"
    r"|\[\d+\](?::\s+\S+)?",
)


@dataclass
class WrapInstruction:
    start: int          # char offset into the rewritten markdown
    end: int            # exclusive
    span_text: str
    note: str
    synthetic_id: str   # e.g. "u1", "u2" — used as data-cite-id


def find_claimed_ranges(markdown: str) -> list[tuple[int, int]]:
    """Find character ranges in `markdown` that are part of cite link
    constructions (wrap-form, point-form, or footnote definitions).
    Returns list of (start, end) tuples sorted by start.
    """
    return [(m.start(), m.end()) for m in _CLAIMED_RE.finditer(markdown)]


def _overlaps_claimed(start: int, end: int,
                      claimed: list[tuple[int, int]]) -> bool:
    """True if [start, end) intersects any claimed range."""
    for cs, ce in claimed:
        if start < ce and cs < end:
            return True
    return False


def find_uncited_spans(
    markdown: str,
    uncited_entries: list[dict],
) -> tuple[list[WrapInstruction], dict[str, int]]:
    """Locate each uncited span in `markdown`, returning wrap
    instructions plus counters: {uncited_matched, uncited_unmatched,
    uncited_overlap}.
    """
    counters = {
        "uncited_matched": 0,
        "uncited_unmatched": 0,
        "uncited_overlap": 0,
    }
    claimed = find_claimed_ranges(markdown)
    instructions: list[WrapInstruction] = []
    next_synth = 1
    for entry in uncited_entries:
        span = entry["span_text"]
        before = entry.get("before_context") or ""
        after = entry.get("after_context") or ""
        # Find ALL occurrences of span_text in the markdown.
        occurrences: list[int] = []
        start = 0
        while True:
            idx = markdown.find(span, start)
            if idx < 0:
                break
            occurrences.append(idx)
            start = idx + 1  # allow overlapping matches; unlikely but safe
        # Filter out those overlapping a claimed range.
        viable = [
            i for i in occurrences
            if not _overlaps_claimed(i, i + len(span), claimed)
        ]
        if not viable:
            if occurrences:
                # Found, but all overlapped a cite link — count as overlap.
                counters["uncited_overlap"] += 1
            else:
                counters["uncited_unmatched"] += 1
            continue
        # Disambiguate with before/after context.
        chosen: int | None = None
        if len(viable) == 1:
            chosen = viable[0]
        else:
            def score(idx: int) -> int:
                s = 0
                if before:
                    pre = markdown[max(0, idx - len(before)):idx]
                    if pre.endswith(before):
                        s += 2
                if after:
                    post = markdown[
                        idx + len(span):idx + len(span) + len(after)
                    ]
                    if post.startswith(after):
                        s += 2
                return s
            scored = [(score(i), i) for i in viable]
            scored.sort(reverse=True)
            top, top_idx = scored[0]
            # Need a non-zero score and a uniquely best match to claim it.
            if top == 0 or (len(scored) > 1 and scored[1][0] == top):
                counters["uncited_unmatched"] += 1
                continue
            chosen = top_idx
        instructions.append(WrapInstruction(
            start=chosen,
            end=chosen + len(span),
            span_text=span,
            note=entry.get("note", ""),
            synthetic_id=f"u{next_synth}",
        ))
        next_synth += 1
        counters["uncited_matched"] += 1
    # Sort by start so caller can wrap right-to-left.
    instructions.sort(key=lambda w: w.start)
    return instructions, counters


def apply_wraps(markdown: str,
                instructions: list[WrapInstruction]) -> str:
    """Apply wrap instructions to `markdown`, walking right-to-left so
    offsets stay valid. Wraps with a raw HTML anchor (CommonMark
    passes raw HTML through). data-judge-note gets HTML-escaped."""
    out = markdown
    for w in sorted(instructions, key=lambda w: -w.start):
        note_esc = html_lib.escape(w.note, quote=True)
        # span_text is rendered as the anchor's inner text. Since
        # markdown.find() located it byte-for-byte, we splice it back in
        # unchanged (markdown will continue to render it as plain text,
        # except now wrapped in our raw-HTML <a> element).
        replacement = (
            f'<a class="cite" role="button" tabindex="0" '
            f'data-cite-id="{w.synthetic_id}" data-kind="uncited" '
            f'data-state="needs-citation" '
            f'data-judge-note="{note_esc}">{w.span_text}</a>'
        )
        out = out[:w.start] + replacement + out[w.end:]
    return out
