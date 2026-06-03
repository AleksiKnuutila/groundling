"""Errors module: public exception types."""
from groundling.errors import (
    NoTextError,
    ZeroCorpusError,
)


def test_no_text_error_is_exception():
    exc = NoTextError("scan.pdf")
    assert isinstance(exc, Exception)


def test_zero_corpus_error_is_exception():
    exc = ZeroCorpusError("/empty")
    assert isinstance(exc, Exception)


def test_all_errors_subclass_groundling_error():
    from groundling.errors import GroundlingError
    assert issubclass(NoTextError, GroundlingError)
    assert issubclass(ZeroCorpusError, GroundlingError)
