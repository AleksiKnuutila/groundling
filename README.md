# groundling

Grounded Q&A over a folder of PDFs, with cite links you can click to
verify. Designed for use from Claude Code (or any AGENTS.md-aware
agent).

Two modes — pick based on what you have:

- **Mode A — API-backed.** `groundling ask "..."` calls the Anthropic
  Messages API with citations enabled. Single command, pay-per-token.
- **Mode B — agent-driven.** `groundling prep` + agent fan-out +
  `groundling render` uses your Claude subscription. The agent reads
  per-PDF linearized text, emits cite markers, render validates them
  into clickable links.

Both modes produce `answer.md` + a self-contained `answer.html`
browser view with cite highlights, hover-to-preview-PDF popovers,
and click-opens-side-pane source viewing.

## Install

    pipx install git+https://github.com/AleksiKnuutila/groundling.git
    # or, if you use uv:
    uv tool install git+https://github.com/AleksiKnuutila/groundling.git
    # or, from a local clone:
    pipx install /path/to/groundling

## Quick start

    cd ~/my-research/        # contains your PDFs
    groundling init          # drops AGENTS.md
    claude                   # or codex, or any AGENTS.md-aware agent

In the agent session:

    > what does Q1 say about revenue growth?

The agent reads AGENTS.md, picks the appropriate mode (Mode A if
`ANTHROPIC_API_KEY` is set, Mode B otherwise), runs groundling, prints
the answer with cite links.

## Browser viewing

    groundling serve                                    # in another shell
    # then open in browser:
    http://localhost:8123/<run_id>/answer.html

Cite spans are highlighted; hover any cite to see a popover with the
source PDF region; click to open the full cite page in a side pane.

## Commands

| Command | Purpose |
| --- | --- |
| `groundling init` | Drop or refresh AGENTS.md in cwd |
| `groundling instructions` | Print AGENTS.md template to stdout |
| `groundling ask` | Mode A: one-shot question via Anthropic API |
| `groundling prep` | Mode B step 1: per-PDF chunks + linearized text |
| `groundling render` | Mode B step 2: validate agent cite markers → answer.md + answer.html |
| `groundling serve` | Static HTTP server for cite pages (default port 8123) |

Run any command with `--help` for full flag listings.

## Use as a Claude Skill

Groundling can run entirely inside Claude's code-execution sandbox —
no pipx install on the user's machine, no hosted server. The skill
is the same artifact (a zip with bundled wheels) for all three
Claude surfaces; the install mechanism differs.

Pre-built zip: download `groundling-skill-vX.Y.Z.zip` from the
[latest GitHub Release](https://github.com/AleksiKnuutila/groundling/releases),
or build it from source:

    ./skill/build_zip.sh v0.1.0
    # produces skill/dist/groundling-skill-v0.1.0.zip (~30MB)

### Claude.ai web (Pro / Max / Team / Enterprise)

1. Download the zip
2. In Claude.ai → Settings > Features > Skills > Create skill → Upload a skill
3. Upload the zip; Claude auto-invokes when you ask about PDFs in a Project

### Claude API

```python
import anthropic

client = anthropic.Anthropic()
with open("groundling-skill-v0.1.0.zip", "rb") as f:
    skill = client.beta.skills.create(
        display_title="groundling",
        files=[("groundling-skill.zip", f, "application/zip")],
        betas=["skills-2025-10-02"],
    )

# Then reference skill.id in messages.create(container={"skills": [...]})
```

See `skill/api_smoke.py` for a complete end-to-end example
(upload PDF, invoke skill, retrieve generated `answer.html`).

### Claude Code

```
mkdir -p ~/.claude/skills
cd ~/.claude/skills
curl -L \
  https://github.com/AleksiKnuutila/groundling/releases/latest/download/groundling-skill-v0.1.0.zip \
  -o tmp.zip
unzip tmp.zip && rm tmp.zip
# ~/.claude/skills/groundling/ now contains SKILL.md + scripts + wheels
```

When you ask a question about a PDF, Claude reads `SKILL.md`,
bootstraps (pip-installs from bundled wheels into the sandbox),
runs prep + render, and surfaces a self-contained `answer.html`
with cite-span hover previews of the source PDF region.

## State on disk

Per corpus directory:

- `qa-runs/<run-id>/` — one subdir per question, contains `answer.md`,
  `answer.html`, `manifest.json`, `cites/N.html`+`cites/N.png`.
- `.groundling-prep/<stamp>/` — mode-B chunks + linearized text +
  `dispatch_hint.json`.
- `.groundling-cache/` — per-PDF word-extraction cache.

All three are gitignore candidates.

## How it works

See `docs/plans/` for design docs covering each mode and the
intermediate artefacts:

- `2026-05-30-groundling-design.md` — Mode A: Anthropic Messages API with citations enabled
- `2026-05-30-agent-mode-design.md` — Mode B: prep + render + marker contract (both wrapping and point shapes)
- `2026-05-30-answer-html-design.md` — browser view with hover preview + side pane

## Limits

- **No OCR.** Scanned PDFs without extractable text exit early
  (`groundling ask` exit code 3). OCR externally first.
- **No table-structure inference for prose linearization.** Mode A
  uses PyMuPDF's reading order as-is; complex multi-column layouts
  may produce garbled linearization, though cited bboxes remain
  correct per-word. Mode B uses `find_tables()` for tighter
  per-cell chunks (on by default; pass `--no-tables` to disable).
- **No persistent project model.** Each invocation is a fresh,
  isolated run. Past runs accumulate under `qa-runs/`.

## License

TBD.
