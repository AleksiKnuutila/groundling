"""Skill render: validate markers + produce single-file inline answer.html."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_PREP = Path(__file__).parent.parent / "skill" / "scripts" / "prep.py"
SKILL_RENDER = Path(__file__).parent.parent / "skill" / "scripts" / "render.py"


def test_skill_render_produces_single_html(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    prep_out = tmp_path / "prep"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(prep_out)],
        check=True,
    )
    chunks = json.loads((prep_out / "doc1.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    cid, quote = first["chunk_id"], first["text"].split()[0]
    answer = f'See [the opening](chunk://doc1/{cid} "{quote}") here.'
    (tmp_path / "answer.md").write_text(answer, encoding="utf-8")

    out_html = tmp_path / "answer.html"
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out),
         "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(out_html)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out_html.exists()
    html = out_html.read_text(encoding="utf-8")
    assert 'src="cites/' not in html
    assert '<iframe' not in html
    assert 'data:image/png;base64,' in html
    assert 'class="cite"' in html


def test_skill_render_exits_5_on_zero_cites(tmp_path, text_pdf):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    prep_out = tmp_path / "prep"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(prep_out)],
        check=True,
    )
    (tmp_path / "answer.md").write_text("no cites here.")
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out),
         "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(tmp_path / "out.html")],
        capture_output=True, text=True,
    )
    assert result.returncode == 5
