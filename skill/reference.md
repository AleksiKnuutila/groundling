# groundling — reference

Level-2 detail loaded on demand from SKILL.md. Contains marker
validation rules, script flags, exit codes, common errors.

## prep.py

```
python scripts/prep.py --corpus <DIR> --out <DIR> [--no-tables]
```

- `--corpus` — directory of `.pdf` files; other extensions ignored.
- `--out` — output directory; created if missing.
- `--no-tables` — skip `find_tables()` table detection. Use for
  prose-heavy corpora or when table-detection produces noisy
  chunks. Default is tables-on (better cite precision on financial
  docs).

Output per PDF:
- `<stem>.linearized.txt` — chunk-id-bracketed plain text Claude
  reads to formulate the answer.
- `<stem>.chunks.json` — list of `{chunk_id, text, page, bbox,
  word_idx_start, word_idx_end}` for render-time validation.

Exit codes:
- `0` — success
- `2` — no PDFs in --corpus

## render.py

```
python scripts/render.py --prep-dir <DIR> --corpus <DIR> \
    --answer <FILE> --out <FILE>
```

- `--prep-dir` — output of `prep.py`.
- `--corpus` — original PDFs (used to re-render page images for
  cite previews).
- `--answer` — markdown with cite markers.
- `--out` — single self-contained `answer.html` written here.

Stderr counters: `validated=N invalid_chunk=N invalid_quote=N
invalid_url=N`. Self-correction signal — if non-zero invalid_*,
re-read the chunk and fix the quote, then re-render.

Exit codes:
- `0` — success
- `5` — zero markers survived validation (answer is ungrounded)

## Marker validation rules

For every marker:

1. **Chunk lookup** — `<pdf-stem>` must match a `.chunks.json` file
   in the prep dir; `<chunk_id>` must exist in that file.
2. **Quote substring** — the `quote=` value must be a verbatim
   substring of the chunk's text. Unicode punctuation (curly
   quotes, em dashes, non-breaking spaces) is normalised to ASCII
   before comparison — you can quote with either form.
3. **Word resolution** — the quote's word positions in the chunk
   become the bbox highlight on the rendered page.

Invalid markers are silently dropped from the answer markdown. The
stderr counters tell you exactly how many and why.

## Web markers

Web cites have **loose validation only** in this skill — we trust
the marker without fetching the URL to verify the quote (network
access is optional in the sandbox). The user clicks through to the
source URL to verify.

## Common errors

- **"no PDFs in --corpus"** — wrong path; check `ls <corpus>` and
  verify the PDFs are there.
- **"zero valid cites"** — markers didn't validate. Most common
  cause: quote not a verbatim substring of the chunk. Re-read the
  linearized text and quote exactly.
- **`ModuleNotFoundError: No module named 'groundling'`** —
  bootstrap not run. Run `python scripts/bootstrap.py` first.
