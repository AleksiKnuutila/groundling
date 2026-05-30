from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from groundling.cli import app
from groundling.errors import ZeroCorpusError, ZeroCitationsError
from groundling.orchestration import run_ask


def _ns(**kw):
    return SimpleNamespace(**kw)


def _seed_corpus(tmp_path, text_pdf) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    return corpus


def _fake_pdf_citation_response():
    """A response with one PDF citation and one cited text block."""
    return _ns(content=[
        _ns(type="text", text="The first page says ", citations=None),
        _ns(type="text", text="Hello", citations=[_ns(
            type="char_location", document_index=0,
            document_title="sample.pdf", cited_text="some source quote",
            start_char_index=0, end_char_index=5,
        )]),
        _ns(type="text", text=".", citations=None),
    ])


def test_run_ask_writes_run_dir_and_cite_html(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_pdf_citation_response()

    result = run_ask(
        corpus_dir=corpus,
        question="what does the first page say?",
        client=fake_client,
    )
    assert result.run_dir.parent == corpus / "qa-runs"
    # Markdown trails the cited block with [1] and lists the file:// ref.
    assert "[1]" in result.answer_md
    assert f"file://{result.run_dir.resolve()}/cites/1.html" in result.answer_md
    # The cite HTML and the page image both exist on disk.
    assert (result.run_dir / "cites" / "1.html").exists()
    assert (result.run_dir / "cites" / "1.png").exists()
    # Manifest written and consistent with the markdown.
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "pdf"


def test_run_ask_zero_corpus_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    fake_client = MagicMock()
    with pytest.raises(ZeroCorpusError):
        run_ask(corpus_dir=empty, question="q", client=fake_client)


def test_run_ask_zero_citations_raises_with_run_dir_and_md(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _ns(content=[
        _ns(type="text", text="No citations here.", citations=None),
    ])
    with pytest.raises(ZeroCitationsError) as ei:
        run_ask(corpus_dir=corpus, question="q", client=fake_client)
    assert ei.value.run_dir.exists()
    assert "No citations here." in ei.value.answer_md


def test_run_ask_web_search_citation_lands_in_manifest(tmp_path, text_pdf):
    corpus = _seed_corpus(tmp_path, text_pdf)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _ns(content=[
        _ns(type="text", text="Analysts agree.", citations=[_ns(
            type="web_search_result_location",
            url="https://example.com/x", title="X",
            cited_text="some quote", encrypted_index="EncIdx",
        )]),
    ])
    result = run_ask(
        corpus_dir=corpus, question="q",
        web_search=True, client=fake_client,
    )
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "web"
    # Web cite HTML is a redirect stub.
    web_html = (result.run_dir / "cites" / "1.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html


# --- CLI integration -----------------------------------------------------

def test_cli_zero_corpus_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["ask", "q", "--corpus", str(empty)])
    assert result.exit_code == 2
