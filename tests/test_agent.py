from __future__ import annotations

from groundling.agent import (
    MAX_PDFS_IN_SESSION,
    MAX_TOKENS_IN_SESSION,
    SUBAGENT_PROMPT_TEMPLATE,
    compute_dispatch_hint,
)


def _record(n_chunks=10, linearized_tokens=1000):
    return {"n_chunks": n_chunks, "linearized_tokens": linearized_tokens}


def test_small_corpus_recommends_in_session():
    hint = compute_dispatch_hint([_record(), _record()])
    assert hint["recommend"] == "in_session"
    assert hint["n_pdfs"] == 2


def test_many_pdfs_recommends_fanout():
    records = [_record() for _ in range(MAX_PDFS_IN_SESSION + 1)]
    hint = compute_dispatch_hint(records)
    assert hint["recommend"] == "subagent_fanout"
    assert hint["n_pdfs"] == MAX_PDFS_IN_SESSION + 1


def test_many_tokens_recommends_fanout():
    records = [_record(linearized_tokens=MAX_TOKENS_IN_SESSION + 1)]
    hint = compute_dispatch_hint(records)
    assert hint["recommend"] == "subagent_fanout"


def test_dispatch_hint_includes_aggregate_counts():
    records = [_record(n_chunks=10, linearized_tokens=500),
               _record(n_chunks=15, linearized_tokens=800)]
    hint = compute_dispatch_hint(records)
    assert hint["n_chunks"] == 25
    assert hint["linearized_tokens"] == 1300


def test_subagent_prompt_template_has_required_placeholders():
    """The prompt template is shipped as a string with {pdf_path} and
    {question} placeholders that AGENTS.md fills at dispatch time."""
    assert "{pdf_path}" in SUBAGENT_PROMPT_TEMPLATE
    assert "{question}" in SUBAGENT_PROMPT_TEMPLATE
    # And it carries the marker contract verbatim.
    assert "[chunk=" in SUBAGENT_PROMPT_TEMPLATE
    assert "[url=" in SUBAGENT_PROMPT_TEMPLATE
