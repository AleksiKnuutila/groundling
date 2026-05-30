# groundling

Grounded Q&A over a folder of PDFs, with citations you can click to verify.

Designed for use from Claude Code: drop `AGENTS.md` into your project, set
`ANTHROPIC_API_KEY`, ask questions. The tool prints a markdown answer with
clickable citation links — PDF citations open a local HTML page with the
cited page rendered and the cited text highlighted; web citations (opt-in
via `--web-search`) open the source URL with the cited sentence highlighted
natively by the browser.

**Status:** pre-v1. See `docs/plans/2026-05-30-groundling-design.md`.
