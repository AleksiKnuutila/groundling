"""Skill prep entry point: chunk PDFs, output linearized text + chunks.json."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_PREP = Path(__file__).parent.parent / "skill" / "scripts" / "prep.py"


def test_skill_prep_processes_pdfs(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    out_dir = tmp_path / "prep-out"
    result = subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(out_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out_dir / "doc1.linearized.txt").exists()
    assert (out_dir / "doc1.chunks.json").exists()
    chunks = json.loads((out_dir / "doc1.chunks.json").read_text())
    assert isinstance(chunks, list)
    assert all("chunk_id" in c and "text" in c for c in chunks)


def test_skill_prep_skips_non_pdfs(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    (corpus / "ignore.txt").write_text("ignore me")
    out_dir = tmp_path / "prep-out"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(out_dir)],
        check=True, capture_output=True,
    )
    assert (out_dir / "doc1.linearized.txt").exists()
    assert not (out_dir / "ignore.linearized.txt").exists()


def test_skill_prep_exits_2_on_empty_corpus(tmp_path):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    result = subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
