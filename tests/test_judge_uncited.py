"""PR 3 — load uncited.json and wrap flagged spans with needs-citation anchors."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from groundling.judge import load_uncited
from groundling.prep import run_prep
from groundling.render_cmd import run_render
from groundling.uncited import (
    WrapInstruction,
    apply_wraps,
    find_claimed_ranges,
    find_uncited_spans,
)


# ----------------- load_uncited unit tests -----------------

def test_load_uncited_none_returns_empty():
    assert load_uncited(None) == []


def test_load_uncited_missing_file_returns_empty(tmp_path):
    """An empty judge_dir (no uncited.json) → [], no warnings."""
    assert load_uncited(tmp_path) == []


def test_load_uncited_well_formed(tmp_path):
    payload = [
        {"span_text": "a vague claim",
         "before_context": "Also, ",
         "after_context": " that lacks evidence",
         "note": "Specific factual claim with no source."},
        {"span_text": "another", "before_context": "x",
         "after_context": "y", "note": "n"},
    ]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert len(out) == 2
    assert out[0] == {
        "span_text": "a vague claim",
        "before_context": "Also, ",
        "after_context": " that lacks evidence",
        "note": "Specific factual claim with no source.",
    }
    assert out[1]["span_text"] == "another"


def test_load_uncited_malformed_json_returns_empty(tmp_path, capsys):
    (tmp_path / "uncited.json").write_text("{not json")
    out = load_uncited(tmp_path)
    assert out == []
    err = capsys.readouterr().err
    assert "uncited.json malformed" in err


def test_load_uncited_non_array_returns_empty(tmp_path, capsys):
    """The file must be a JSON array; an object is rejected."""
    (tmp_path / "uncited.json").write_text('{"span_text": "x"}')
    out = load_uncited(tmp_path)
    assert out == []
    assert "must be a JSON array" in capsys.readouterr().err


def test_load_uncited_drops_non_object_entry(tmp_path, capsys):
    payload = [
        "a string entry",
        {"span_text": "ok", "note": "n"},
    ]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert len(out) == 1
    assert out[0]["span_text"] == "ok"
    assert "not an object" in capsys.readouterr().err


def test_load_uncited_drops_missing_span_text(tmp_path, capsys):
    payload = [
        {"note": "no span text here"},
        {"span_text": "ok", "note": "n"},
    ]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert len(out) == 1
    assert out[0]["span_text"] == "ok"
    err = capsys.readouterr().err
    assert "span_text" in err and "missing" in err


def test_load_uncited_drops_empty_span_text(tmp_path, capsys):
    payload = [
        {"span_text": ""},
        {"span_text": "ok"},
    ]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert len(out) == 1
    assert out[0]["span_text"] == "ok"


def test_load_uncited_note_truncated_at_300_chars(tmp_path):
    long_note = "x" * 500
    payload = [{"span_text": "s", "note": long_note}]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert len(out[0]["note"]) == 300


def test_load_uncited_normalizes_missing_optional_fields(tmp_path):
    """Optional before/after/note default to empty strings."""
    payload = [{"span_text": "s"}]
    (tmp_path / "uncited.json").write_text(json.dumps(payload))
    out = load_uncited(tmp_path)
    assert out == [{
        "span_text": "s",
        "before_context": "",
        "after_context": "",
        "note": "",
    }]


# ----------------- find_uncited_spans unit tests -----------------

def test_find_uncited_spans_single_match():
    md = "The economy grew by 5% last year."
    entries = [
        {"span_text": "grew by 5%",
         "before_context": "economy ", "after_context": " last year",
         "note": "specific number, no source"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters == {
        "uncited_matched": 1,
        "uncited_unmatched": 0,
        "uncited_overlap": 0,
    }
    assert len(wraps) == 1
    assert wraps[0].span_text == "grew by 5%"
    assert wraps[0].synthetic_id == "u1"
    assert md[wraps[0].start:wraps[0].end] == "grew by 5%"


def test_find_uncited_spans_multiple_matches_disambiguated_by_before():
    md = "the cat sat on the mat. the cat ran away."
    entries = [
        {"span_text": "the cat",
         "before_context": ". ",  # second occurrence after the period
         "after_context": " ran",
         "note": "second cat"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_matched"] == 1
    # Should pick the SECOND occurrence (after ". ").
    assert wraps[0].start == md.find("the cat", 5)


def test_find_uncited_spans_multiple_matches_disambiguated_by_after():
    md = "the cat sat. the cat ran."
    entries = [
        {"span_text": "the cat",
         "before_context": "",
         "after_context": " sat",
         "note": "first cat"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_matched"] == 1
    assert wraps[0].start == 0


def test_find_uncited_spans_multiple_matches_no_disambiguator_unmatched():
    """Multiple matches and no scorable context => can't pick safely."""
    md = "the cat sat. the cat ran."
    entries = [
        {"span_text": "the cat",
         "before_context": "",  # no useful disambiguator
         "after_context": "",
         "note": "ambiguous"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_unmatched"] == 1
    assert counters["uncited_matched"] == 0
    assert wraps == []


def test_find_uncited_spans_multiple_matches_tied_score_unmatched():
    """If two viable matches tie on the context score, drop them both."""
    md = "AAA the span BBB the span CCC"
    entries = [
        {"span_text": "the span",
         "before_context": "XXX",  # not present anywhere
         "after_context": "YYY",
         "note": "ambiguous"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    # Both score 0, so we refuse to guess.
    assert counters["uncited_unmatched"] == 1


def test_find_uncited_spans_no_match():
    md = "The economy grew by 5% last year."
    entries = [
        {"span_text": "stock prices doubled",
         "before_context": "", "after_context": "",
         "note": "not in the text"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_unmatched"] == 1
    assert counters["uncited_matched"] == 0
    assert wraps == []


def test_find_uncited_spans_overlap_with_wrap_cite():
    """Span inside [claim](cite://N "quote") link text counts as overlap."""
    md = '[the claim text](cite://1 "the quote") and more.'
    entries = [
        {"span_text": "claim text",
         "before_context": "", "after_context": "",
         "note": "inside link text"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_overlap"] == 1
    assert counters["uncited_matched"] == 0


def test_find_uncited_spans_overlap_with_footnote_ref():
    """Span overlapping `[1]` point-form reference counts as overlap."""
    md = "See [1] for details.\n\n[1]: file:///x.html"
    entries = [
        {"span_text": "See [1]",
         "before_context": "", "after_context": "",
         "note": "overlaps footnote ref"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_overlap"] == 1
    assert counters["uncited_matched"] == 0
    assert wraps == []


def test_find_uncited_spans_overlap_with_footnote_def():
    """Span overlapping a `[1]: url` footnote definition counts overlap."""
    md = "body text here.\n\n[1]: file:///x.html"
    entries = [
        {"span_text": "[1]: file:///x.html",
         "before_context": "", "after_context": "",
         "note": "overlaps the def line"},
    ]
    wraps, counters = find_uncited_spans(md, entries)
    assert counters["uncited_overlap"] == 1


def test_find_claimed_ranges_picks_up_wrap_form():
    md = '[c](cite://1 "q") rest'
    ranges = find_claimed_ranges(md)
    assert len(ranges) == 1
    assert md[ranges[0][0]:ranges[0][1]].startswith("[c](cite://")


def test_find_claimed_ranges_picks_up_point_form():
    md = "x [1] y\n\n[1]: file:///a"
    ranges = find_claimed_ranges(md)
    # Two: inline `[1]` and the `[1]: ...` def.
    assert len(ranges) == 2


# ----------------- apply_wraps unit tests -----------------

def test_apply_wraps_emits_expected_anchor():
    md = "X is grew by 5% last."
    instr = [WrapInstruction(
        start=md.find("grew by 5%"),
        end=md.find("grew by 5%") + len("grew by 5%"),
        span_text="grew by 5%",
        note="specific number",
        synthetic_id="u1",
    )]
    out = apply_wraps(md, instr)
    assert (
        '<a class="cite" role="button" tabindex="0" '
        'data-cite-id="u1" data-kind="uncited" '
        'data-state="needs-citation" '
        'data-judge-note="specific number">grew by 5%</a>'
    ) in out


def test_apply_wraps_escapes_judge_note_html():
    md = "X has badness here."
    instr = [WrapInstruction(
        start=md.find("badness"),
        end=md.find("badness") + len("badness"),
        span_text="badness",
        note='</a><script>evil()</script>',
        synthetic_id="u1",
    )]
    out = apply_wraps(md, instr)
    # Raw </script> must be escaped in the attribute value.
    assert '</script>' not in out.split('"badness"')[0]
    # The escaped form is in the attribute.
    assert "&lt;script&gt;" in out


def test_apply_wraps_walks_right_to_left():
    """Multiple wraps don't corrupt each other's offsets."""
    md = "alpha beta gamma delta"
    a_idx = md.find("alpha")
    g_idx = md.find("gamma")
    instr = [
        WrapInstruction(start=a_idx, end=a_idx + 5,
                        span_text="alpha", note="n1", synthetic_id="u1"),
        WrapInstruction(start=g_idx, end=g_idx + 5,
                        span_text="gamma", note="n2", synthetic_id="u2"),
    ]
    out = apply_wraps(md, instr)
    assert 'data-cite-id="u1"' in out
    assert 'data-cite-id="u2"' in out
    assert ">alpha</a>" in out
    assert ">gamma</a>" in out


# ----------------- integration: run_render + uncited.json -----------------

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


def test_run_render_with_uncited_json_wraps_span(tmp_path, text_pdf):
    """uncited.json with a matching span produces a needs-citation anchor
    in the rewritten answer.md."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'Hello [opening](chunk://sample/{chunk_id} "{quote}") world. '
        f'Also, the moon is square.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "uncited.json").write_text(json.dumps([
        {"span_text": "the moon is square",
         "before_context": "Also, ",
         "after_context": ".",
         "note": "factual claim without a source"},
    ]))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        web_base="http://localhost:8123", judge_dir=judge_dir,
    )
    rewritten_md = (result.run_dir / "answer.md").read_text()
    # The uncited span has been wrapped with our raw-HTML anchor.
    assert 'data-state="needs-citation"' in rewritten_md
    assert 'data-kind="uncited"' in rewritten_md
    assert 'data-cite-id="u1"' in rewritten_md
    assert 'the moon is square</a>' in rewritten_md
    # Counters reflect the match.
    assert result.counters["uncited_matched"] == 1
    assert result.counters["uncited_unmatched"] == 0
    assert result.counters["uncited_overlap"] == 0


def test_run_render_uncited_counters_unmatched(tmp_path, text_pdf):
    """An uncited.json entry whose span isn't in the answer -> unmatched."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "uncited.json").write_text(json.dumps([
        {"span_text": "totally absent phrase", "note": "ghost"},
    ]))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    assert result.counters["uncited_matched"] == 0
    assert result.counters["uncited_unmatched"] == 1


def test_run_render_uncited_counters_overlap(tmp_path, text_pdf):
    """A span that lives inside a `[N]` point footnote counts overlap."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    # Point-form cite uses [chunk=...] marker syntax which renders to [1].
    answer = f'A claim [chunk=sample:{chunk_id} quote="{quote}"].'
    result_no_judge = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
    )
    out_md = (result_no_judge.run_dir / "answer.md").read_text()
    assert "[1]" in out_md  # confirms point-form rewrite landed
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "uncited.json").write_text(json.dumps([
        {"span_text": "[1]", "note": "overlaps footnote ref"},
    ]))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    assert result.counters["uncited_overlap"] == 1
    assert result.counters["uncited_matched"] == 0


def test_run_render_uncited_in_manifest(tmp_path, text_pdf):
    """The manifest's `uncited` array surfaces synthetic ids + spans."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}"). '
        f'Also, the moon is square.'
    )
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    (judge_dir / "uncited.json").write_text(json.dumps([
        {"span_text": "the moon is square",
         "before_context": "Also, ", "after_context": ".",
         "note": "no source"},
    ]))
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
        judge_dir=judge_dir,
    )
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert "uncited" in manifest
    assert len(manifest["uncited"]) == 1
    assert manifest["uncited"][0]["synthetic_id"] == "u1"
    assert manifest["uncited"][0]["span_text"] == "the moon is square"
    assert manifest["uncited"][0]["note"] == "no source"


def test_run_render_no_uncited_json_keeps_counters_zero(tmp_path, text_pdf):
    """No uncited.json => no wraps, counters all zero, no errors."""
    _, prep_dir = _seeded_prep(tmp_path, text_pdf)
    chunk_id, quote = _chunk_id_from_prep(prep_dir, "sample")
    answer = (
        f'See [opening](chunk://sample/{chunk_id} "{quote}") here.'
    )
    result = run_render(
        prep_dir=prep_dir, answer_md=answer, state_dir=None,
    )
    assert result.counters["uncited_matched"] == 0
    assert result.counters["uncited_unmatched"] == 0
    assert result.counters["uncited_overlap"] == 0
    rewritten = (result.run_dir / "answer.md").read_text()
    assert 'data-state="needs-citation"' not in rewritten
