"""Test fixtures."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    """Two-page text-native PDF with known content."""
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Hello world.\nRevenue grew 20%.")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Page two content.")
    out = tmp_path / "sample.pdf"
    doc.save(out)
    doc.close()
    return out


@pytest.fixture
def empty_pdf(tmp_path: Path) -> Path:
    """One-page PDF with no text — simulates a scan."""
    doc = fitz.open()
    doc.new_page()
    out = tmp_path / "scan.pdf"
    doc.save(out)
    doc.close()
    return out
