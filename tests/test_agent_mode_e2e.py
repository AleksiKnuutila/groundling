"""End-to-end smoke: prep → hand-crafted agent answer → render."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from groundling.prep import run_prep
from groundling.render_cmd import run_render


def test_full_agent_mode_flow(tmp_path, text_pdf):
    # 1. Seed corpus.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")

    # 2. prep.
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    linearized = (prep_dir / "sample.linearized.txt").read_text()
    chunks = json.loads((prep_dir / "sample.chunks.json").read_text())
    assert any("[sample:" in line for line in linearized.splitlines())
    assert len(chunks) >= 1

    # 3. Hand-craft an "agent answer" using the first chunk's first word
    #    as a verbatim quote.
    first = next(c for c in chunks if c["text"])
    quote = first["text"].split()[0]
    agent_answer = (
        f'The document begins with the word '
        f'[chunk=sample:{first["chunk_id"]} quote="{quote}"] '
        f'and continues with prose.'
    )

    # 4. render.
    result = run_render(
        prep_dir=prep_dir, answer_md=agent_answer, state_dir=None,
    )
    assert "[1]" in result.markdown
    assert (result.run_dir / "cites" / "1.html").exists()
    assert (result.run_dir / "cites" / "1.png").exists()
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["citations"][0]["source_type"] == "pdf"
    assert manifest["citations"][0]["chunk_id"] == first["chunk_id"]
    assert result.counters["validated"] == 1
