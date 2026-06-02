import json
from pathlib import Path
import sys

# Make sibling import work the same way other tests do.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skill" / "scripts"))
import render  # noqa: E402


def _write_ev(dir, name, payload):
    (dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_load_web_evidence_missing_dir_returns_empty(tmp_path):
    assert render.load_web_evidence(tmp_path / "nope") == {}


def test_load_web_evidence_empty_dir_returns_empty(tmp_path):
    assert render.load_web_evidence(tmp_path) == {}


def test_load_web_evidence_valid_file_indexed_by_url(tmp_path):
    _write_ev(tmp_path, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "hello world",
    })
    ev = render.load_web_evidence(tmp_path)
    assert "https://example.com/a" in ev
    assert ev["https://example.com/a"]["extracted_text"] == "hello world"


def test_load_web_evidence_skips_malformed_json(tmp_path, capsys):
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    _write_ev(tmp_path, "good.json", {
        "url": "https://example.com/x", "title": "X",
        "fetched_at": "2026-06-02T00:00:00Z", "extracted_text": "t",
    })
    ev = render.load_web_evidence(tmp_path)
    assert list(ev) == ["https://example.com/x"]
    assert "bad.json" in capsys.readouterr().err


def test_load_web_evidence_skips_missing_required_keys(tmp_path, capsys):
    _write_ev(tmp_path, "01.json", {"url": "https://x.com/", "title": "X"})
    assert render.load_web_evidence(tmp_path) == {}
    assert "01.json" in capsys.readouterr().err


def test_load_web_evidence_skips_non_dict_json(tmp_path, capsys):
    """A file that parses as valid JSON but isn't an object (e.g. a
    bare string or array) must be skipped with a warning, not crash."""
    (tmp_path / "bad.json").write_text('"just a string"', encoding="utf-8")
    (tmp_path / "list.json").write_text('[1, 2, 3]', encoding="utf-8")
    _write_ev(tmp_path, "good.json", {
        "url": "https://example.com/x", "title": "X",
        "fetched_at": "2026-06-02T00:00:00Z", "extracted_text": "t",
    })
    ev = render.load_web_evidence(tmp_path)
    assert list(ev) == ["https://example.com/x"]
    err = capsys.readouterr().err
    assert "bad.json" in err
    assert "list.json" in err


def test_compute_excerpt_middle(tmp_path):
    text = "a" * 200 + "QUOTE" + "b" * 200
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert "QUOTE" in excerpt
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"


def test_compute_excerpt_quote_at_start(tmp_path):
    text = "QUOTE" + "x" * 500
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert off == 0
    assert excerpt.startswith("QUOTE")


def test_compute_excerpt_quote_at_end(tmp_path):
    text = "x" * 500 + "QUOTE"
    excerpt, off = render.compute_excerpt(text, "QUOTE", window=150)
    assert excerpt.endswith("QUOTE")
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"


def test_compute_excerpt_short_text_returns_whole(tmp_path):
    excerpt, off = render.compute_excerpt("short QUOTE here", "QUOTE", window=150)
    assert excerpt == "short QUOTE here"
    assert excerpt[off:off + len("QUOTE")] == "QUOTE"


import subprocess


def _run_render(tmp_path, answer_md, web_dir=None, prep_dir=None, corpus=None):
    answer = tmp_path / "answer.md"
    answer.write_text(answer_md, encoding="utf-8")
    out = tmp_path / "answer.html"
    cmd = ["python", str(Path(__file__).resolve().parents[1]
                          / "skill" / "scripts" / "render.py"),
           "--answer", str(answer), "--out", str(out)]
    if web_dir: cmd += ["--web-dir", str(web_dir)]
    if prep_dir: cmd += ["--prep-dir", str(prep_dir)]
    if corpus: cmd += ["--corpus", str(corpus)]
    return subprocess.run(cmd, capture_output=True, text=True), out


def test_web_marker_valid_produces_cite(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "Foo bar baz the quoted text more words",
    })
    md = '[claim](web://https://example.com/a "the quoted text")'
    proc, out = _run_render(tmp_path, md, web_dir=web)
    assert proc.returncode == 0, proc.stderr
    assert "validated=1" in proc.stderr
    assert "missing_evidence=0" in proc.stderr
    assert "invalid_quote_web=0" in proc.stderr


def test_web_marker_missing_evidence_counter(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    md = '[c](web://https://nowhere.example/x "anything")'
    proc, _ = _run_render(tmp_path, md, web_dir=web)
    assert "missing_evidence=1" in proc.stderr
    assert proc.returncode == 5  # zero valid cites


def test_web_marker_invalid_quote_counter(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "this text does not contain the quote",
    })
    md = '[c](web://https://example.com/a "totally not present")'
    proc, _ = _run_render(tmp_path, md, web_dir=web)
    assert "invalid_quote_web=1" in proc.stderr
    assert proc.returncode == 5


def test_render_web_only_succeeds(tmp_path):
    web = tmp_path / "web"; web.mkdir()
    _write_ev(web, "01.json", {
        "url": "https://example.com/a", "title": "A",
        "fetched_at": "2026-06-02T00:00:00Z",
        "extracted_text": "the quoted text appears here",
    })
    md = '[c](web://https://example.com/a "the quoted text")'
    proc, out = _run_render(tmp_path, md, web_dir=web)
    assert proc.returncode == 0
    assert out.exists()


def test_render_neither_flag_errors(tmp_path):
    answer = tmp_path / "answer.md"; answer.write_text("hi")
    out = tmp_path / "answer.html"
    cmd = ["python", str(Path(__file__).resolve().parents[1]
                          / "skill" / "scripts" / "render.py"),
           "--answer", str(answer), "--out", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 2
    assert "at least one" in proc.stderr.lower() or "required" in proc.stderr.lower()
