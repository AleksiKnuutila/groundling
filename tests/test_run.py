from __future__ import annotations

import json
import re

from groundling.run import slugify_question, write_run_dir


def test_slugify_normal_question():
    # "What" is dropped as a leading question word, "was" as a stopword,
    # "'s" splits into a tiny token kept as part of the slug.
    assert slugify_question("What was BYD's Q1 2025 revenue?") == "byd-s-q1-2025-revenue"


def test_slugify_strips_punctuation_and_lowercases():
    assert slugify_question("Hello, World!") == "hello-world"


def test_slugify_caps_length():
    long_q = "a " * 200
    out = slugify_question(long_q)
    assert len(out) <= 50


def test_slugify_empty_falls_back_to_hex():
    out = slugify_question("???   ")
    assert re.fullmatch(r"[0-9a-f]{6}", out)


def test_write_run_dir_creates_files(tmp_path):
    state = tmp_path / "qa-runs"
    state.mkdir()
    docs = [{"doc_idx": 0, "pdf_path": "/abs/a.pdf"}]
    manifest = {
        "run_id": "ignored",
        "model": "m", "question": "q", "web_search": False,
        "docs": docs, "citations": [],
    }
    run_dir = write_run_dir(
        state_dir=state,
        question="what is X?",
        manifest=manifest,
        response_json={"raw": True},
    )
    assert run_dir.parent == state
    assert (run_dir / "question.txt").read_text() == "what is X?"
    persisted = json.loads((run_dir / "manifest.json").read_text())
    assert persisted["run_id"] == run_dir.name
    assert (run_dir / "response.json").exists()
    assert (run_dir / "cites").is_dir()


def test_write_run_dir_unique_run_ids(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    r1 = write_run_dir(
        state_dir=state, question="same question",
        manifest={"citations": []}, response_json={},
    )
    r2 = write_run_dir(
        state_dir=state, question="same question",
        manifest={"citations": []}, response_json={},
    )
    assert r1 != r2


def test_run_dir_name_starts_with_timestamp(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    run = write_run_dir(
        state_dir=state, question="hi",
        manifest={"citations": []}, response_json={},
    )
    # Timestamp pattern YYYY-MM-DDTHH-MM-SS
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_", run.name)
