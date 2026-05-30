# Grounded Q&A — groundling

When a user asks a research question and there's a `docs/` folder of PDFs,
answer it by running:

    groundling ask --corpus docs/ "<question>"

The command prints markdown to stdout. Each cited claim is a clickable
link. Pass the markdown through to the user verbatim — they will click
links to verify sources:

- PDF citations open a local HTML page with the rendered PDF page and
  the cited text highlighted.
- Web citations open the source URL with the cited sentence highlighted
  natively by the browser.

If the user wants the answer to also draw on current web sources, add
`--web-search`:

    groundling ask --corpus docs/ --web-search "<question>"

Default is docs-only — no external lookups. The user should opt in.

Exit codes:
- 0 — success
- 2 — corpus has zero PDFs
- 3 — a PDF couldn't be text-extracted (probably a scan)
- 5 — zero citations returned (the answer is ungrounded — consider
      rephrasing or surfacing this to the user)

State lives under `<corpus>/qa-runs/` (gitignore it). Cache under
`<corpus>/.groundling-cache/`. Run dirs are self-contained — `tar` one
to share.

Requires `ANTHROPIC_API_KEY` in env or a `.env` in the current dir.
