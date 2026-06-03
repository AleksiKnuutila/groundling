"""PR 2 — load verdicts.json and decorate cite anchors with state + note."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from groundling.judge import VALID_STATES, load_verdicts
from groundling.prep import run_prep
from groundling.render_cmd import run_render


# ----------------- load_verdicts unit tests -----------------

def test_load_verdicts_none_returns_empty():
    assert load_verdicts(None) == {}


def test_load_verdicts_missing_file_returns_empty(tmp_path):
    """An empty judge_dir (no verdicts.json) → {}, no warnings."""
    assert load_verdicts(tmp_path) == {}


def test_load_verdicts_well_formed(tmp_path):
    payload = {
        "1": {"state": "supported", "note": "directly cited"},
        "2": {"state": "partial", "note": "adjacent figure"},
        "3": {"state": "unsupported", "note": "different doc entirely"},
    }
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert out == {
        1: {"state": "supported", "note": "directly cited"},
        2: {"state": "partial", "note": "adjacent figure"},
        3: {"state": "unsupported", "note": "different doc entirely"},
    }


def test_load_verdicts_malformed_json_returns_empty(tmp_path, capsys):
    (tmp_path / "verdicts.json").write_text("{not json")
    out = load_verdicts(tmp_path)
    assert out == {}
    err = capsys.readouterr().err
    assert "verdicts.json malformed" in err


def test_load_verdicts_non_object_returns_empty(tmp_path, capsys):
    (tmp_path / "verdicts.json").write_text('["a", "b"]')
    out = load_verdicts(tmp_path)
    assert out == {}
    assert "must be a JSON object" in capsys.readouterr().err


def test_load_verdicts_drops_invalid_state(tmp_path, capsys):
    """Entry with state='bogus' is skipped; the rest survive."""
    payload = {
        "1": {"state": "supported", "note": "ok"},
        "2": {"state": "bogus", "note": "meh"},
        "3": {"state": "partial", "note": "ok"},
    }
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert set(out.keys()) == {1, 3}
    err = capsys.readouterr().err
    assert "bogus" in err
    assert "invalid" in err


def test_load_verdicts_drops_non_int_key(tmp_path, capsys):
    payload = {
        "1": {"state": "supported", "note": "ok"},
        "foo": {"state": "supported", "note": "ok"},
        "3": {"state": "supported", "note": "ok"},
    }
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert set(out.keys()) == {1, 3}
    err = capsys.readouterr().err
    assert "'foo'" in err
    assert "not an int" in err


def test_load_verdicts_drops_missing_state(tmp_path, capsys):
    payload = {
        "1": {"note": "no state"},  # state missing => state=None
        "2": {"state": "supported", "note": "ok"},
    }
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert set(out.keys()) == {2}
    assert "invalid" in capsys.readouterr().err


def test_load_verdicts_drops_non_object_entry(tmp_path, capsys):
    payload = {
        "1": "not a dict",
        "2": {"state": "supported", "note": "ok"},
    }
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert set(out.keys()) == {2}
    assert "not an object" in capsys.readouterr().err


def test_load_verdicts_note_truncated_at_300_chars(tmp_path):
    long_note = "x" * 500
    payload = {"1": {"state": "supported", "note": long_note}}
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert len(out[1]["note"]) == 300


def test_load_verdicts_non_string_note_becomes_empty(tmp_path):
    payload = {"1": {"state": "supported", "note": 42}}
    (tmp_path / "verdicts.json").write_text(json.dumps(payload))
    out = load_verdicts(tmp_path)
    assert out[1]["note"] == ""


def test_valid_states_constant():
    """Sanity-pin the contract: the three states the design doc names."""
    assert VALID_STATES == {"supported", "partial", "unsupported"}


# ----------------- integration: run_render + judge_dir -----------------

def _seeded_prep(tmp_path, text_pdf) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    prep_dir = run_prep(corpus, out_dir=None, detect_tables=False)
    return corpus, prep_dir


def _chunk_id_from_prep(prep_dir: Path, stem: str) -> tuple[str, str]:
    chunks = json.loads((prep_dir / f"{stem}.chunks.json").read_text())
    first = next(c for c in chunks if c["text"])
    return first["chunk_id"], first["text"].split()[0]


def test_run_render_no_judge_dir_keeps_data_state_none(tmp_path, text_pdf):
    """judge_dir=None → behaves as today: every anchor data-state='none'."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123",
    )
    html = (result.run_dir / "answer.html").read_text()
    assert 'data-state="none"' in html
    assert 'data-judge-note' not in html
    # The Spotlight button must be absent (no judge data).
    assert 'id="weakBtn"' not in html
    assert result.counters["verdicts_missing"] == 0
    assert result.counters["verdicts_unmapped"] == 0


def test_run_render_with_verdicts_stamps_state_and_note(tmp_path, text_pdf):
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "verdicts.json").write_text(json.dumps({
        "1": {"state": "partial", "note": "tangential figure only"},
    }))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123", judge_dir=judge_dir,
    )
    html = (result.run_dir / "answer.html").read_text()
    assert 'data-state="partial"' in html
    assert 'data-judge-note="tangential figure only"' in html
    # Spotlight button must appear when has_judge_data is True.
    assert 'id="weakBtn"' in html


def test_run_render_verdicts_missing_counter(tmp_path, text_pdf):
    """Two cites in the answer, one verdict — verdicts_missing=1."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    # Use two cites: PDF chunk + web cite.
    answer = (
        f'a [first](chunk://sample/{chunk_id} "{quote}") b '
        '[second](web://https://example.com "anything").'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "verdicts.json").write_text(json.dumps({
        "1": {"state": "supported", "note": "ok"},
    }))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    assert result.counters["validated"] == 2
    assert result.counters["verdicts_missing"] == 1
    assert result.counters["verdicts_unmapped"] == 0


def test_run_render_verdicts_unmapped_counter(tmp_path, text_pdf):
    """Verdict mentions a cite_id that doesn't exist in this render."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "verdicts.json").write_text(json.dumps({
        "1": {"state": "supported", "note": "ok"},
        "99": {"state": "unsupported", "note": "stale"},
    }))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    assert result.counters["verdicts_unmapped"] == 1
    assert result.counters["verdicts_missing"] == 0


def test_run_render_judge_dir_malformed_skips_and_continues(
    tmp_path, text_pdf, capsys,
):
    """A garbled verdicts.json must not break the render."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "verdicts.json").write_text("{garbage")
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    # Render still produced a valid answer.html with default state.
    html = (result.run_dir / "answer.html").read_text()
    assert 'data-state="none"' in html
    assert result.counters["validated"] == 1
    # Counters are zero because verdicts dict was effectively empty.
    assert result.counters["verdicts_missing"] == 0
    assert result.counters["verdicts_unmapped"] == 0
