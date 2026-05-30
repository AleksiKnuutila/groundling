from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.errors import ZeroCorpusError
from groundling.prep import run_prep


def _seed_corpus(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    return corpus


def test_run_prep_creates_prep_dir(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    assert prep_dir.parent == corpus / ".groundling-prep"
    assert (prep_dir / "sample.linearized.txt").exists()
    assert (prep_dir / "sample.chunks.json").exists()
    hint = json.loads((prep_dir / "dispatch_hint.json").read_text())
    assert hint["n_pdfs"] == 1
    assert hint["recommend"] in ("in_session", "subagent_fanout")


def test_run_prep_zero_corpus_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ZeroCorpusError):
        run_prep(empty, out_dir=None, detect_tables=False)


def test_cli_prep_prints_dir_to_stdout(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    runner = CliRunner()
    result = runner.invoke(app, ["prep", "--corpus", str(corpus), "--no-tables"])
    assert result.exit_code == 0
    # stdout is the prep dir path (single line).
    out_path = Path(result.stdout.strip())
    assert out_path.exists()
    assert (out_path / "dispatch_hint.json").exists()


def test_cli_prep_zero_corpus_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["prep", "--corpus", str(empty)])
    assert result.exit_code == 2
