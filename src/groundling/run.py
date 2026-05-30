"""Persist one Q&A run to disk: question.txt, manifest.json, response.json + cites/ dir."""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
from pathlib import Path


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "of", "on", "or", "that", "the",
    "to", "was", "were", "what", "which", "who", "with",
}


def slugify_question(question: str, *, max_len: int = 50) -> str:
    """Build a short slug from a question for run-dir naming."""
    # Lowercase, replace non-alphanum with spaces, split, drop stopwords,
    # keep first 5-6 tokens, join with hyphens, cap length.
    cleaned = re.sub(r"[^\w\s]", " ", question.lower())
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS]
    # Drop "what" specifically only when it's the leading token.
    if tokens and tokens[0] == "what":
        tokens = tokens[1:]
    slug = "-".join(tokens[:6])
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    if not slug:
        slug = secrets.token_hex(3)
    return slug


def _new_run_id(question: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    slug = slugify_question(question)
    return f"{stamp}_{slug}"


def write_run_dir(
    *,
    state_dir: Path,
    question: str,
    manifest: dict,
    response_json: dict,
) -> Path:
    run_id = _new_run_id(question)
    run_dir = state_dir / run_id
    # Collide-safety: if the same timestamp+slug somehow exists, suffix with hex.
    if run_dir.exists():
        run_id = f"{run_id}_{secrets.token_hex(2)}"
        run_dir = state_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "cites").mkdir()
    manifest = dict(manifest)
    manifest["run_id"] = run_id
    (run_dir / "question.txt").write_text(question, encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "response.json").write_text(json.dumps(response_json, indent=2))
    return run_dir
