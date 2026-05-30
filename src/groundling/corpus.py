"""Walk a corpus directory: PDF → extracted words → linearized text + offset_map."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from groundling.errors import ZeroCorpusError
from groundling.extract import extract_words
from groundling.linearize import linearize_words


@dataclass
class CorpusEntry:
    pdf_path: Path
    words: list[dict]
    linearized: str
    offset_map: list[dict]


def collect_corpus(corpus_dir: Path, *, cache_dir: Path) -> list[CorpusEntry]:
    pdfs = sorted(corpus_dir.glob("*.pdf"))
    if not pdfs:
        raise ZeroCorpusError(f"No PDFs found in {corpus_dir}")
    entries: list[CorpusEntry] = []
    for pdf in pdfs:
        words = extract_words(pdf, cache_dir=cache_dir)
        text, offset_map = linearize_words(words)
        entries.append(CorpusEntry(
            pdf_path=pdf,
            words=words,
            linearized=text,
            offset_map=offset_map,
        ))
    return entries
