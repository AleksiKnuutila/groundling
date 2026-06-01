---
name: groundling
description: Grounded Q&A over PDFs uploaded to a Project, optionally extended with web sources. Produces a self-contained HTML artifact with cite spans that show source passages on hover and open a full PDF-page view on click. Use when the user asks a question that requires verifiable citations from uploaded PDF documents — even casually (like "what does the report say about X" when PDFs are in scope). Do NOT trigger for ungrounded summarisation, for non-PDF documents (use docx/xlsx skills for those), or when the user explicitly asks for an answer without citations.
---

# Groundling — grounded PDF Q&A

Produces a verifiable answer to a question grounded in uploaded PDFs.
The output is a single self-contained `answer.html` the user can open
as an artifact; cite spans on hover show the source PDF region with
the cited passage highlighted.

Bundled wheels in `wheels/` make this work in any sandbox network
setting — no PyPI access required.

## Workflow

### Step 1: Bootstrap

Run once per sandbox lifetime. Idempotent — a sentinel file at
`/tmp/.groundling-installed` skips re-install on subsequent runs.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/bootstrap.py
```

### Step 2: Find the user's PDFs

Use bash to locate uploaded PDFs in the sandbox. Common locations vary
by surface; check the working directory first, then `/mnt/user-data/`
or similar attachment paths. Pass the directory containing the PDFs to
prep.

### Step 3: Prep (cache-aware)

Build per-PDF chunks and linearized text. The output dir is
`/tmp/groundling-prep` by convention. Skip prep if the dir already
exists from an earlier turn in this conversation.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/prep.py \
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
substring of the cited chunk's text.

**Point (footnote):** when the claim is the whole preceding sentence
and pulling out a fragment would feel artificial.

    [chunk=<pdf-stem>:<chunk_id> quote="exact verbatim quote"]
    [url="https://full-url" quote="exact verbatim quote"]

See `reference.md` for marker validation rules and edge cases.

### Step 5: Render

Validate markers and produce the single-file HTML. The script prints
counters to stderr like
`validated=9 invalid_chunk=0 invalid_quote=0 invalid_url=0` — if any
marker fails validation, re-read the chunk text and fix the quote.

Exit code 5 means zero markers survived validation — your answer is
ungrounded, rewrite it.

```bash
python ${CLAUDE_SKILL_DIR}/scripts/render.py \
    --prep-dir /tmp/groundling-prep \
    --corpus <pdf-dir> \
    --answer /tmp/answer.md \
    --out /tmp/answer.html
```

### Step 6: Surface to user

Print the answer markdown to the conversation, with cite markers
rewritten to `[N]` superscript-style references (the markdown body
should read cleanly, not as raw markers). Attach `/tmp/answer.html`
as a file artifact so the user can open it inline.
