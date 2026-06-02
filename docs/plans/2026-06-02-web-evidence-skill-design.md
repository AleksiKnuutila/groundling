# Web Evidence Skill — Design

**Goal:** Extend the groundling Claude Skill so it grounds answers in
web sources, not just user-uploaded PDFs — running entirely in the
Claude code-execution sandbox, producing the same self-contained
`answer.html` with verifiable cite spans.

**Architecture:** Claude uses its native `web_search` / `web_fetch`
tools (Anthropic does the extraction server-side). For each cited
source, the model deposits an evidence JSON file in the sandbox.
`render.py` validates web cite markers against deposited evidence —
same substring check as today's PDF chunk validation — and produces a
unified `answer.html` with two cite kinds.

**Tech stack:** Python 3.11, existing Jinja2 templates, no new
dependencies.

## Motivation

Groundling today produces verifiable answers grounded in uploaded
PDFs. Many real questions need current web sources: "what were Q1
2026 earnings", "what did the company announce yesterday", "what's
the latest on X." Claude's native `web_search` / `web_fetch` cite
URLs in chat, but those cites rot, get edited, paywall, or
disappear. There is no permanent verifiable artifact.

This design adds web-grounding to the existing skill while keeping
the PDF path untouched. The output is one `answer.html` with mixed
cite kinds:

- PDF cites keep their existing visual treatment: page region image
  with bbox highlight on hover, full page in click dialog.
- Web cites get a textual treatment: the quote highlighted in ±150
  chars of extracted-text context, plus a link to the live URL.

## Non-goals

- **Live page rendering / screenshots.** Headless chrome is not
  feasible in the sandbox (system-lib gap on manylinux2014, no apt).
  Extracted text is the evidence.
- **Independent fetching by the skill.** The skill never touches the
  live web. Only the model does, via its native tools. The skill is
  a renderer of evidence the model has gathered, not a fetcher.
- **Wayback / archive integration.** Direct URL link is sufficient
  for v1. Revisit if quote-drift becomes a frequent failure mode.
- **Client-side "verify still live" button.** Adds JS complexity;
  CORS makes it often impossible in practice. YAGNI for v1.
- **URL canonicalization.** v1 requires exact string match between
  marker and evidence file. Model is responsible for consistency.
  Defer normalization to v2 if needed empirically.

## Architecture

```
  PDFs (optional)              Web (optional)
   │                             │
   │ prep.py                     │ Claude writes evidence
   │                             │ files between web tool
   ↓                             ↓ calls and answer compose
  /tmp/groundling-prep/         /tmp/groundling-web/
     foo.linearized.txt            01.json, 02.json, ...
     foo.chunks.json
                ↘             ↙
                 render.py
                    │ validates quotes against either corpus
                    │ builds unified cite_records
                    ↓
                 answer.html  (one file, mixed cite kinds)
```

Either-or-both: `render.py` accepts `--prep-dir`, `--web-dir`, or
both. At least one must yield non-empty content. Web-only QA is a
first-class mode.

## Evidence-deposit protocol

For each web source Claude intends to cite, it writes one JSON file
to `/tmp/groundling-web/<n>.json` with sequential numeric filenames:

```json
{
  "url": "https://aramco.com/.../q1-2026.html",
  "title": "Aramco Reports First Quarter 2026 Results",
  "fetched_at": "2026-06-02T14:30:00Z",
  "extracted_text": "...full readable text the model got back..."
}
```

- `url` — canonical key. Marker URLs must match this exactly.
- `extracted_text` — verbatim copy of what `web_search` / `web_fetch`
  returned. No paraphrasing, no truncation.
- Filename is purely storage; the model picks any unused integer.

This is a **skill-layer convention**, not an Anthropic primitive.
Same enforcement model as today's marker contract: model is expected
to follow; validation catches violations after the fact, surfaces
them in stderr counters, and the model is asked to retry.

## Marker contract

Structurally identical to PDF markers, with `web://` scheme:

```
[claim text](web://<full-url> "exact verbatim quote")    # wrapping
[url="<full-url>" quote="exact verbatim quote"]          # point
```

Validation:

- URL must match a `url` field in some evidence file exactly
- Quote must be a verbatim substring of that file's `extracted_text`
- Markers failing either check are dropped; counters report
  `missing_evidence` and `invalid_quote_web` to stderr
- Exit code 5 (all markers invalid) still applies

## Rendering

**PDF cite (existing, unchanged):**

- Hover: floating preview with PDF page region, bbox highlight
- Click dialog: full page image with bbox, claim + quote, filename

**Web cite (new):**

- Hover: typographic popover (~360px wide) showing the quote
  highlighted (`<mark>`) in ±150 chars of surrounding extracted text
- Click dialog: larger excerpt with the same `<mark>` highlight,
  source URL as a direct link (`target="_blank" rel="noopener"`),
  fetched_at timestamp
- Small globe icon (CSS `::before`) distinguishes web cites from PDF
  cites at a glance

The visual asymmetry is **intentional** and tells the truth about
what the system has access to. PDF cites are visually verifiable
against a permanent uploaded artifact. Web cites are textually
verifiable against extracted text captured at a point in time.
Different evidence types, different verification UIs.

## File-by-file changes

Approximately 190 LOC of new code across 5 files. PDF code path does
not move.

### `scripts/render.py` (~60 LOC)

- New `--web-dir` flag; `--prep-dir` becomes optional (at least one
  of prep/web must yield content)
- Evidence loader: glob `<web-dir>/*.json`, parse, build
  `url → evidence` dict; malformed JSON files skipped with warning
- Marker parser gains `web://` branch
- Web-marker validation:
  ```python
  ev = url_to_ev.get(marker.url)
  if ev is None:
      counters["missing_evidence"] += 1; continue
  if marker.quote not in ev["extracted_text"]:
      counters["invalid_quote_web"] += 1; continue
  ```
- Excerpt computation: locate quote position, slice ±150 chars,
  record `excerpt` + `quote_offset_in_excerpt`
- Builds cite_record with `kind: "web"` and fields: `url`, `title`,
  `fetched_at`, `excerpt`, `quote_offset_in_excerpt`
- New counter `missing_evidence` in stderr output

### `src/groundling/answer_html_inline.py` (~25 LOC)

- Recognize `kind == "web"` cite_records; pass new fields to template
- Compute `excerpt_html`: HTML-escape `excerpt`, inject
  `<mark>...</mark>` around the quote span using
  `quote_offset_in_excerpt` + `len(quote)`. Server-side; template
  receives via `| safe`
- Web cites skip the image registry (no slot allocation)

### `src/groundling/templates/answer_inline.html.j2` (~30 LOC)

- Web cite dialog body: render `excerpt_html`, source URL as direct
  link, fetched_at as secondary text
- Web cite hover preview: new `<div class="preview-text">` block
  inside the anchor (sibling of existing PDF `.preview` div)
- Cite anchor data attrs: `data-kind="web"` (already flows through)

### CSS (~25 LOC, inside the template's `<style>` block)

- `a.cite[data-kind="web"] .preview-text` — typographic popover,
  ~360px wide, max-height with scroll, padded
- `<mark>` styling that matches the existing yellow cite highlight
- Small globe icon `::before` on web cite anchors

### `skill/SKILL.md` (~50 LOC)

- New Step 2b "Web evidence (if using web sources)" drilling deposit
  discipline (verbatim copy, sequential filenames, URL consistency)
- Marker contract: promote `web://` to peer of `chunk://`
- Step 5: show both `--prep-dir` and `--web-dir` flags

## Testing

### Unit tests (`tests/test_render_web.py`, ~80 LOC, new file)

- Evidence loader: well-formed dir, missing dir, malformed JSON
  (skip+warn), missing required keys
- Web marker validation:
  - Valid: URL exists, quote ⊂ extracted_text → cite_record produced
  - Missing evidence: URL not in any file → counter +1, cite dropped
  - Wrong quote: URL exists, quote not in text → counter +1, cite
    dropped
- Excerpt computation:
  - Quote at start (window clamps to 0)
  - Quote at end (window clamps to len)
  - Short text (whole text returned)
- Hybrid: answer with both PDF and web markers → both kinds present
- Web-only: `--prep-dir` omitted → valid output
- Both flags omitted → exit code 2 with clear error

### Inline-HTML tests (`tests/test_answer_html_inline.py`, ~40 LOC)

- Web cite renders with `data-kind="web"` anchor
- Excerpt appears in dialog with `<mark>` around quote span
- Web cite does NOT trigger an `IMG_REGISTRY` slot (regression for
  image-registry bloat)
- Hover preview HTML present for web cites
- Hash deep link `#cite-N` opens web cite dialog same as PDF

### Empirical validation

Code correctness only takes us so far. We need a real end-to-end run
in the Claude sandbox with a current-events question — same approach
as `skill/api_smoke.py` for PDFs. A new `skill/api_smoke_web.py`
parallel runs a web QA scenario end-to-end against the real API.

Things to confirm on a live run:

- Model reliably deposits evidence *before* composing the answer
- Model copies `extracted_text` verbatim from web tool result
- Model uses URL string identically in evidence file and marker
- Model `web_fetch`es for full content when search snippet isn't
  enough to support a quote
- Validation counters healthy (zero `invalid_quote_web`,
  zero `missing_evidence`)

Failure modes here are almost always cured by tightening SKILL.md
wording, not code changes — cheap iteration loop.

Gate v0.2.0 release on `api_smoke_web.py` passing.

## Tradeoffs and open questions

- **Model bookkeeping overhead.** The model has to write a JSON file
  per web source before composing. Adds friction; price of
  verifiability.
- **No layout fidelity for web.** Users see text, not screenshots.
  Acceptable given sandbox constraints. If pixel verification ever
  becomes critical, route through an external screenshot API.
- **Quote drift over time.** Evidence is frozen at fetch time. If
  the article gets edited, our cite still verifies against frozen
  text, but the live URL may not match anymore. Mitigated by
  surfacing `fetched_at` in the dialog so the reader knows the cite
  is point-in-time.
- **URL canonicalization.** v1 requires exact string match. Same
  article via different URLs (`www.` prefix, `?utm_*` params,
  trailing slash) won't dedupe. Defer normalization to v2.
- **Discipline check.** Whether Claude follows the protocol reliably
  is an empirical question. Validation counters give us a fast
  signal; SKILL.md wording is the fix when violations show up.

## Release sequencing

1. Land render.py + answer_html_inline.py + template + CSS changes
   behind tests on a feature branch
2. Update `SKILL.md` with Step 2b + web marker contract
3. Rebuild skill zip (`./skill/build_zip.sh v0.2.0`)
4. Run `skill/api_smoke_web.py` against the real Anthropic API
5. Iterate on SKILL.md wording if counters surface protocol violations
6. Tag v0.2.0, publish release with versioned + stable zips
