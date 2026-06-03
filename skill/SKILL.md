---
name: groundling
description: Grounded Q&A over PDFs uploaded to a Project and/or web sources fetched via web_search / web_fetch. Produces a self-contained HTML artifact with cite spans that show source passages on hover and open a full PDF-page view (or source URL) on click. Use when the user asks a question that requires verifiable citations from uploaded PDF documents or web sources — even casually (like "what does the report say about X" when PDFs are in scope, or "what's the latest reporting on Y" when web search is available). Do NOT trigger for ungrounded summarisation, for non-PDF local documents (use docx/xlsx skills for those), or when the user explicitly asks for an answer without citations.
---

# Groundling — grounded PDF Q&A

Produces a verifiable answer to a question grounded in uploaded PDFs
and/or web sources. The output is a single self-contained
`answer.html` the user can open as an artifact; cite spans on hover
show the source PDF region (or a snippet of the web page) with the
cited passage highlighted.

Bundled wheels in `wheels/` make this work in any sandbox network
setting — no PyPI access required.

## Workflow

### Step 1: Bootstrap

Run once per sandbox lifetime. Idempotent — a sentinel file at
`/tmp/.groundling-installed` skips re-install on subsequent runs.

```bash
python /skills/groundling/scripts/bootstrap.py
```

### Step 2: Find the user's PDFs

Use bash to locate uploaded PDFs in the sandbox. Common locations vary
by surface; check the working directory first, then `/mnt/user-data/`
or similar attachment paths. Pass the directory containing the PDFs to
prep.

### Step 2b: Web evidence deposit (if using web sources)

For each web source you intend to cite, deposit one JSON evidence
file in `/tmp/groundling-web/` so the renderer can validate quotes
against it. Use sequential numeric filenames (`01.json`, `02.json`,
...).

```bash
mkdir -p /tmp/groundling-web
cat > /tmp/groundling-web/01.json <<'EOF'
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "fetched_at": "2026-06-02T14:30:00Z",
  "extracted_text": "<verbatim copy of the readable text you got back from web_search / web_fetch>"
}
EOF
```

Critical rules:

- **Copy `extracted_text` verbatim** from your web tool result. Do
  not paraphrase, summarize, or truncate. The renderer validates
  that every cited quote is a verbatim substring of this text —
  any deviation will fail validation and drop the cite.
- **Use the same URL string in the marker and the evidence file.**
  Differences in trailing slashes, `?utm=` params, or `www.`
  prefix will cause the cite to be dropped with a
  `missing_evidence` counter.
- **Only deposit sources you will actually cite.** Speculative
  deposits waste sandbox space; the renderer ignores unused
  evidence files but they consume disk.
- **If the search snippet is too short to contain the quote you
  want, call `web_fetch` for the full content first.** A
  `web_search` result may only show a few sentences; deposit
  evidence based on the longer `web_fetch` body.

### Step 3: Prep (cache-aware)

Build per-PDF chunks and linearized text. The output dir is
`/tmp/groundling-prep` by convention. Skip prep if the dir already
exists from an earlier turn in this conversation.

```bash
python /skills/groundling/scripts/prep.py \
    --corpus <pdf-dir> \
    --out /tmp/groundling-prep
```

For each `<stem>.pdf`, this writes `<stem>.linearized.txt` and
`<stem>.chunks.json` into the out dir.

### Step 4: Read + answer

Read each `<stem>.linearized.txt` from the prep dir. Each chunk is
prefixed with a bracketed ID like `[p2:b01]` (prose block) or
`[p2:t0r1c1]` (table cell).

Formulate the answer in markdown. Embed cite markers next to claims
following the contract below. Write the answer to `/tmp/answer.md`.

#### Marker contract

Two shapes — **prefer the wrapping form** when you can name the
specific claim a cite supports:

**Wrapping (preferred):**

    [<claim text>](chunk://<pdf-stem>/<chunk_id> "exact verbatim quote")
    [<claim text>](web://https://full-url "exact verbatim quote")

The link text is the precise span of your answer that this citation
grounds. The quote in the title attribute MUST be a verbatim
substring of the cited source's text.

**Point (footnote):** when the claim is the whole preceding sentence
and pulling out a fragment would feel artificial.

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim quote"]
    [url="https://full-url" quote="exact verbatim quote"]

Validation rules — the same two forms apply to both schemes, and the
renderer enforces:

- `chunk://` — the chunk ID must resolve in the prep dir; the quote
  must be a verbatim substring of that chunk's text.
- `web://` — the URL must match (exactly, byte-for-byte) a `url`
  field in some `/tmp/groundling-web/*.json` evidence file; the
  quote must be a verbatim substring of that file's
  `extracted_text`. A URL with no matching evidence file is dropped
  under `missing_evidence`; a mismatched quote is dropped under
  `invalid_quote_web`.

See `reference.md` for further marker validation rules and edge
cases.

### Step 5: Render

Validate markers and produce the single-file HTML. The script prints
counters to stderr like
`validated=9 invalid_chunk=0 invalid_quote=0 invalid_url=0 missing_evidence=0 invalid_quote_web=0`
— if any marker fails validation, re-read the chunk / web evidence
text and fix the quote (or, for `missing_evidence`, fix the URL or
deposit the missing evidence file).

Exit code 5 means zero markers survived validation — your answer is
ungrounded, rewrite it.

```bash
python /skills/groundling/scripts/render.py \
    [--prep-dir /tmp/groundling-prep --corpus <pdf-dir>] \
    [--web-dir /tmp/groundling-web] \
    --answer /tmp/answer.md \
    --out /tmp/answer.html
```

At least one of `--prep-dir` (with `--corpus`) or `--web-dir` must
be present. Pass both when the answer mixes PDF and web cites.

### Step 6: Judge the cites (REQUIRED)

After the first render produces `answer.md` and `manifest.json`, you MUST
run the judge before surfacing the answer to the user. The judge is the
reason this skill exists — without it, citations are only syntactically
validated, not semantically verified.

**Skip only if the user explicitly opted out** — e.g., said "skip the
judge", "quick answer please", "don't verify the cites" at some point in
this conversation. Absent an explicit opt-out, do not skip on your own
judgment. "It looks fine, I'll skip it" is not acceptable.

The judge runs in two passes against the artifacts render just produced.
Both deposit JSON files at `/tmp/groundling-judge/` that a second render
pass reads.

```bash
mkdir -p /tmp/groundling-judge
```

#### Pass 1: uncited significant claims

Read the full rewritten `answer.md` (the one render just produced).
Scan for factual claims that:
  (a) name a specific number, date, attribution, or causal mechanism,
      AND
  (b) have NO citation marker (`[N]`, `chunk://`, `web://`) within
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

Write the resulting list to `/tmp/groundling-judge/uncited.json`. Write
an empty list `[]` if you find no uncited claims — STILL write the
file, do not skip the deposit step.

`span_text` must be a verbatim substring of the rewritten answer.md;
`before_context` / `after_context` are used to disambiguate when the
same span appears more than once. The re-render counter
`uncited_unmatched` flags spans we couldn't locate (usually a
hallucinated paraphrase) and `uncited_overlap` flags spans that
landed inside an existing cite link (skip and move on).

#### Pass 2: cited verdicts (batched)

Read `/tmp/groundling-prep/manifest.json` for the list of cites that need
judging. For each cite, you have access to its `claim_text`, its
`cited_text` (quote), and its source pointer (PDF stem + chunk_id, or
web url).

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

#### Step 6c: re-render with --judge-dir

Re-invoke render with the deposited judge data:

```bash
python /skills/groundling/scripts/render.py \
    --prep-dir /tmp/groundling-prep \
    --corpus <pdf-dir> \
    --answer /tmp/answer.md \
    --out /tmp/answer.html \
    --judge-dir /tmp/groundling-judge
```

The resulting answer.html will have state-colored cite underlines, the
Spotlight-weak-claims toggle in the trust strip, judge notes in the
hover-card and modal, and dashed-blue underlines on any uncited spans
Pass 1 caught. Stderr counters: `verdicts_missing` (cites without
verdicts — should be 0), `verdicts_unmapped` (verdicts for unknown
cite_ids — should be 0), `uncited_matched` / `uncited_unmatched` /
`uncited_overlap`.

If `verdicts_missing > 0`, you missed cites in Pass 2 — go back and
verdict them.

### Step 7: Surface to user

Print the answer markdown to the conversation, with cite markers
rewritten to clickable deep links into the HTML artifact:

    Operating revenue was RMB 170 billion [[1]](answer.html#cite-1).

The link target is the artifact filename + a `#cite-N` fragment;
answer.html's JS opens the matching cite dialog on load. Reads
cleanly in chat, jumps straight to the source preview when clicked.

Attach `/tmp/answer.html` as a file artifact so the user can open
it inline.
