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

## Step 4: judge the cites (default-on)

**Run the judge by default after rendering.** Skip ONLY if the user
asked for a quick answer ("just the answer, no checking", "skip the
judge", "don't verify the cites"). Verifiability is the point of this
project — when in doubt, run it.

The judge runs as a second pass that decorates each cite with a verdict.
It deposits JSON into `/tmp/groundling-judge/` and re-invokes render
with `--judge-dir`, which stamps `data-state` and `data-judge-note`
onto every cite anchor and turns on the Spotlight toggle.

```bash
mkdir -p /tmp/groundling-judge
```

### Pass 1: uncited significant claims

Scan the rewritten answer (the markdown render just wrote into the run
dir) for factual claims that should have had a cite marker but don't.
One subagent gets the whole answer + corpus index; it returns a JSON
array of flagged spans.

Subagent prompt:

    Read this entire answer:
    <the rewritten answer.md content>

    Available source titles:
    <bulleted list of pdf filenames + web titles from the corpus>

    Identify factual claims in the answer that:
      (a) name a specific number, date, attribution, or causal
          mechanism, AND
      (b) have NO citation marker ([N], chunk://, or web://) within the
          same sentence.

    Skip:
      - Framing prose ("the report covers", "according to the data")
      - Opinion ("this is concerning", "an interesting finding")
      - Claims that paraphrase a nearby cited claim

    For each uncited significant claim, output JSON:
      {"span_text": "exact verbatim substring of the answer",
       "before_context": "3-8 words immediately preceding the span",
       "after_context": "3-8 words immediately following the span",
       "note": "short reasoning (<= 200 chars)"}

    Output a JSON array. Empty array if no uncited claims.

Deposit at `/tmp/groundling-judge/uncited.json`:

    [{"span_text": "...", "before_context": "...",
      "after_context": "...", "note": "..."},
     ...]

`span_text` must be a verbatim substring of the rewritten answer.md.
The re-render counter `uncited_unmatched` flags spans we couldn't
locate (usually a hallucinated paraphrase) and `uncited_overlap`
flags spans that landed inside an existing cite link.

### Pass 2: cited verdicts

For each cite in the run's `manifest.json`, dispatch a fresh Task
subagent with this exact prompt (fill the bracketed slots from
`manifest.json` + the corresponding `chunks.json` / web evidence):

    Source excerpt:
      <chunk text from <prep_dir>/<stem>.chunks.json for the cite's
       chunk_id, OR ±300 chars of extracted_text around the quote
       for web cites>

    Source label: <pdf_stem · page N | url>

    Claim from the answer:
      <the claim_text from the cite record, OR the sentence in
       answer.md that contains the cite for point markers>

    Cited quote:
      "<quote from the cite record>"

    Does the source excerpt support the claim? Answer in ONE of:
    - supported: the source directly says what the claim says, or
      is the precise basis for the claimed fact
    - partial: the source says something related — adjacent, weaker,
      broader, or narrower — but doesn't fully back the specific
      claim
    - unsupported: the source is irrelevant, says something different,
      or actively contradicts the claim

    Output JSON ONLY, no prose:
    {"state": "supported|partial|unsupported",
     "note": "<= 200 chars explaining the call"}

Collect all subagent outputs into `/tmp/groundling-judge/verdicts.json`:

    {"1": {"state": "supported", "note": "..."},
     "2": {"state": "partial",   "note": "..."},
     ...}

Keys are stringified cite_ids matching `manifest.json`.

### Re-render with the judge

After all subagents return, re-invoke render with `--judge-dir`:

    groundling render <prep_dir> --answer /tmp/answer.md \
        --judge-dir /tmp/groundling-judge

The resulting `answer.html` carries state-colored cite underlines, a
working Spotlight toggle, judge notes in the hover card / modal, and
dashed-blue "needs-citation" underlines on any uncited significant
claims Pass 1 flagged. stderr reports counters from both passes:
`verdicts_missing` / `verdicts_unmapped` (Pass 2 cross-reference) and
`uncited_matched` / `uncited_unmatched` / `uncited_overlap` (Pass 1
span-location).

---

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`; prep dirs under `<corpus>/.groundling-prep/`.
Run dirs are self-contained — `tar` one to share.
