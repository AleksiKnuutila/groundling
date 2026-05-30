"""Errors module: public exception types."""
from groundling.errors import (
    NoTextError,
    ZeroCorpusError,
    ZeroCitationsError,
)


def test_no_text_error_is_exception():
    exc = NoTextError("scan.pdf")
    assert isinstance(exc, Exception)


def test_zero_corpus_error_is_exception():
    exc = ZeroCorpusError("/empty")
    assert isinstance(exc, Exception)


def test_zero_citations_error_carries_payload(tmp_path):
    exc = ZeroCitationsError(run_dir=tmp_path, answer_md="hello\n")
    assert exc.run_dir == tmp_path
    assert exc.answer_md == "hello\n"


def test_all_errors_subclass_groundling_error():
    from groundling.errors import GroundlingError
    assert issubclass(NoTextError, GroundlingError)
    assert issubclass(ZeroCorpusError, GroundlingError)
    assert issubclass(ZeroCitationsError, GroundlingError)
