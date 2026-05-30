"""Public exception types for groundling."""
from __future__ import annotations

from pathlib import Path


class GroundlingError(Exception):
    """Base class for groundling-raised exceptions.

    Catch this to handle any groundling-specific failure mode without
    swallowing third-party SDK errors (anthropic.APIError, fitz errors).
    """


class NoTextError(GroundlingError):
    """A PDF returned no extractable text (probably a scan)."""


class ZeroCorpusError(GroundlingError):
    """Corpus directory contains no PDFs."""


class ZeroCitationsError(GroundlingError):
    """The model returned a response but didn't cite anything."""

    def __init__(self, *, run_dir: Path, answer_md: str):
        super().__init__("Model returned no citations.")
        self.run_dir = run_dir
        self.answer_md = answer_md
