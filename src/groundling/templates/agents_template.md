# Grounded Q&A — groundling

This project answers corpus questions using your Claude subscription:
prep + agent + render. The marker contract below is mandatory —
deviating breaks citation validation and produces no clickable links.

## Step 1: prep

    groundling prep --corpus docs/

Capture stdout (the prep dir path). Read `<prep_dir>/dispatch_hint.json`.

## Step 2: dispatch decision

If `recommend == "in_session"`:
- Read each `<pdf-stem>.linearized.txt` in this session via the Read tool.
- Answer the question in your next turn, using the marker contract.

If `recommend == "subagent_fanout"`:
- For each PDF, dispatch a Task subagent. The subagent prompt template is
  in `src/groundling/agent.py` as `SUBAGENT_PROMPT_TEMPLATE`; paste it
  verbatim, filling `{pdf_path}` and `{question}`.
- Collect each subagent's marked-up per-doc answer.
- In your next turn, synthesise a final answer. **Preserve every
  `[chunk=...]` and `[url=...]` marker verbatim from the subagent
  outputs.** Do not invent new markers; do not paraphrase quoted text
  inside markers.

## Marker contract

Two shapes — **prefer the wrapping form when you can name the claim
the citation supports**.

**Wrapping (preferred for specific claims):**

    [<claim text>](chunk://<pdf-stem>/<chunk_id> "exact verbatim quote")
    [<claim text>](web://https://full-url "exact verbatim quote")

The claim text is the span the citation is grounding — write it as
the precise sentence-fragment that the cited quote supports. The link
text becomes the citation's scope on the page. At render time the
URL is rewritten to the local cite HTML; the link text and the
quote (in the title attribute) are preserved verbatim.

**Point (footnote, when a claim spans many figures):**

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim quote"]
    [url="https://full-url" quote="exact verbatim quote"]

Becomes `[N]` at render time, with a reference appendix at the bottom.
Read by convention as covering the preceding sentence — vaguer scope,
useful when the claim is the whole sentence and pulling out a fragment
would be artificial.

The chunk_id is the bracketed label in the linearized text (e.g.
`p2:b01`, `p2:t0r1c1`). The quote MUST be a verbatim substring of
that chunk's text. Render-time validation drops cites where the chunk
is unknown or the quote is not found.

## Step 3: render

    echo "<your answer markdown>" | groundling render <prep_dir> --answer -

Render rewrites your markdown so each marker becomes a `[N]` link
pointing at a local cites/N.html. Print the rewritten markdown to the
user verbatim — that is the final answer. stderr carries
`validated=N invalid_chunk=N invalid_quote=N invalid_url=N`; consider
surfacing the counts if any cites were dropped.

Exit code 5 means zero markers survived validation — your answer is
ungrounded. Consider rephrasing or asking the user.

For browser viewing, the run dir also contains `answer.html` — a
self-contained page with a trust-strip header, state-styled inline
cites, a hover card per cite, and a click-to-open modal that loads
the full cite page in an iframe. Serve it via `groundling serve`
and open `http://127.0.0.1:8123/<run_id>/answer.html`.

If the user's terminal doesn't make `file://` links clickable, pass
`--web-base http://localhost:8123` to `render` and start `groundling
serve` in a second shell — that serves the state dir over HTTP so
cite links open in a browser.

## Step 4: judge the cites (REQUIRED)

After the first render produces `answer.md` and `manifest.json`, you MUST
run the judge before surfacing the answer to the user. The judge is the
reason this project exists — without it, citations are only syntactically
validated, not semantically verified.

**Skip only if the user explicitly opted out** — e.g., said "skip the
judge", "quick answer please", "don't verify the cites" at some point in
this conversation. Absent an explicit opt-out, do not skip on your own
judgment. "It looks fine, I'll skip it" is not acceptable.

The judge runs as a second pass that decorates each cite with a verdict.
It deposits JSON into `/tmp/groundling-judge/` and re-invokes render
with `--judge-dir`, which stamps `data-state` and `data-judge-note`
onto every cite anchor and turns on the Spotlight toggle.

```bash
mkdir -p /tmp/groundling-judge
```

### Pass 1: uncited significant claims (batched)

Scan the rewritten answer (the markdown render just wrote into the run
dir) for factual claims that should have had a cite marker but don't.
Produce the full list in ONE pass over the answer.

Read the entire rewritten `answer.md` and identify factual claims that:
  (a) name a specific number, date, attribution, or causal mechanism,
      AND
  (b) have NO citation marker (`[N]`, `chunk://`, or `web://`) within
      the same sentence.

Skip:
  - Framing prose ("the report covers", "according to the data")
  - Opinion ("this is concerning", "an interesting finding")
  - Claims that paraphrase a nearby cited claim

For each uncited significant claim, produce:

    {"span_text": "exact verbatim substring of the answer",
     "before_context": "3-8 words immediately preceding the span",
     "after_context": "3-8 words immediately following the span",
     "note": "short reasoning (<= 200 chars)"}

Deposit a JSON array at `/tmp/groundling-judge/uncited.json`:

    [{"span_text": "...", "before_context": "...",
      "after_context": "...", "note": "..."},
     ...]

`span_text` must be a verbatim substring of the rewritten answer.md.
Write `[]` if no uncited claims — STILL write the file, do not skip
the deposit step. The re-render counter `uncited_unmatched` flags
spans we couldn't locate (usually a hallucinated paraphrase) and
`uncited_overlap` flags spans that landed inside an existing cite link.

### Pass 2: cited verdicts (batched)

Read `manifest.json` for the list of cites that need judging. For each
cite, you have access to its `claim_text`, its `cited_text` (quote), and
its source pointer (PDF stem + chunk_id, or web url).

Gather the source excerpts ONCE up front:
  - For each PDF cite, locate the matching chunk in
    `<prep_dir>/<pdf_stem>.chunks.json` and grab its full text.
  - For each web cite, locate the matching URL in
    `/tmp/groundling-web/*.json` and grab ±300 chars around the quote
    in `extracted_text`.

Now produce the FULL verdicts map in ONE structured response. For each
cite_id in `manifest.json`:

  1. Look at ONLY that cite's source excerpt, claim_text (or the
     sentence containing the cite in `answer.md` for point markers),
     and quote. Don't reference other cites or the rest of the answer
     while you decide this one.
  2. Decide ONE of:
     - **supported** — the source excerpt directly says what the claim
       says, or is the precise basis for the claimed fact.
     - **partial** — the source says something related (adjacent,
       weaker, broader, or narrower) but doesn't fully back the
       specific claim.
     - **unsupported** — the source is irrelevant, says something
       different, or actively contradicts the claim.
  3. Write a short note (≤ 200 chars) explaining the call.

Output the complete JSON map at once. Discipline: judge each cite as if
it were the only one — do not let earlier verdicts influence later ones,
and do not aggregate ("most cites are supported, so..."). Each verdict
is a fresh, scoped judgment.

Write the resulting map to `/tmp/groundling-judge/verdicts.json`:

    {"1": {"state": "supported", "note": "Source line states ..."},
     "2": {"state": "partial",   "note": "Source describes ..."},
     "3": {"state": "unsupported", "note": "Source says X, not Y."},
     ...}

Keys are stringified cite_ids matching `manifest.json`. EVERY cite in
`manifest.json` MUST appear in the map — none should be missing. If
you're unsure on a cite, mark it partial rather than skipping.

### Re-render with the judge

After all subagents return, re-invoke render with `--judge-dir`:

    groundling render <prep_dir> --answer /tmp/answer.md \
        --judge-dir /tmp/groundling-judge

The resulting `answer.html` carries state-colored cite underlines, a
working Spotlight toggle, judge notes in the hover card / modal, and
dashed-blue "needs-citation" underlines on any uncited significant
claims Pass 1 flagged. Stderr counters: `verdicts_missing` (cites
without verdicts — should be 0), `verdicts_unmapped` (verdict entries
for unknown cite_ids — should be 0), `uncited_matched` /
`uncited_unmatched` / `uncited_overlap` (Pass 1 span-location).

If `verdicts_missing > 0`, you missed cites in Pass 2 — add verdicts
for the missing cite_ids to `verdicts.json` and re-render.

---

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`; prep dirs under `<corpus>/.groundling-prep/`.
Run dirs are self-contained — `tar` one to share.
