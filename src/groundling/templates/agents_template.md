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

---

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`; prep dirs under `<corpus>/.groundling-prep/`.
Run dirs are self-contained — `tar` one to share.
