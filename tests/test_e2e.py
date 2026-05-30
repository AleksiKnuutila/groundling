"""End-to-end smoke: corpus → orchestrator → static HTML files on disk."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from groundling.orchestration import run_ask


def _ns(**kw):
    return SimpleNamespace(**kw)


def _fake_response_with_pdf_and_web_cites():
    return _ns(content=[
        _ns(type="text", text="The first paragraph says ", citations=None),
        _ns(type="text", text="Hello world.",
            citations=[_ns(
                type="char_location", document_index=0,
                document_title="sample.pdf",
                cited_text="some source quote",
                start_char_index=0, end_char_index=12,
            )]),
        _ns(type="text", text=" Analysts confirm.",
            citations=[_ns(
                type="web_search_result_location",
                url="https://example.com/analyst",
                title="Analyst piece",
                cited_text="Hello world reports it",
                encrypted_index="EncIdxFoo",
            )]),
    ])


def test_full_flow(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response_with_pdf_and_web_cites()

    result = run_ask(
        corpus_dir=corpus,
        question="what does the first paragraph say?",
        web_search=True,
        client=fake_client,
    )

    # Markdown ends each cited block with the right [N] marker and
    # lists a file:// reference for each cite.
    md = result.answer_md
    assert "Hello world.[1]" in md
    assert " Analysts confirm.[2]" in md
    base = f"file://{result.run_dir.resolve()}/cites"
    assert f"[1]: {base}/1.html" in md
    assert f"[2]: {base}/2.html" in md

    # PDF cite produced an HTML + PNG; web cite is a redirect stub.
    cites = result.run_dir / "cites"
    assert (cites / "1.html").exists()
    assert (cites / "1.png").exists()
    assert (cites / "2.html").exists()
    assert not (cites / "2.png").exists()  # web cite has no image
    pdf_html = (cites / "1.html").read_text()
    assert "Citation 1 / 2" in pdf_html
    assert "sample.pdf, page 1" in pdf_html
    web_html = (cites / "2.html").read_text()
    assert "<meta http-equiv=\"refresh\"" in web_html
    assert "Hello%20world%20reports%20it" in web_html

    # Manifest is structurally complete.
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["run_id"] == result.run_dir.name
    assert manifest["web_search"] is True
    assert [c["source_type"] for c in manifest["citations"]] == ["pdf", "web"]
