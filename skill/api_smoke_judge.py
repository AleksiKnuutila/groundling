#!/usr/bin/env python3
"""Real-API smoke test for the LLM-as-judge flow. Uploads the
groundling skill (with judge support), asks a question against
a BYD Q1 2025 PDF that invites mixed verdicts, and confirms the
returned answer.html has state-colored cite anchors and a visible
Spotlight toggle (proving the judge ran end-to-end).

Usage:
    uv run python skill/api_smoke_judge.py

Costs: ~60-90s of model time (PDF read + per-cite judge subagent
fan-out). Real money.

Asserts the downloaded HTML contains:
  - data-kind="pdf"               (PDF cite anchor)
  - data-judge-note=              (proves Pass 2 verdict notes
                                   actually decorated anchors —
                                   the strict gate: this attribute
                                   is only emitted when a verdict
                                   supplied a note, never appears
                                   in the CSS/JS source)
  - class="trustbar"              (new template)
  - id="weakBtn"                  (Spotlight visible — has_judge_data=True)
  - GROUNDLING_CITES              (cite registry)

OPTIONAL (warn-only):
  - data-state="needs-citation" or data-kind="uncited"
    (Pass 1 caught an uncited claim — depends on what the model wrote)

Note: we do NOT check for `data-state="supported"`/`"partial"`/
`"unsupported"` substrings, because the template's CSS contains all
three selectors regardless of whether any anchor uses them — that
check is a false positive. `data-judge-note=` is the discriminating
signal: it only appears as an attribute on a real anchor when the
judge produced a note for that cite.

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
PDF_PATH = Path("/tmp/grounded-qa-e2e/BYD-2025-Q1.pdf")
OUT_DIR = Path("/tmp/groundling-api-smoke-judge")
QUESTION = (
    "Use the groundling skill to answer this. The PDF has been "
    "uploaded into your container — find it via `ls /` and the "
    "common upload paths (it should be under /mnt/user-data/ or "
    "similar). Move/copy it into a corpus directory, then run the "
    "skill's workflow: bootstrap, prep, render. Question: "
    "Summarise BYD's Q1 2025 operating revenue and the main drivers "
    "of growth, and assess whether the report explicitly attributes "
    "growth to specific product lines or geographies. Note any "
    "quantitative claims you cite, and call out any significant "
    "claims you can't ground in the report. Produce the answer.html "
    "artifact and copy it to /files/output/."
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

    print(f"\n== Step 6: HTML assertions ==")
    if not html_paths:
        print("  FAIL: no HTML artifact downloaded; cannot assert.")
        print(f"\nDONE (with failures). Artifacts in {OUT_DIR}/")
        sys.exit(1)

    # Run assertions against the first HTML artifact. Each required
    # check prints pass/fail to stdout; failures flip the exit code
    # to 1. Optional checks warn-only.
    html_path = html_paths[0]
    html = html_path.read_text(encoding="utf-8", errors="replace")
    print(f"  asserting on {html_path} ({len(html)} chars)")

    # `data-judge-note=` is the discriminating Pass-2 signal. The
    # template's CSS contains `data-state="supported"|"partial"|
    # "unsupported"` selectors unconditionally, so checking for those
    # substrings is a false positive. `data-judge-note=` is only
    # emitted as an HTML attribute on a real anchor when the judge
    # produced a note for that cite — it never appears in the CSS
    # or JS source.
    checks = [
        ('data-kind="pdf"',
         'data-kind="pdf"' in html),
        ('data-judge-note= (Pass 2 verdict note attached to an anchor)',
         'data-judge-note=' in html),
        ('class="trustbar"',
         'class="trustbar"' in html),
        ('id="weakBtn"',
         'id="weakBtn"' in html),
        ('GROUNDLING_CITES',
         'GROUNDLING_CITES' in html),
    ]
    failed = 0
    for label, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] contains {label}")
        if not ok:
            failed += 1

    # Optional: Pass 1 may or may not have flagged uncited claims.
    # A tight answer with everything cited is a valid outcome — just
    # a less informative smoke run. Warn but don't fail.
    pass1_caught = (
        'data-state="needs-citation"' in html
        or 'data-kind="uncited"' in html
    )
    if pass1_caught:
        print('  [INFO] Pass 1 flagged at least one uncited claim '
              '(data-state="needs-citation" or data-kind="uncited" present)')
    else:
        print('  [INFO] Pass 1 produced no uncited spans '
              '(model may have cited everything)')

    print(f"\nDONE. Artifacts in {OUT_DIR}/")
    if failed:
        print(f"  {failed} required assertion(s) failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
