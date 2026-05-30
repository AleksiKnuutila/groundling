from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.prep import run_prep
from groundling.render_cmd import run_render


def _seeded_prep(tmp_path, text_pdf) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    return corpus, prep_dir


def _chunk_id_from_prep(prep_dir: Path, stem: str) -> tuple[str, str]:
    chunks = json.loads((prep_dir / f"{stem}.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    return first["chunk_id"], first["text"].split()[0]  # first word as quote


def test_run_render_valid_pdf_marker_creates_cite(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'The first word is [chunk=sample:{chunk_id} quote="{quote}"] indeed.'
    )
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert "[1]" in result.markdown
    assert "(no citations" not in result.markdown
    assert (result.run_dir / "cites" / "1.html").exists()
    assert result.counters["validated"] == 1
    assert result.counters["invalid_chunk"] == 0
    assert result.counters["invalid_quote"] == 0


def test_run_render_invalid_chunk_dropped(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    answer = 'fake [chunk=sample:p99:bFF quote="x"] cite.'
    # Pair with one valid cite so we don't trigger zero-cites exit.
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer += f' real [chunk=sample:{chunk_id} quote="{quote}"] one.'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert result.counters["invalid_chunk"] == 1
    assert result.counters["validated"] == 1
    # The fake marker is gone from the rewritten markdown.
    assert "p99:bFF" not in result.markdown


def test_run_render_web_marker(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'doc [chunk=sample:{chunk_id} quote="{quote}"] and '
        'web [url="https://example.com/x" quote="cited text"].'
    )
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert "[1]" in result.markdown and "[2]" in result.markdown
    web_html = (result.run_dir / "cites" / "2.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html


def test_run_render_zero_markers_returns_zero_cites_counter(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    answer = 'no cites here.'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    assert result.counters["validated"] == 0


def test_cli_render_reads_answer_from_stdin(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'see [chunk=sample:{chunk_id} quote="{quote}"] here.'
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(prep_dir), "--answer", "-"], input=answer,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "[1]" in result.stdout
