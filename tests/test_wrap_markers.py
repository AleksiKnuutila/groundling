"""Wrap-style marker parsing + rendering."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from groundling.cli import app
from groundling.markers import parse_markers
from groundling.prep import run_prep
from groundling.render_cmd import run_render


def test_parse_wrap_pdf_marker():
    md = '[Q1 revenue was X](chunk://BYD-2025-Q1/p2:t0r1c1 "170,360,448,000.00") in numbers.'
    ms = parse_markers(md)
    assert len(ms) == 1
    m = ms[0]
    assert m.kind == "pdf"
    assert m.wrap_kind == "wrap"
    assert m.pdf_stem == "BYD-2025-Q1"
    assert m.chunk_id == "p2:t0r1c1"
    assert m.claim_text == "Q1 revenue was X"
    assert m.quote == "170,360,448,000.00"


def test_parse_wrap_web_marker():
    md = '[Tesla overtook BYD](web://https://example.com/news "Tesla overtook BYD in Q2").'
    ms = parse_markers(md)
    assert len(ms) == 1
    m = ms[0]
    assert m.kind == "web"
    assert m.wrap_kind == "wrap"
    assert m.url == "https://example.com/news"
    assert m.claim_text == "Tesla overtook BYD"
    assert m.quote == "Tesla overtook BYD in Q2"


def test_parse_mixed_wrap_and_point_markers():
    md = (
        'See [the revenue figure](chunk://Doc/p1:b00 "1.7 billion") and '
        'an old-style [chunk=Doc:p1:b01 quote="growth"] cite.'
    )
    ms = parse_markers(md)
    assert len(ms) == 2
    # Sorted by span_start.
    assert ms[0].wrap_kind == "wrap"
    assert ms[0].claim_text == "the revenue figure"
    assert ms[1].wrap_kind == "point"


def test_parse_ordinary_markdown_link_is_not_a_cite():
    md = 'see [the docs](https://example.com/docs) for details.'
    assert parse_markers(md) == []


def _seeded_prep(tmp_path: Path, text_pdf: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    return corpus, prep_dir


def _first_chunk(prep_dir: Path, stem: str) -> tuple[str, str]:
    chunks = json.loads((prep_dir / f"{stem}.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    return first["chunk_id"], first["text"].split()[0]


def test_run_render_wrap_marker_rewrites_url_and_keeps_claim(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _first_chunk(prep_dir, "sample")
    answer = (
        f'See [the opening line]'
        f'(chunk://sample/{chunk_id} "{quote}") for the lede.'
    )
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123",
    )
    md = result.markdown
    # Claim text preserved, URL rewritten, no [N] footnote appended.
    assert "[the opening line]" in md
    assert "chunk://" not in md
    assert f"http://localhost:8123/{result.run_dir.name}/cites/1.html" in md
    assert quote in md  # title attribute carries the quote
    # No reference appendix because all cites are wrap-style.
    assert "[1]:" not in md
    assert result.counters["validated"] == 1


def test_run_render_invalid_wrap_marker_drops_link(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    answer = (
        'Bogus [claim text]'
        '(chunk://sample/p99:bFF "not in any chunk") here.'
    )
    chunk_id, quote = _first_chunk(prep_dir, "sample")
    answer += f' Real [chunk=sample:{chunk_id} quote="{quote}"] cite.'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    # The wrap marker had a bad chunk_id, so the link is dropped.
    assert "chunk://" not in result.markdown
    assert "[claim text]" not in result.markdown
    assert result.counters["invalid_chunk"] == 1
    assert result.counters["validated"] == 1


def test_run_render_mixed_wrap_and_point_emits_both_correctly(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _first_chunk(prep_dir, "sample")
    answer = (
        f'A [wrapped claim](chunk://sample/{chunk_id} "{quote}") '
        f'and a footnote [chunk=sample:{chunk_id} quote="{quote}"] cite.'
    )
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    md = result.markdown
    assert "[wrapped claim](" in md
    assert "[2]" in md  # point marker became [2]
    # Reference appendix exists for point cite but not wrap.
    assert "[2]:" in md
    assert "[1]:" not in md
    assert result.counters["validated"] == 2


def test_manifest_records_wrap_metadata(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _first_chunk(prep_dir, "sample")
    answer = f'[A claim](chunk://sample/{chunk_id} "{quote}")'
    result = run_render(prep_dir=prep_dir, answer_md=answer, state_dir=None)
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    cite = manifest["citations"][0]
    assert cite["wrap_kind"] == "wrap"
    assert cite["claim_text"] == "A claim"
    assert cite["cited_text"] == quote


def test_cli_render_wrap_marker_via_stdin(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _first_chunk(prep_dir, "sample")
    answer = f'[wrapped](chunk://sample/{chunk_id} "{quote}")'
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["render", str(prep_dir), "--answer", "-",
         "--web-base", "http://localhost:8123"],
        input=answer,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "[wrapped](http://localhost:8123/" in result.stdout
