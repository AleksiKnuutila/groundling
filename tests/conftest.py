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


@pytest.fixture
def table_pdf(tmp_path: Path) -> Path:
    """PDF with one prose paragraph + one 2x2 grid-drawn table."""
    doc = fitz.open()
    page = doc.new_page()
    # Prose paragraph
    page.insert_text((72, 72), "Some intro paragraph here.")
    # Draw a 2x2 table at y=120..200
    # Header row
    page.insert_text((100, 130), "Header A")
    page.insert_text((200, 130), "Header B")
    # Body row
    page.insert_text((100, 170), "Value 1")
    page.insert_text((200, 170), "Value 2")
    # Draw cell borders so PyMuPDF can detect the table.
    page.draw_rect(fitz.Rect(80, 120, 180, 150))  # A header
    page.draw_rect(fitz.Rect(180, 120, 280, 150))  # B header
    page.draw_rect(fitz.Rect(80, 150, 180, 200))  # A value
    page.draw_rect(fitz.Rect(180, 150, 280, 200))  # B value
    out = tmp_path / "with_table.pdf"
    doc.save(out)
    doc.close()
    return out
