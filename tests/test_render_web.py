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
