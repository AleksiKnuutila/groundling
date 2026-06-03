"""Public exception types for groundling."""
from __future__ import annotations


class GroundlingError(Exception):
    """Base class for groundling-raised exceptions.

    Catch this to handle any groundling-specific failure mode without
    swallowing third-party errors (fitz, etc.).
    """


class NoTextError(GroundlingError):
    """A PDF returned no extractable text (probably a scan)."""


class ZeroCorpusError(GroundlingError):
    """Corpus directory contains no PDFs."""
