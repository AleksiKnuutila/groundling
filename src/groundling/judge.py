"""Load judge deposits from /tmp/groundling-judge/ (or any --judge-dir).

Two deposit files:
  verdicts.json — Pass 2 output. Map cite_id (str) -> {state, note}.
  uncited.json  — Pass 1 output. List of {span_text, before_context,
                  after_context, note}.

Render reads whichever exist; both are optional. Malformed entries are
dropped with a stderr warning rather than failing the render.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VALID_STATES = {"supported", "partial", "unsupported"}


def load_verdicts(judge_dir: Path | None) -> dict[int, dict]:
    """Return {cite_id: {"state", "note"}} or {} when absent/malformed.

    Drops entries with unknown states or missing fields; logs counts
    to stderr. Caller decides what to do with missing/unmapped cites
    after cross-referencing against the rendered cite_records.
    """
    if judge_dir is None:
        return {}
    path = judge_dir / "verdicts.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warn: judge_dir/verdicts.json malformed: {exc}",
              file=sys.stderr)
        return {}
    if not isinstance(raw, dict):
        print("warn: verdicts.json must be a JSON object", file=sys.stderr)
        return {}
    out: dict[int, dict] = {}
    for key, val in raw.items():
        try:
            cid = int(key)
        except (TypeError, ValueError):
            print(f"warn: verdicts.json key {key!r} is not an int; skipping",
                  file=sys.stderr)
            continue
        if not isinstance(val, dict):
            print(f"warn: verdicts.json[{key}] is not an object; skipping",
                  file=sys.stderr)
            continue
        state = val.get("state")
        if state not in VALID_STATES:
            print(f"warn: verdicts.json[{key}].state={state!r} invalid; "
                  f"skipping (allowed: supported/partial/unsupported)",
                  file=sys.stderr)
            continue
        note = val.get("note", "")
        if not isinstance(note, str):
            note = ""
        out[cid] = {"state": state, "note": note[:300]}
    return out


def load_uncited(judge_dir: Path | None) -> list[dict]:
    """Return the parsed uncited.json list, or [] when absent/malformed.

    Each entry must have a non-empty string `span_text` and optionally
    `before_context`, `after_context`, `note` (all strings). Bad entries
    dropped with a stderr warning.
    """
    if judge_dir is None:
        return []
    path = judge_dir / "uncited.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warn: judge_dir/uncited.json malformed: {exc}",
              file=sys.stderr)
        return []
    if not isinstance(raw, list):
        print("warn: uncited.json must be a JSON array", file=sys.stderr)
        return []
    out: list[dict] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            print(f"warn: uncited.json[{i}] is not an object; skipping",
                  file=sys.stderr)
            continue
        span = entry.get("span_text")
        if not isinstance(span, str) or not span:
            print(f"warn: uncited.json[{i}].span_text missing or empty; "
                  f"skipping", file=sys.stderr)
            continue
        out.append({
            "span_text": span,
            "before_context": str(entry.get("before_context") or ""),
            "after_context": str(entry.get("after_context") or ""),
            "note": str(entry.get("note") or "")[:300],
        })
    return out
