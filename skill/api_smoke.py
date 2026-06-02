#!/usr/bin/env python3
"""Real-API smoke test: upload the skill via the Anthropic Skills API,
upload a PDF via the Files API, ask a question via Messages with
code_execution + skill_id, save the resulting answer.html.

Usage:
    uv run python skill/api_smoke.py

Reads ANTHROPIC_API_KEY from /srv/research/code/groundswell/.env.
Writes the rendered answer.html (if produced) and the raw response
JSON to /tmp/groundling-api-smoke/.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv


SKILL_ZIP = Path(__file__).parent / "dist" / "groundling-skill.zip"
PDF_PATH = Path("/tmp/grounded-qa-e2e/BYD-2025-Q1.pdf")
OUT_DIR = Path("/tmp/groundling-api-smoke")
QUESTION = (
    "Use the groundling skill to answer this. The PDF has been "
    "uploaded into your container — find it via `ls /` and the "
    "common upload paths (it should be under /mnt/user-data/ or "
    "similar). Move/copy it into a corpus directory, then run the "
    "skill's workflow: bootstrap, prep, render. Question: what was "
    "BYD's operating revenue for the Q1 2025 reporting period and "
    "what was the year-on-year growth rate? Cite verbatim. Produce "
    "the answer.html artifact and copy it to /files/output/."
)

BETAS = [
    "skills-2025-10-02",
    "code-execution-2025-08-25",
    "files-api-2025-04-14",
]


def main():
    load_dotenv("/srv/research/code/groundswell/.env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=api_key)

    print(f"== Step 1: upload skill from {SKILL_ZIP} ==")
    assert SKILL_ZIP.exists(), f"skill zip missing at {SKILL_ZIP}"
    with SKILL_ZIP.open("rb") as f:
        skill = client.beta.skills.create(
            display_title="groundling",
            files=[("groundling-skill.zip", f, "application/zip")],
            betas=BETAS,
        )
    print(f"  skill_id={skill.id}")
    print(f"  source={skill.source}")
    print(f"  latest_version={skill.latest_version}")

    print(f"\n== Step 2: upload PDF {PDF_PATH} ==")
    assert PDF_PATH.exists(), f"PDF missing at {PDF_PATH}"
    with PDF_PATH.open("rb") as f:
        file_obj = client.beta.files.upload(
            file=("BYD-2025-Q1.pdf", f, "application/pdf"),
            betas=BETAS,
        )
    print(f"  file_id={file_obj.id}")

    print(f"\n== Step 3: Messages call with skill + code execution ==")
    print(f"  question: {QUESTION!r}")
    t0 = time.time()
    response = client.beta.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8192,
        betas=BETAS,
        container={
            "skills": [
                {"type": "custom", "skill_id": skill.id,
                 "version": skill.latest_version},
            ],
        },
        tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
        messages=[{
            "role": "user",
            "content": [
                # container_upload places the file into the sandbox
                # filesystem (vs document which puts content in
                # model context only).
                {"type": "container_upload", "file_id": file_obj.id},
                {"type": "text", "text": QUESTION},
            ],
        }],
    )
    dt = time.time() - t0
    print(f"  took {dt:.1f}s, stop_reason={response.stop_reason}")

    print(f"\n== Step 4: save response ==")
    (OUT_DIR / "response.json").write_text(
        response.model_dump_json(indent=2), encoding="utf-8",
    )

    # Walk content blocks. Surfaced files come back nested inside
    # bash_code_execution_tool_result.content[].file_id — NOT as
    # top-level container_upload blocks.
    text_chunks = []
    code_runs = []
    file_refs = []
    for block in response.content:
        bt = block.type
        if bt == "text":
            text_chunks.append(block.text)
        elif bt == "server_tool_use":
            code_runs.append({
                "name": block.name,
                "input": getattr(block, "input", None),
            })
        elif bt.endswith("_tool_result"):
            cr = {"tool_use_id": block.tool_use_id}
            if hasattr(block, "content"):
                c = block.content
                cr["content"] = c.model_dump() if hasattr(c, "model_dump") else str(c)
            code_runs.append(cr)
            # Surfaced file ids live inside the content payload.
            inner = getattr(c, "content", None) if hasattr(block, "content") else None
            if inner:
                for item in inner:
                    fid = getattr(item, "file_id", None)
                    if fid:
                        file_refs.append(fid)
        elif bt == "container_upload":  # also catch top-level if present
            file_refs.append(block.file_id)

    print(f"  text blocks: {len(text_chunks)}")
    print(f"  code runs: {len(code_runs)}")
    print(f"  container_upload files: {len(file_refs)}")

    if text_chunks:
        full_text = "\n\n".join(text_chunks)
        (OUT_DIR / "answer.md").write_text(full_text, encoding="utf-8")
        print(f"\n--- model's text response (saved to {OUT_DIR}/answer.md) ---")
        print(full_text[:2000])
        if len(full_text) > 2000:
            print(f"... ({len(full_text) - 2000} more chars)")

    # Try to download any container_upload files.
    for fid in file_refs:
        print(f"\n== Downloading container file {fid} ==")
        try:
            content = client.beta.files.download(fid, betas=BETAS)
            data = content.read() if hasattr(content, "read") else bytes(content)
            # Heuristic: HTML?
            if data[:20].strip().lower().startswith((b"<!doctype", b"<html")):
                out = OUT_DIR / f"{fid}.html"
            else:
                out = OUT_DIR / f"{fid}.bin"
            out.write_bytes(data)
            print(f"  saved to {out} ({len(data)} bytes)")
        except Exception as e:
            print(f"  download failed: {e}")

    print(f"\n== Step 5: cleanup ==")
    # Skills have versions that must be deleted first.
    try:
        versions = client.beta.skills.versions.list(skill.id, betas=BETAS)
        for v in versions.data:
            client.beta.skills.versions.delete(
                skill_id=skill.id, version=v.version, betas=BETAS,
            )
    except Exception as e:
        print(f"  version cleanup error (non-fatal): {e}")
    try:
        client.beta.skills.delete(skill.id, betas=BETAS)
    except Exception as e:
        print(f"  skill delete error (non-fatal): {e}")
    try:
        client.beta.files.delete(file_obj.id, betas=BETAS)
    except Exception as e:
        print(f"  file delete error (non-fatal): {e}")
    print("  cleanup done.")

    print(f"\nDONE. Artifacts in {OUT_DIR}/")


if __name__ == "__main__":
    main()
