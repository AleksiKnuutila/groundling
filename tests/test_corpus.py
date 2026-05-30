from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from groundling.corpus import collect_corpus, CorpusEntry
from groundling.errors import ZeroCorpusError


def test_collect_single_pdf(text_pdf, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "sample.pdf")
    entries = collect_corpus(corpus, cache_dir=tmp_path / "cache")
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, CorpusEntry)
    assert e.pdf_path == corpus / "sample.pdf"
    assert "Hello" in e.linearized or "world" in e.linearized
    assert len(e.offset_map) == len(e.linearized.split(" "))


def test_collect_sorted_by_name(text_pdf, tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(text_pdf, corpus / "zzz.pdf")
    shutil.copy(text_pdf, corpus / "aaa.pdf")
    entries = collect_corpus(corpus, cache_dir=tmp_path / "cache")
    names = [e.pdf_path.name for e in entries]
    assert names == ["aaa.pdf", "zzz.pdf"]


def test_empty_corpus_raises_zero_corpus_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ZeroCorpusError, match=str(empty)):
        collect_corpus(empty, cache_dir=tmp_path / "cache")
