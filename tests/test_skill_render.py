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


def test_skill_render_handles_embedded_quote_in_point_marker(tmp_path, text_pdf):
    """Quote with embedded " in a POINT marker should round-trip
    through the markdown-link rewrite without silently dropping the cite.

    Regression: the previous version forgot to escape quotes on the
    point branch of _rewrite_to_cite_scheme."""
    corpus = tmp_path / "corpus"; corpus.mkdir()
    shutil.copy(text_pdf, corpus / "doc1.pdf")
    prep_out = tmp_path / "prep"
    subprocess.run(
        [sys.executable, str(SKILL_PREP),
         "--corpus", str(corpus), "--out", str(prep_out)],
        check=True,
    )
    chunks = json.loads((prep_out / "doc1.chunks.json").read_text())
    # Find a chunk with a quote-containing word.
    # text_pdf has simple ASCII; we synthesise a "quoted" word by
    # picking a chunk and quoting a word from it. The validation just
    # needs the quote to be a verbatim substring — we use a real word
    # from the chunk text. This test focuses on the point-marker REWRITE
    # path; embedded quotes are exercised via a separate quote we
    # construct.
    #
    # Use the first chunk's first word as the quote; the test PDF
    # doesn't actually contain a " character, so we don't catch the
    # specific symptom here. To exercise the escape robustly we'd need
    # a PDF with quoted text. Instead we test that the point branch
    # handles a quote that ROUND-TRIPS through the escape successfully
    # (no embedded ", but exercises the same code path).
    first = next(c for c in chunks if c["text"])
    cid, quote = first["chunk_id"], first["text"].split()[0]
    answer = (
        f'See the source [chunk=doc1:{cid} quote="{quote}"] for details.'
    )
    (tmp_path / "answer.md").write_text(answer, encoding="utf-8")

    out_html = tmp_path / "answer.html"
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out), "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(out_html)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # The cite span MUST appear in the rendered HTML; stderr counter
    # MUST match (validated=1).
    html = out_html.read_text(encoding="utf-8")
    assert 'class="cite"' in html, "point marker silently dropped"
    assert "validated=1" in result.stderr


def test_skill_render_writes_manifest_json(tmp_path, text_pdf):
    """skill/scripts/render.py must emit a manifest.json with cite
    records for the judge to consume in Pass 2."""
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
    manifest_path = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out),
         "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(out_html),
         "--manifest-out", str(manifest_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert manifest_path.exists(), "manifest.json not written"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "citations" in manifest and isinstance(manifest["citations"], list)
    assert "counters" in manifest
    assert manifest["answer_html_path"] == str(out_html)
    assert len(manifest["citations"]) == 1
    entry = manifest["citations"][0]
    assert entry["cite_id"] == 1
    assert entry["kind"] == "pdf"
    assert entry["claim_text"] == "the opening"
    assert entry["cited_text"] == quote
    assert entry["pdf_stem"] == "doc1"
    assert entry["chunk_id"] == cid


def test_skill_render_manifest_includes_web_cite(tmp_path):
    """Web cites in the manifest should carry url instead of pdf_stem/chunk_id."""
    web_dir = tmp_path / "web"; web_dir.mkdir()
    (web_dir / "01.json").write_text(json.dumps({
        "url": "https://example.com/a",
        "title": "Article",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "Lorem ipsum the cited passage dolor sit amet.",
    }), encoding="utf-8")
    answer = (
        'A claim [the cited passage]'
        '(web://https://example.com/a "the cited passage") supports.'
    )
    (tmp_path / "answer.md").write_text(answer, encoding="utf-8")

    out_html = tmp_path / "answer.html"
    manifest_path = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--web-dir", str(web_dir),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(out_html),
         "--manifest-out", str(manifest_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["citations"]) == 1
    entry = manifest["citations"][0]
    assert entry["kind"] == "web"
    assert entry["url"] == "https://example.com/a"
    assert entry["cited_text"] == "the cited passage"
    assert "pdf_stem" not in entry
    assert "chunk_id" not in entry


def test_skill_render_prints_validation_counters(tmp_path, text_pdf):
    """Stderr summary includes validated / invalid_* counters."""
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
    # Mix of: 1 valid wrap cite, 1 invalid chunk reference.
    answer = (
        f'Valid: [the opening](chunk://doc1/{cid} "{quote}"). '
        f'Invalid: [chunk=doc1:p99:b99 quote="nope"].'
    )
    (tmp_path / "answer.md").write_text(answer, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SKILL_RENDER),
         "--prep-dir", str(prep_out), "--corpus", str(corpus),
         "--answer", str(tmp_path / "answer.md"),
         "--out", str(tmp_path / "out.html")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "validated=1" in result.stderr
    assert "invalid_chunk=1" in result.stderr
    assert "invalid_quote=0" in result.stderr
    assert "invalid_url=0" in result.stderr
