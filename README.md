# groundling

Grounded Q&A over a folder of PDFs, with citations you can click to verify.

Designed for use from Claude Code: drop `AGENTS.md` into your project,
set `ANTHROPIC_API_KEY`, ask questions. The tool prints a markdown answer
with clickable citation links — PDF citations open a local HTML page with
the cited page rendered and the cited text highlighted; web citations
(opt-in via `--web-search`) open the source URL with the cited sentence
highlighted natively by the browser.

## Install

    pipx install groundling
    # or:
    uv tool install groundling

## Quick start

    export ANTHROPIC_API_KEY=sk-ant-...
    cd my-research/                          # contains docs/ with PDFs
    curl -O https://.../groundling/AGENTS.md  # one-time template download
    claude

In the agent session: `> what was BYD's Q1 2025 revenue?`

The agent reads `AGENTS.md`, runs `groundling ask --corpus docs/ "..."`,
and shows you the markdown answer with citation links. Click a `[N]` to
open the cited page in your browser.

## CLI

    groundling ask "question" --corpus DIR [--web-search] [--model MODEL]

| Flag | Default | Description |
|---|---|---|
| `--corpus` | (required) | Directory of PDFs |
| `--model` | `claude-sonnet-4-6` | Anthropic model ID |
| `--state-dir` | `<corpus>/qa-runs` | Where run dirs are written |
| `--cache-dir` | `<corpus>/.groundling-cache` | Per-PDF word-extraction cache |
| `--web-search` | off | Enable Anthropic's server-side web_search tool |

Exit codes: 0 success, 2 no PDFs, 3 unextractable PDF (scan), 5 no citations.

## How it works

1. PyMuPDF extracts word-level bboxes from each PDF.
2. Words are concatenated into a flat linearized text per PDF.
3. The Anthropic Messages API is called with citations enabled; the
   linearized text is sent as a document block, the question as user text.
4. The response carries `char_location` citations (and
   `web_search_result_location` citations when `--web-search` is on).
5. Citations resolve back to PDF bboxes via the offset map.
6. A run dir is written under `qa-runs/<timestamp>_<question-slug>/`
   containing one HTML viewer per citation:
   - PDF cites: rendered PDF page + yellow bbox overlay + sidebar.
   - Web cites: meta-redirect stub bouncing to a Chrome Text Fragments
     URL that highlights the cited sentence on the source page.
7. The markdown answer is printed to stdout; each `[N]` link points at a
   local `file://...cites/N.html`.

## Limits

- **No OCR.** PDFs without extractable text (scans) exit 3. OCR them
  externally first.
- **No table-structure inference.** PyMuPDF's reading order is used as-is.
  Complex multi-column layouts may produce garbled linearization; cited
  bboxes are still correct (per-word), but the answer quality drops.
- **No persistent project model.** Each `groundling ask` invocation is a
  fresh, isolated run. Past runs accumulate under `qa-runs/`; delete the
  directory whenever.

## License

TBD.
