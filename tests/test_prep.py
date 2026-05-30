from __future__ import annotations

import json
import shutil
from pathlib import Path

from groundling.prep import write_pdf_artifacts


def _seed(tmp_path, text_pdf) -> Path:
    out = tmp_path / "prep"
    out.mkdir()
    # text_pdf fixture already writes to tmp_path / "sample.pdf"; copy
    # only when the source lives elsewhere.
    dest = tmp_path / "sample.pdf"
    if Path(text_pdf).resolve() != dest.resolve():
        shutil.copy(text_pdf, dest)
    return out


def test_write_pdf_artifacts_writes_chunks_json(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    record = write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    chunks_file = out / "sample.chunks.json"
    assert chunks_file.exists()
    chunks = json.loads(chunks_file.read_text())
    assert isinstance(chunks, list) and len(chunks) > 0
    assert {"chunk_id", "page", "bbox", "word_idx_start", "word_idx_end", "text"}.issubset(
        chunks[0].keys()
    )


def test_write_pdf_artifacts_writes_linearized_txt(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    linearized = (out / "sample.linearized.txt").read_text()
    # Every line should be prefixed by a bracketed chunk ID like
    # `[sample:p1:b00]`.
    chunks = json.loads((out / "sample.chunks.json").read_text())
    for c in chunks:
        assert f"[sample:{c['chunk_id']}]" in linearized


def test_write_pdf_artifacts_returns_record(tmp_path, text_pdf):
    out = _seed(tmp_path, text_pdf)
    pdf = tmp_path / "sample.pdf"
    record = write_pdf_artifacts(pdf, out_dir=out, detect_tables=False)
    assert record["pdf_stem"] == "sample"
    assert record["n_chunks"] > 0
    assert record["linearized_tokens"] > 0
