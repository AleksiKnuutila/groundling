# LLM-as-Judge + answer.html Redesign — Design

**Goal:** Refresh `answer.html`'s visual language to match the
`scratch/C-inline-confidence.html` mockup, and add an optional
LLM-as-judge pass that decorates each cited claim with a verdict
(supported / partial / unsupported) and flags significant uncited
claims (needs-citation).

**Architecture:** Skill-side deposit protocol, same pattern as the
v0.2.0 web-evidence path. The agent runs zero, one, or both judge
passes via fresh subagents (Task tool in Claude Code; fresh-context
prompt elsewhere) and writes JSON files under `/tmp/groundling-judge/`.
`render.py` reads them and decorates the rendered HTML accordingly.
No CLI judge subcommand; no Anthropic API dep on main.

**Tech stack:** Python 3.11, existing Jinja2 templates, no new deps.
Fonts (IBM Plex Sans, Newsreader, IBM Plex Mono) loaded from Google
Fonts CDN with `system-ui`/`serif`/`monospace` fallbacks.

## Motivation

Today's `answer.html` shows cited spans with a single neutral
underline + hover preview. Two limitations:

1. **No signal on claim quality.** Every cite looks identical
   whether the source firmly entails the claim or the agent
   stretched a tangential quote.
2. **No signal on uncited claims.** Significant factual claims
   missing a marker pass silently — readers have to spot them.

The redesign integrates the two ideas the mockup proposes — inline
verdict styling on cited spans + dashed-underline treatment on
uncited spans — into a single coherent visual. The judge is
optional, deposit-based, and decoupled from the cite-validation
that `render.py` already does.

## Non-goals

- **Confidence percentages.** State-only (`supported` / `partial` /
  `unsupported`). LLM-produced 0–1 scores are poorly calibrated and
  the state already conveys the signal.
- **Pixel-perfect mockup match.** Spirit-match. The trust meter
  (stacked-segment bar) is dropped per user direction; tally counts
  remain.
- **CLI `groundling judge` subcommand.** Pure SKILL.md / AGENTS.md
  instruction set. Keeps main lean and skill-first; matches the
  web-evidence deposit pattern.
- **API-side judge.** Reintroduces `anthropic` as a dep; the
  `api-mode` branch is where that fits if it's ever needed.
- **Cross-cite reasoning.** Each Pass-2 verdict sees only one
  cite's claim + quote + chunk context, plus the surrounding answer
  sentence. No comparing cites against each other in v0.3.0.
- **Persistent verdicts.** Each render is a fresh judgment; no
  caching of verdicts across runs.

## Architecture

```
agent writes answer.md
   ↓
(optional) agent dispatches subagent(s) to judge
   ↓
   writes /tmp/groundling-judge/{verdicts.json, uncited.json}
   (either, neither, or both)
   ↓
render.py [--judge-dir DIR] → answer.md + answer.html
   (decorated if judge files present)
```

Same shape as `/tmp/groundling-web/` for web evidence. The model
is responsible for producing JSON to a documented contract;
`render.py` is purely a validating renderer.

### Two deposit files, independent

**`verdicts.json`** — Pass 2. Map `cite_id → {state, note}`.

```json
{
  "1": {"state": "supported",  "note": "Source line states users click a citation to view the exact paragraph; near-verbatim."},
  "2": {"state": "partial",    "note": "Source describes deterministic citations attaching anchor links, but doesn't specify 'every claim'."},
  "5": {"state": "unsupported","note": "Source phrase 'absolute accuracy over guesses' is aspirational marketing; no concrete basis for the cited capability."}
}
```

Keys are stringified cite_ids matching `manifest.json`. Missing
entries → render treats them as no-verdict (anchor stays in default
state, no underline color, no card band). `note` is capped at
~200 chars in the prompt; render truncates with ellipsis if
oversized.

**`uncited.json`** — Pass 1. List of `{span_text, before_context,
after_context, note}`.

```json
[
  {
    "span_text": "lifting first-contact helpdesk resolution above 50%",
    "before_context": "Reliacode reports",
    "after_context": "and cutting return site visits",
    "note": "Specific percentage; no source attached. Likely from the canvas's customer-gains section."
  }
]
```

- `span_text` — verbatim substring of `answer.md`.
- `before_context` / `after_context` — 3–8 word snippets used by
  render to disambiguate when `span_text` appears multiple times.
- `note` — judge's reasoning; shown in hover card + modal.

### Render.py changes

New `--judge-dir DIR` flag:
- If `verdicts.json` exists, validates that each cite_id present is
  known to the rewritten markdown; stamps `data-state` and
  `data-judge-note` on the anchor element.
- If `uncited.json` exists, locates each span via substring +
  context disambiguation, wraps the match with
  `<a class="cite" data-state="needs-citation" data-uncited-note="...">span</a>`.
- New stderr counters: `verdicts_missing`, `verdicts_unmapped`,
  `uncited_unmatched`, `uncited_overlap`.

If `--judge-dir` is absent, render produces today's output (plus
the visual refresh from Section "Visual design" below).

## Visual design

Spirit-matches `scratch/C-inline-confidence.html`. Single template
for both judge-on and judge-off paths.

### Typography & palette

- Body: IBM Plex Sans 17px / line-height 1.62
- Display (`h1`, `h2`, claim text in modal): Newsreader serif, weight 500
- Mono (cite labels, source kind chip, counts): IBM Plex Mono
- Paper background `#fbfbf9`, ink `#1a1c1e`, soft-ink `#565b61`, hairline `#e6e6e2`
- State colors: supported `#2f8a52`, partial `#a9760a`, unsupported `#c43d2c`, needs-citation `#3160a8`
- Fonts loaded from Google Fonts CDN. Fallback stack:
  `system-ui` / `serif` / `monospace`.

### Header strip

Sticky, blurred backdrop, hairline border-bottom.

```
┌──────────────────────────────────────────────────────────────────┐
│ Groundling.   ●12 Supported ●3 Partial ●2 Unsupported ●1 Uncited  [▢ Spotlight weak] │
└──────────────────────────────────────────────────────────────────┘
```

- Brand left ("Groundling." in Newsreader serif).
- Tally right: four state-dot-and-count chips in mono. When no judge
  ran: single neutral chip `"17 cites validated"`.
- **Spotlight weak claims** toggle right of tally. Click adds
  `body.weak` class → CSS dims `a.cite[data-state="supported"]`
  borders to neutral gray + softens text color. Partial,
  unsupported, needs-citation stay bold. Same behavior as mockup;
  no persistence across reloads.

### Subtitle

Under the h1 (page title = the question), one grey line:

```
Verified answer · 17 claims checked against Q1-earnings.pdf and 3 web sources
```

Degrades to `"17 cites validated"` when no judge ran.

### Inline cite styling

Every `a.cite` element gets a `data-state` attribute. CSS:
- `[data-state="supported"]` → solid green underline
- `[data-state="partial"]` → solid amber underline + state dot
- `[data-state="unsupported"]` → solid red underline + state dot
- `[data-state="needs-citation"]` → dashed blue underline + state dot
- No `data-state` (judge-off, cited) → neutral underline, no dot

### Hover card

Floating, ~420px wide, fixed-position above/below the hovered cite.

- **Cited:** colored band (state color + glyph + label) + source-kind
  chip ("PDF" / "WEB") + body containing PDF crop centred on cited
  region (~392×132px) or text excerpt with `<mark>` around the
  quote (+ fade-out `mask-image` gradient at the bottom edge) +
  footer with source label and "Click to inspect →" cta.
- **Uncited:** band says "Needs citation"; body shows judge's note
  in serif; no source slot.

### Click modal

Backdrop-blurred, ~760px wide.

- **Cited:** colored band (larger) + claim text in Newsreader serif
  + grey callout "Why the judge says X" containing the judge note +
  full PDF page with bbox highlight or web excerpt + source URL +
  fetched_at.
- **Uncited:** band + claim + judge note callout; no source slot.

ESC and backdrop-click close. Deep-link `#cite-N` opens the modal
on load (existing behavior).

### Self-containment

`answer.html` (today's `build_answer_html` path) keeps using
external font CDN references; gracefully degrades offline.
`answer_html_inline.py` (skill path) inlines verdict/uncited JSON
in `<script>` tags the same way image data is today. Single-file
artifact preserved.

## Pass 1: uncited significant claims

### Skill control flow

1. Agent has `answer.md` with cite markers already validated by render.
2. SKILL.md instructs: "for each significant factual claim with no
   cite, deposit `/tmp/groundling-judge/uncited.json`."
3. Agent dispatches a fresh subagent with the full answer markdown +
   list of source titles + the contract for the JSON shape.
4. Subagent emits JSON; agent writes it to the deposit path.
5. `render.py --judge-dir /tmp/groundling-judge/` picks it up.

### Subagent prompt (paraphrased)

> Read this answer. Identify factual claims that
> (a) name a specific number, date, attribution, or causal mechanism,
> and (b) have no `[chunk=...]`, `[url=...]`, `chunk://`, or `web://`
> marker within the same sentence. Skip framing prose ("the report
> covers"), opinion ("this is concerning"), and claims that
> paraphrase a nearby cited claim. For each, emit
> `{span_text, before_context, after_context, note}`.

Final wording is iterated in `api_smoke_judge.py` against real outputs.

### Render-time span-finding

1. For each entry, find all occurrences of `span_text` in `answer.md`
   (after marker rewriting, before HTML generation).
2. One match → wrap.
3. Multiple matches → pick the one whose preceding/following chars
   match `before_context` / `after_context`.
4. Still ambiguous or no match → increment `uncited_unmatched`,
   log to stderr, skip.

### Edge case — overlap with existing cite

If `span_text` intersects a wrapping `[claim](chunk://...)` link's
claim text, drop with `uncited_overlap` counter. Prevents nested
markdown links.

### Cost

One subagent call total (whole answer, not per-claim). Cheap.

## Pass 2: cited verdicts

### Skill control flow

1. Agent has `answer.md` + `manifest.json` listing every cite_id +
   claim_text + quote + source pointer.
2. SKILL.md instructs: "for each cite, dispatch a fresh subagent
   with claim + quote + chunk/source context; collect verdicts into
   `verdicts.json`."
3. Agent fans out N subagent calls (parallel where possible;
   sequential in claude.ai web where Task tool unavailable).
4. Agent assembles results into `/tmp/groundling-judge/verdicts.json`.
5. `render.py` reads it.

### Per-cite subagent input

- `claim_text` — the wrapping link text, OR the answer sentence
  containing a point marker.
- `quote` — the verbatim quote already validated by render.
- `source_excerpt` — full chunk text for PDF cites; ±300 char window
  around the quote in `extracted_text` for web cites.
- `source_label` — pdf-stem + page, or url + title.
- `answer_sentence` — the sentence in the answer containing the
  cite (for argument-context only; the judge is told not to use
  the rest of the answer).

The judge **does not see** other cites or the rest of the answer —
scoped input mitigates self-judge bias.

### Subagent rubric (paraphrased)

> Does the source excerpt support the claim? Answer in one of three
> states:
> - `supported` — the source directly says what the claim says, or
>   is the precise basis for the claimed fact
> - `partial` — the source says something related — adjacent,
>   weaker, broader, or narrower — but doesn't fully back the
>   specific claim
> - `unsupported` — the source is irrelevant, says something
>   different, or actively contradicts the claim
>
> Write a short note (≤ 200 chars) explaining the call.

### Cost

N subagent calls for N cites. The expensive pass. SKILL.md
explicitly says: skip Pass 2 for short answers; this is a quality
bar, not a default. Otherwise the judge becomes a per-question tax.

### Bias mitigation

- Fresh subagent (Task tool dispatch in Claude Code; isolated
  conversation context elsewhere).
- Scoped input — no answer history, no other cites.
- Three-state rubric — no gradient that invites hedging into a
  middle bucket.
- Short note budget — forces a concrete reason rather than vague
  reassurance.
- Acceptable residual: same model family writes the answer and
  judges. A truly independent judge needs a different model or an
  API-side route. Out of scope for v0.3.0.

## Testing

### Unit tests

**`tests/test_judge_uncited.py`** (~80 LOC)
- Span finder: single match → wraps; multiple matches with
  disambiguator → picks right one; multiple matches with no
  disambiguator → drops, counter increments; no match → drops,
  counter increments.
- Overlap detection: `span_text` inside `chunk://` wrap link's
  claim → drops with `uncited_overlap`.
- Malformed entry (missing `span_text`) → skip + warn.
- Output HTML: matched span becomes
  `<a class="cite" data-state="needs-citation" data-uncited-note="...">`
  with no href.

**`tests/test_judge_verdicts.py`** (~60 LOC)
- Full coverage → every anchor gets `data-state` + `data-judge-note`.
- Partial coverage → present cites decorated, missing ones default,
  counter `verdicts_missing` reports.
- Unknown cite_id in verdicts.json → ignored with
  `verdicts_unmapped`.
- Invalid state value → drop entry + warn.

**`tests/test_judge_dir_loader.py`** (~30 LOC)
- `--judge-dir` absent → render works as today; no state attrs.
- Directory present, both files missing → no decoration.
- Malformed JSON → skip with warning, continue rendering.
- `verdicts.json` only / `uncited.json` only / both — each yields
  the right HTML state.

### Inline-HTML tests

Extend `tests/test_answer_html_inline.py` (~50 LOC):
- Each verdict state renders the right CSS class.
- Hover-card content branches: cited has source crop + quote;
  uncited has judge note in place of crop.
- Modal content branches: cited has claim + note callout + source;
  uncited has claim + note, no source slot.
- Spotlight toggle wires up: click adds/removes `body.weak`.
- Header tally counts match verdicts; degrades to `"N cites
  validated"` when no judge files present.
- Subtitle branches on judge state.

### Snapshot / fixture test (~30 LOC)

One golden answer.md with a mixed cite set (2 supported, 1 partial,
1 unsupported, 1 uncited) → render produces an answer.html that
asserts: 4 colored cite anchors, 1 needs-citation anchor, tally
counts correct, deep-link `#cite-3` opens modal.

### Empirical validation

New **`skill/api_smoke_judge.py`** parallel to `api_smoke_web.py`:
end-to-end against the real API with a question where some cited
claims are deliberately weak. Confirms:

- Subagent reliably returns valid JSON in the documented shape.
- States distribute across all three values (not degenerate
  "everything is supported").
- Uncited spans get caught when seeded into the answer.
- Whole flow produces a valid answer.html with the trust strip and
  inline state colors.

Gate v0.3.0 release on `api_smoke_judge.py` passing.

### Existing-test maintenance

The visual refresh changes inline-HTML test expectations (new font
stack, new class names for the trust strip and cite-card structure).
Those updates are part of the implementation, not a new test file.
Today's 136 tests cover render with no `--judge-dir`. That code
path's behavior is unchanged except for visual output.

## Release sequencing

1. **PR 1 — visual refresh (no judge).** Rewrite `answer_html.py`
   and `answer_html_inline.py` to emit the new HTML/CSS: sticky
   header strip with tally + spotlight toggle, new typography, new
   cite/card/modal styling. Tally shows `"N cites validated"`.
   Existing tests updated. Risk-isolated: cite validation
   unchanged.
2. **PR 2 — Pass 2 (cited verdicts).** Add `--judge-dir` flag,
   `verdicts.json` loader, state-decoration. SKILL.md gains "Step
   6: judge (optional)" with Pass-2 subsection. New tests + smoke.
   `uncited.json` quietly ignored if present.
3. **PR 3 — Pass 1 (uncited claims).** `uncited.json` loader +
   span-finding + needs-citation anchor injection. SKILL.md gets a
   Pass-1 subsection. New tests + `api_smoke_judge.py` empirical
   gate.
4. **Tag v0.3.0.** Bundle refreshed SKILL.md + scripts + wheels
   into the skill zip.

Each PR is independently shippable. PR 1 can land even if Pass 2/3
are abandoned — main still benefits from the visual refresh. The
`api-mode` branch is unaffected throughout.

## Open questions

- **Subagent prompt wording.** Especially Pass 2's three-state
  rubric. Iterate in `api_smoke_judge.py` empirical runs.
- **`note` length cap.** Proposed 200 chars; might want 300 after
  seeing real outputs. Render truncates if oversized.
- **Source excerpt size for Pass 2.** Full chunk for PDFs, ±300
  chars for web. Tune up if judge's "I can't tell from this
  excerpt" rate is high.
- **Spotlight toggle persistence.** Mockup resets on reload;
  matching that. Could move to `localStorage` later.
- **CSS font-loading fallback.** Offline → `system-ui` / `serif` /
  `monospace`. Accept the visual degradation; bundling Plex +
  Newsreader together would add ~600KB to every answer.html.

## Tradeoffs

- **Cost of Pass 2.** N subagent calls per answer. For a 20-cite
  answer, 20 model invocations. SKILL.md must say explicitly: skip
  for short answers; this is a quality bar, not a default.
- **Self-judge bias risk.** Mitigated by scoped input. Residual:
  same model family writes and judges. Independent judge needs a
  different model or API path — out of scope for v0.3.0.
- **Calibration honesty.** State-only avoids overclaiming
  precision. If a confidence % is ever wanted back, derive from
  state buckets rather than ask the LLM.
- **Mockup divergence.** No meter, no confidence %, vocabulary
  shifted (supported / partial / unsupported / needs-citation).
  Spirit-match, not pixel-match. Spotlight toggle kept.
- **Font CDN dependency.** Answer.html loses true offline
  self-containment for the refreshed typography. Acceptable; the
  fallback stack still reads well.
