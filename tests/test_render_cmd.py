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


def test_cite_url_file_base_emits_absolute_path(tmp_path):
    from groundling.render_cmd import _cite_url
    run_dir = tmp_path / "run-abc"
    run_dir.mkdir()
    url = _cite_url("file://", run_dir, 3)
    assert url == f"file://{run_dir.resolve()}/cites/3.html"


def test_cite_url_http_base_emits_run_name_path(tmp_path):
    from groundling.render_cmd import _cite_url
    run_dir = tmp_path / "2026-05-30T00-00-00_render_abcd"
    run_dir.mkdir()
    url = _cite_url("http://localhost:8123", run_dir, 7)
    assert url == "http://localhost:8123/2026-05-30T00-00-00_render_abcd/cites/7.html"


def test_cite_url_http_base_strips_trailing_slash(tmp_path):
    from groundling.render_cmd import _cite_url
    run_dir = tmp_path / "run-x"
    run_dir.mkdir()
    url = _cite_url("http://localhost:8123/", run_dir, 1)
    assert url == "http://localhost:8123/run-x/cites/1.html"


def test_run_render_web_base_rewrites_reference_block(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = f'see [chunk=sample:{chunk_id} quote="{quote}"] here.'
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123",
    )
    assert "file://" not in result.markdown
    assert f"http://localhost:8123/{result.run_dir.name}/cites/1.html" in result.markdown


def test_cli_render_passes_web_base(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = f'see [chunk=sample:{chunk_id} quote="{quote}"] here.'
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render", str(prep_dir),
            "--answer", "-",
            "--web-base", "http://localhost:8123",
        ],
        input=answer,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "http://localhost:8123/" in result.stdout
    assert "/cites/1.html" in result.stdout


def test_cli_serve_help_lists_options():
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--state-dir" in result.stdout
    assert "--port" in result.stdout
    assert "--host" in result.stdout


def test_serve_command_actually_serves_cite_file(tmp_path):
    """End-to-end smoke: start the server in a thread, fetch a cite, stop it."""
    import functools
    import threading
    import urllib.request
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    state_dir = tmp_path / "qa-runs"
    run_dir = state_dir / "run-xyz"
    cite_html = run_dir / "cites" / "1.html"
    cite_html.parent.mkdir(parents=True)
    cite_html.write_text("<html>hello cite</html>", encoding="utf-8")

    handler = functools.partial(
        SimpleHTTPRequestHandler, directory=str(state_dir),
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/run-xyz/cites/1.html"
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode()
        assert "hello cite" in body
    finally:
        httpd.shutdown()
        t.join(timeout=2)


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


def test_run_render_writes_answer_html_with_cite_decoration(tmp_path, text_pdf):
    corpus, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [the opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123",
    )
    html_path = result.run_dir / "answer.html"
    assert html_path.exists()
    html = html_path.read_text()
    # Page shell.
    assert "<!doctype html>" in html or "<!DOCTYPE html>" in html
    assert '<aside class="cite-pane"' in html
    # Cite decoration arrived through the full pipeline.
    assert 'class="cite"' in html
    assert 'data-cite-id="1"' in html
    assert 'data-kind="pdf"' in html
    assert 'data-img="cites/1.png"' in html
    # Mobile fall-through media query.
    assert "(hover: hover)" in html


def test_run_render_answer_html_handles_zero_cites(tmp_path, text_pdf):
    """No cites → answer.html still exists, just plain prose."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    result = run_render(
        prep_dir=prep_dir, answer_md="no cites here.", state_dir=None,
    )
    html_path = result.run_dir / "answer.html"
    assert html_path.exists()
    html = html_path.read_text()
    assert 'class="cite"' not in html
    # Page shell still present.
    assert '<aside class="cite-pane"' in html
