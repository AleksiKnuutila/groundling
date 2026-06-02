#!/usr/bin/env python3
"""Real-API smoke test for the web-evidence path. Uploads the
groundling skill, asks a question that requires web_search, and
saves the resulting answer.html for inspection.

Usage:
    uv run python skill/api_smoke_web.py

Costs: ~30-60s of model time + a few web_search calls. Real money.

Asserts the downloaded HTML contains:
  - data-kind="web"
  - class="preview preview-text"
  - <mark>
  - at least one href="http

If counters in the model's render output show missing_evidence > 0
or invalid_quote_web > 0, the model failed to follow the deposit
protocol — first fix is to tighten SKILL.md Step 2b wording, then
rebuild the zip and retry.

Reads ANTHROPIC_API_KEY from /srv/research/code/groundswell/.env.
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
OUT_DIR = Path("/tmp/groundling-api-smoke-web")
QUESTION = (
    "Use the groundling skill to answer this. You will need to use "
    "web_search to find current information; for each source you cite, "
    "deposit a JSON evidence file at /tmp/groundling-web/ per the "
    "skill's Step 2b protocol. Question: What was the most recent "
    "quarterly net income reported by Saudi Aramco? Cite verbatim from "
    "the source. Produce the answer.html artifact and copy it to "
    "/files/output/."
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

    print(f"\n== Step 2: Messages call with skill + code execution + web_search ==")
    print(f"  question: {QUESTION!r}")
    t0 = time.time()
    # Tool types verified against anthropic SDK 0.105.2:
    #   web_search_20250305 (name="web_search") — confirmed in
    #   anthropic/types/web_search_tool_20250305_param.py
    #   code_execution_20250825 — same as api_smoke.py
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
        tools=[
            {"type": "code_execution_20250825", "name": "code_execution"},
            {"type": "web_search_20250305", "name": "web_search"},
        ],
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": QUESTION},
            ],
        }],
    )
    dt = time.time() - t0
    print(f"  took {dt:.1f}s, stop_reason={response.stop_reason}")

    print(f"\n== Step 3: save response ==")
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

    # Try to download any container_upload files. Track HTML paths
    # for the assertion pass.
    html_paths: list[Path] = []
    for fid in file_refs:
        print(f"\n== Downloading container file {fid} ==")
        try:
            content = client.beta.files.download(fid, betas=BETAS)
            data = content.read() if hasattr(content, "read") else bytes(content)
            # Heuristic: HTML?
            if data[:20].strip().lower().startswith((b"<!doctype", b"<html")):
                out = OUT_DIR / f"{fid}.html"
                html_paths.append(out)
            else:
                out = OUT_DIR / f"{fid}.bin"
            out.write_bytes(data)
            print(f"  saved to {out} ({len(data)} bytes)")
        except Exception as e:
            print(f"  download failed: {e}")

    print(f"\n== Step 4: cleanup ==")
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
    print("  cleanup done.")

    print(f"\n== Step 5: HTML assertions ==")
    if not html_paths:
        print("  FAIL: no HTML artifact downloaded; cannot assert.")
        print(f"\nDONE (with failures). Artifacts in {OUT_DIR}/")
        sys.exit(1)

    # Run assertions against the first HTML artifact. Each check
    # prints pass/fail to stdout; failures flip the exit code to 1.
    html_path = html_paths[0]
    html = html_path.read_text(encoding="utf-8", errors="replace")
    print(f"  asserting on {html_path} ({len(html)} chars)")

    checks = [
        ('data-kind="web"',
         'data-kind="web"' in html),
        ('class="preview preview-text"',
         'class="preview preview-text"' in html),
        ('<mark>',
         '<mark>' in html),
        ('href="http',
         'href="http' in html),
    ]
    failed = 0
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] contains {label}")
        if not ok:
            failed += 1

    print(f"\nDONE. Artifacts in {OUT_DIR}/")
    if failed:
        print(f"  {failed} assertion(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
