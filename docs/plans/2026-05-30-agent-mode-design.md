# groundling agent-driven mode: design

**Date:** 2026-05-30
**Goal:** Add a second answering mode to groundling that moves LLM
inference from the Anthropic API (paid per token) to the Claude Code
agent's session (paid via the user's subscription). The mode is
opt-in, lives behind two new CLI commands (`groundling prep` +
`groundling render`), reuses the v1 cite-HTML machinery unchanged,
and leaves the existing `groundling ask` command untouched.

## Context

v1 of groundling calls Anthropic's Messages API with citations
enabled. The API path is cheap per query (a few cents on Sonnet) but
scales linearly with corpus size and with API spend across many
users. For users who already pay a Claude subscription (Pro / Max /
Team), the same inference work is bundled into a flat fee — but only
accessible via the Claude Code agent's own turns. There's no API
hook that says "use my subscription quota"; the only way to spend
subscription is to take an agent turn.

So this design splits the work: groundling does what tools should
(extract PDFs, chunk them, validate citations, render HTML); the
agent does what an LLM should (read the linearized text, answer the
question, emit cite markers). Two new commands wrap the tool work; a
new AGENTS.md section instructs the agent on the marker contract and
dispatch decision. The agent's turns spend subscription quota; the
tool runs locally for free.

A second motivation: the agent mode generalizes more naturally to
larger corpora. The agent can dispatch one Task subagent per PDF,
each with a fresh context — so 10-PDF corpora work without depending
on Opus's 1M context window. The v1 API path is bounded by Sonnet's
200k window; the agent path is bounded by per-subagent context and
subscription quota.

## Key decisions (validated during brainstorm 2026-05-30)

1. **Two separate top-level commands**: `groundling prep` +
   `groundling render`. The existing `groundling ask` is untouched.
   The two modes pick by which command the agent calls; AGENTS.md
   branches on whether `ANTHROPIC_API_KEY` is set.
2. **Marker contract: chunk ID + verbatim quote.** The agent emits
   `[chunk=<pdf-stem>:<chunk_id> quote="..."]` for PDF cites and
   `[url="..." quote="..."]` for web cites. Render validates each:
   chunk exists AND quote is a substring of the chunk's text.
   Invalid markers are dropped silently with a stderr counter.
3. **Chunk granularity matches groundswell.** PyMuPDF blocks (`b<n>`)
   for prose, table cells (`t<i>r<r>c<c>`) for tables — same ID
   grammar groundswell already uses, so any agent already primed on
   groundswell's convention works here too. Tables detected via
   PyMuPDF's `page.find_tables()`; rendered as markdown grids with
   each cell prefixed by its ID.
4. **Dispatch decision lives in AGENTS.md, driven by a hint file.**
   `groundling prep` writes `dispatch_hint.json` with a corpus-size
   summary and a `recommend` field (`"in_session"` or
   `"subagent_fanout"`). AGENTS.md tells the agent: if
   `recommend == "in_session"`, Read each `.linearized.txt` directly;
   if `"subagent_fanout"`, dispatch one Task per PDF with the
   subagent prompt template.
5. **Synthesis preserves markers verbatim.** When the agent collects
   subagent outputs and writes a synthesis turn, AGENTS.md requires
   it to keep every `[chunk=...]` and `[url=...]` marker exactly as
   it appeared in the subagent output. The render step's validation
   is the safety net; the prompt-level discipline is the
   first-line defense.
6. **Refinekit deferred.** The validation logic (chunk lookup +
   quote substring) is structurally similar to groundswell's
   `filter_by_span_membership` but operates on free-form quotes
   rather than typed atoms. Porting wouldn't save lines; would add a
   heavy dep. Hand-rolled in `markers.py` for now; extract to a
   shared module only if a third caller appears.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ Claude Code session                                                  │
│  user: "what was BYD's Q1 revenue?"                                  │
│  agent reads AGENTS.md (no ANTHROPIC_API_KEY → Mode B); runs:        │
│            groundling prep --corpus docs/                            │
│                                                                      │
│  prep dir written:                                                   │
│    qa-prep/<utc-timestamp>/                                          │
│      BYD-Q1.linearized.txt   ← per-PDF chunked text + IDs            │
│      BYD-Q1.chunks.json      ← chunk_id → (page, bbox, word range)   │
│      BYD-H1.linearized.txt                                           │
│      BYD-H1.chunks.json                                              │
│      dispatch_hint.json      ← {n_pdfs, n_tokens, recommend}         │
│                                                                      │
│  agent reads dispatch_hint; branches:                                │
│   ─ small corpus: Read each linearized.txt into main session         │
│   ─ large corpus: dispatch one Task per PDF, each subagent answers   │
│      ↓                                                               │
│   either path produces markdown with markers:                        │
│     "BYD's Q1 revenue was RMB 170.36B[chunk=BYD-Q1:p2:t0r1c1         │
│      quote=\"170,360,448,000.00\"]"                                  │
│      ↓                                                               │
│  agent runs: groundling render <prep-dir> --answer answer.md         │
│      ↓                                                               │
│  groundling validates markers, drops invalid silently, generates     │
│  cites/N.html files via v1's render_cite_pdf + render_cite_web,      │
│  rewrites markdown so each marker becomes a [N] reference with       │
│  [N]: file://abs/.../cites/N.html at the bottom.                     │
│      ↓                                                               │
│  agent prints the rewritten markdown to the user.                    │
└──────────────────────────────────────────────────────────────────────┘
```

**Five new modules** under `src/groundling/`:

```
chunker.py     # PyMuPDF block walking + find_tables; chunk ID assignment;
               # markdown-grid rendering for tables; chunks.json builder
agent.py       # dispatch_hint thresholds + computation; subagent prompt
               # template as a module constant
prep.py        # groundling prep orchestration: writes prep dir
markers.py     # parser for [chunk=...] and [url=...] markers; chunk
               # lookup + quote substring validation; counter tracking
render_cmd.py  # groundling render orchestration: parse markers →
               # validate → resolve chunks to spans via existing
               # offset_map → call v1's render_cite_pdf/web → rewrite
               # markdown to use [N] references
```

Plus two new Typer subcommands wired into `cli.py`.

**v1 modules used unchanged** (zero changes to existing code):
- `extract.py` (`extract_words`, per-PDF mtime cache)
- `linearize.py` (`linearize_words`, `resolve_range`) — though prep
  uses chunker.py to build chunks on top of the word offset_map
- `render.py` (`render_pdf_page`, `render_cite_pdf`,
  `render_cite_web`, `build_text_fragment_url`)
- `templates/cite_pdf.html.j2`, `templates/cite_web.html.j2`

## The `prep` command

```
groundling prep --corpus DIR [--out DIR] [--cache-dir DIR]
                              [--no-tables]
```

**Behaviour:**

1. Walk `<corpus>/*.pdf` sorted alphabetically. Reuse
   `extract_words(pdf, cache_dir=cache)` from v1 — gets the
   word-level dicts with bbox + page, cached.
2. For each page, call `page.find_tables()`. Cell bboxes become the
   units for table content; non-table content uses
   `page.get_text("blocks")` for prose blocks.
3. Walk the page top-to-bottom by y-coordinate, partitioning words:
   - Words inside a detected table cell → grouped into
     `t<i>r<r>c<c>` chunks (one per cell).
   - Remaining words → grouped per PyMuPDF block, ID `b<n>`.
4. Build `<pdf-stem>.linearized.txt` with each chunk's text prefixed
   by its full chunk ID (e.g. `[BYD-Q1:p2:b01]`); tables rendered as
   markdown grids mirroring groundswell's `_render_markdown_table`:

```
[BYD-Q1:p1:b00] BYD Company Limited Q1 2025 Quarterly Report ...
[BYD-Q1:p2:b01] MAJOR FINANCIAL DATA ...

| [BYD-Q1:p2:t0r0c0] (RMB) | [BYD-Q1:p2:t0r0c1] Reporting Period | ...
| --- | --- | ... |
| [BYD-Q1:p2:t0r1c0] Operating revenue | [BYD-Q1:p2:t0r1c1] 170,360,448,000.00 | ...
```

5. Build `<pdf-stem>.chunks.json` — flat list of chunk records:

```json
[
  {
    "chunk_id": "BYD-Q1:p2:t0r1c1",
    "page": 2,
    "bbox": [120.3, 480.1, 215.7, 495.4],
    "word_idx_start": 1834,
    "word_idx_end": 1841,
    "text": "170,360,448,000.00"
  }
]
```

Render uses this to look up chunks by ID and resolve quote substrings
to the word-index range inside the chunk via the existing word
offset_map.

6. Build `dispatch_hint.json`:

```json
{
  "n_pdfs": 2,
  "n_chunks": 412,
  "linearized_tokens": 47000,
  "recommend": "in_session",
  "thresholds": {"max_pdfs_in_session": 4, "max_tokens_in_session": 120000}
}
```

Thresholds live in `agent.py` as module constants so AGENTS.md can
quote them and tuning is one-file. `recommend == "in_session"` iff
both thresholds are under; else `"subagent_fanout"`.

7. Print the prep dir path to stdout so AGENTS.md can capture it.

**Output dir** defaults to `<corpus>/.groundling-prep/<utc-timestamp>/`
(mirrors `.groundling-cache/` and `qa-runs/`). New prep dir per
invocation; cheap because word extraction is mtime-cached.

**`--no-tables`** skips `page.find_tables()` — for debugging or
prose-only corpora where table detection adds latency.

## AGENTS.md (mode branching + marker contract)

AGENTS.md gets a top-level branch on whether `ANTHROPIC_API_KEY` is
set, then describes both modes. Mode A is the existing v1 instructions
for `groundling ask`; Mode B is new and describes prep + agent
inference + render. Mode B's content:

```markdown
## Mode B: Agent-driven (no ANTHROPIC_API_KEY needed)

When ANTHROPIC_API_KEY is NOT set, or the user prefers using your
subscription, answer corpus questions via prep + render instead of
`groundling ask`. The marker contract below is mandatory: deviating
breaks citation validation and produces no clickable links.

### Step 1: prep

    groundling prep --corpus docs/

Capture stdout (the prep dir path). Read
<prep_dir>/dispatch_hint.json.

### Step 2: dispatch decision

If `recommend == "in_session"`:
  - Read each <pdf-stem>.linearized.txt in this session via the Read
    tool.
  - Answer the question in your next turn, using the marker contract.

If `recommend == "subagent_fanout"`:
  - For each PDF, dispatch a Task subagent with:
      * path to that PDF's .linearized.txt
      * the user's question
      * the marker contract (paste verbatim from below)
  - Collect each subagent's marked-up per-doc answer.
  - In your next turn, synthesise a final answer. Preserve every
    [chunk=…] and [url=…] marker verbatim from the subagent outputs.
    Do not invent new markers; do not paraphrase quoted text inside
    markers.

### Marker contract

When you cite a PDF chunk:

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim substring of the chunk"]

The chunk_id is the bracketed label in the linearized text (e.g.
`p2:b01`, `p2:t0r1c1`). The quote MUST be a verbatim substring of
that chunk's text, not paraphrased. Render-time validation drops
cites where the chunk is unknown or the quote is not found.

When you cite a web source (via your WebSearch / WebFetch tools):

    [url="https://full-url" quote="exact verbatim sentence from page"]

Quote MUST be a verbatim substring of the fetched page text.

### Step 3: render

    groundling render <prep_dir> --answer <path-to-answer.md>

Render rewrites your markdown so each marker becomes a `[N]` link
pointing at a local cites/N.html. Print the rewritten markdown to the
user verbatim — that is the final answer.
```

The subagent prompt template lives in `agent.py` as a module constant
so AGENTS.md can refer to "the marker contract below" and the
contract has one source of truth.

## The `render` command

```
groundling render <prep_dir> --answer FILE
                              [--state-dir DIR]   # default: <corpus>/qa-runs
                              [--web-base BASE]   # default: file://
```

`<prep_dir>` positional, mandatory. `--answer -` reads from stdin so
the agent can pipe directly without a temp file.

**Validation pass.** Parse each marker, drop invalid ones with a
stderr counter so the agent (and user) sees what was lost.

For `[chunk=<pdf-stem>:<chunk_id> quote="..."]`:

1. Load `<pdf-stem>.chunks.json` once per stem (cached for the run).
   Look up `chunk_id`.
2. Unknown chunk → drop, increment `invalid_chunk` counter.
3. Quote string not a substring of the chunk's text (after light
   normalisation: collapse whitespace runs, strip wrapping quotes) →
   drop, increment `invalid_quote` counter.
4. Valid → find the quote's word-index range inside the chunk via a
   substring search on the chunk's text, slice the chunk's
   `[word_idx_start, word_idx_end)` range to that subrange, resolve
   to `[{page, bbox}, ...]` via the v1 word-level offset_map. Emit a
   manifest citation entry with `source_type="pdf"` and those spans.

For `[url="..." quote="..."]`:

1. URL must be HTTP(S) and parseable. Otherwise drop, increment
   `invalid_url`.
2. Emit a manifest entry with `source_type="web"`, URL, quote as
   `cited_text`. No content fetch — Text Fragments URL handles
   verification at click time.

**Rendering.** Reuse v1's cite-HTML machinery unchanged:

- PDF cite spans → `render_cite_pdf(...)` from v1. Same image
  rasterisation, same bbox overlay, same sidebar shape.
- Web cite → `render_cite_web(...)` from v1.
- PNG dedup across cites lands on the same `(pdf, page)` keys as
  v1's orchestration.

**Output:**

1. Rewrite the input markdown — each surviving marker becomes a
   `[N]` reference; `[N]: file://<abs>/cites/N.html` references at
   the bottom. Markers that failed validation are dropped from the
   markdown, leaving the surrounding prose untouched.
2. Write `manifest.json` in the same shape v1 produces (sourced from
   markers rather than Anthropic citations). Static HTML files land
   in `<run_dir>/cites/`.
3. Print the rewritten markdown to stdout. Stderr carries
   `validated=N invalid_chunk=N invalid_quote=N invalid_url=N`.

**Exit codes:**

- 0 success
- 5 zero markers survived validation (ungrounded answer; matches v1)
- 6 prep dir doesn't exist or marker syntax version mismatch
  (forward-compat hook)

## Coexistence with v1

Two modes share data structures but not control flow. Shared
infrastructure used unchanged by both:

- `extract_words` + per-PDF mtime cache
- Word-level offset_map (consumed by both `groundling ask` and by
  the new `render_cmd.py` for chunk-quote → bbox resolution)
- `render_cite_pdf`, `render_cite_web`, `build_text_fragment_url`,
  the Jinja templates
- Manifest schema (cite viewers don't know which mode wrote it)
- Run-dir layout (`qa-runs/<timestamp>_<slug>/` with `cites/`,
  `manifest.json`)

**Net new code:** ~620 LoC across 5 new modules + ~40 LoC of CLI
wiring. Tests scale similarly — ~25 new tests.

**AGENTS.md** becomes a two-section doc with a clear branch at the
top. Mode A (existing) is unchanged. Mode B is new. A user can omit
either section if their flow is single-mode.

## Out of scope (deferred to v1.1+)

- Real Claude Code subagent integration testing. Can't test "actually
  spawn Task subagents from a live session" from the test suite;
  manual verification suffices.
- Synthesis-step quality measurement. Whether the marker-preservation
  discipline holds across question shapes — measure with real usage.
- Web archive snapshots of cited URLs. Same v1.5 territory as v1.
- Refinekit as a hard dep. Validation stays hand-rolled.
- Multi-page chunk support. Chunks are page-bounded by construction;
  REL-221's multi-page citation issue still applies but each cite is
  now naturally single-chunk so the rendering case is easier to fix.
- A `--mode` flag on existing `ask`. We picked two separate commands.
- OCR fallback in prep. Same as v1: PDFs with no extractable text
  exit 3.
- LLM-driven verification of cited_text on the source page. Local
  substring check is cheaper and catches the same failures.
- A `groundling preview` command for deterministic prep+render
  testing without a real agent.

## Risks

- **Chunk IDs are stable per prep invocation, not across.** Re-running
  prep produces a new timestamped prep dir; `b<n>` numbering may
  shift if PyMuPDF's block detection is non-deterministic across
  versions. Document in AGENTS.md: never combine markers from
  different prep dirs.
- **Synthesis-step discipline is prompt-fragile.** If the agent
  paraphrases or drops markers during synthesis, citations are lost.
  Mitigation: render's drop-silently-and-count behaviour surfaces
  the loss to the user without breaking the answer.
- **PyMuPDF's `find_tables()` is heuristic.** Misses borderless
  tables, false-positives on aligned text. For text-native financial
  filings it works well; for newspaper-style multi-column layouts
  expect failures. Document in README.
- **Quote-substring validation is brittle on number formatting.** The
  agent might write `"170.36 billion"` when the source says
  `"170,360,448,000.00"`. We catch this (substring check fails,
  cite dropped, counter increments) but the cite is lost rather than
  resolved. Future enhancement: light numeric normalisation in the
  quote check.

## Done criteria

- `groundling prep --corpus DIR` writes a prep dir with one
  `<stem>.linearized.txt` per PDF (tables as markdown grids with
  `[t<i>r<r>c<c>]` IDs), matching `<stem>.chunks.json`, and a
  `dispatch_hint.json`.
- `groundling render <prep-dir> --answer FILE` validates markers,
  generates `cites/*.html`, rewrites markdown.
- A hand-crafted answer file with both `[chunk=...]` and `[url=...]`
  markers round-trips through prep + render against the BYD corpus,
  producing the same `cites/N.html` shape v1 produces.
- AGENTS.md has two clearly-labeled sections (Mode A and Mode B);
  agent picks by checking whether `ANTHROPIC_API_KEY` is set.
- `pytest tests/ -q` is green; v1's 67 tests still pass; ~25 new
  tests for chunker, markers, render command, agent-mode E2E.
- Manual verification: open Claude Code in a project containing the
  new AGENTS.md and a `docs/` folder with text-native PDFs, ask a
  question, get a markdown answer with clickable `file://` citation
  links.
