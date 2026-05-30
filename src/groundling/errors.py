"""Public exception types for groundling."""
from __future__ import annotations

from pathlib import Path


class NoTextError(Exception):
    """A PDF returned no extractable text (probably a scan)."""


class ZeroCorpusError(Exception):
    """Corpus directory contains no PDFs."""


class ZeroCitationsError(Exception):
    """The model returned a response but didn't cite anything."""

    def __init__(self, *, run_dir: Path, answer_md: str):
        super().__init__("Model returned no citations.")
        self.run_dir = run_dir
        self.answer_md = answer_md
