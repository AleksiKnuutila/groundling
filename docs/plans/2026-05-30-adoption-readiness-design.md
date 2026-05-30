# Adoption readiness — design

## Goal

Make `groundling` install-and-go for a fresh Claude Code session: a
user runs `pipx install groundling`, points Claude Code at any folder
of PDFs, and gets a grounded answer with cite links on the first try.

Four changes get us there:
1. `groundling init` writes/updates AGENTS.md in cwd (beads-style).
2. README rewrite — current README only describes mode A, has a
   stale download URL, and doesn't mention prep/render/serve/wrapping
   cites/answer.html.
3. Bundle the AGENTS.md content into the wheel so `init` has
   something to read post-install.
4. A shell smoke test that builds, installs, and exercises the CLI
   end-to-end in an isolated env.

## Item 1: `groundling init`

Pattern stolen from
[beads](https://github.com/gastownhall/beads):

- Writes to `./AGENTS.md` in cwd.
- If absent: create with the bundled template body.
- If present and contains our markers: replace the bracketed section
  in place. Idempotent.
- If present without markers: append our wrapped section at the end,
  preserving user content.

Marker shape:

```
<!-- BEGIN GROUNDLING INSTRUCTIONS v1 -->
[full body of the bundled agents_template.md]
<!-- END GROUNDLING INSTRUCTIONS -->
```

`v1` is a format version. Lets us upgrade marker shape later.

A fallback `groundling instructions` command prints the bundled
template to stdout — useful when init can't write, or for
inspecting what content init would produce.

No flags on init for v1. Beads has many (`--stealth`, `--force`,
`--non-interactive`); add as needs surface.

## Item 2: README rewrite

Current README's mental model is mode A only. The new README is
structured around the adoption path, not the architecture:

- Two-mode summary (when to use API vs subscription) upfront.
- Install via pipx (with a local-path option for dev).
- Quick start that uses `groundling init` instead of the current
  stale `curl -O` instruction.
- Section on browser viewing (`groundling serve` + answer.html).
- Command table covering all six commands (init, ask, prep, render,
  serve, instructions).
- Drop the "how it works" section that describes only mode A; point
  at design docs in docs/plans/ for readers who want internals.

Target length ~80–100 lines. Landing pad, not a manual.

## Item 3: Bundle AGENTS.md in the wheel

The current AGENTS.md lives at the repo root. `pipx install`'d
packages can only see files under `src/groundling/` — root files are
invisible at runtime.

**Move it** to `src/groundling/templates/agents_template.md` and
replace the root file with a symlink. Single source of truth, no
drift, dev experience unchanged (`cat AGENTS.md` works through the
symlink).

Hatch already ships `src/groundling/templates/` (because of
`cite_pdf.html.j2`, `cite_web.html.j2`, `answer.html.j2`). One more
file in that directory is free — no `pyproject.toml` change needed.

Runtime load:
```python
from importlib.resources import files
TEMPLATE = (
    files("groundling.templates")
    .joinpath("agents_template.md")
    .read_text()
)
```

Verify packaging works:
```
uv build && unzip -l dist/groundling-*.whl | grep templates
```
should show all four template files (3 existing + agents_template.md).

## Item 4: pipx install smoke test

A shell script at `scripts/smoke_install.sh` that:

1. Builds the wheel: `uv build --wheel`.
2. Installs into an isolated env: `uv tool install --force <wheel>`.
3. Verifies `groundling --help` works (entry point).
4. Verifies `groundling instructions` prints the bundled template
   (catches missing template-file bug).
5. Runs `groundling init` in a temp dir, asserts AGENTS.md exists
   with the marker.
6. Runs `groundling init` again, asserts no duplicate markers
   (idempotency check).
7. Appends user content to AGENTS.md, runs init a third time,
   asserts user content survives.
8. Cleans up: `uv tool uninstall groundling`; remove temp dir.

**Why shell not pytest:** pytest runs inside the dev venv where
groundling is editable-installed. Wheel-packaging bugs only surface
when you install the actual wheel into a separate environment. A
shell script using `uv tool install` is the cleanest way.

**Out of scope for v1:** end-to-end tests of ask/prep/render/serve
(need real PDFs + API key or live agent fan-out). Smoke test stays
focused on "install works, init works, instructions render."

## Architecture summary

New module: `src/groundling/init_cmd.py` (~80 lines)
- Loads bundled template via `importlib.resources`.
- `run_init(cwd) -> InitResult` — pure function modulo the file
  write. Returns counters/status so tests can pin behaviour without
  CLI scaffolding.
- Marker constants `BEGIN_MARKER = "<!-- BEGIN GROUNDLING INSTRUCTIONS v1 -->"`,
  `END_MARKER = "<!-- END GROUNDLING INSTRUCTIONS -->"`.
- Handles all three cases (absent / present-with-markers /
  present-without-markers).

CLI additions in `src/groundling/cli.py`:
- `groundling init` — calls `run_init(Path.cwd())`.
- `groundling instructions` — prints the bundled template.

Repo restructure:
- Move `AGENTS.md` → `src/groundling/templates/agents_template.md`.
- Replace root `AGENTS.md` with a symlink.

Tests (in `tests/test_init.py`, ~6 unit tests):
- Template loads from the package.
- Absent AGENTS.md → file created with markers.
- Present-with-markers AGENTS.md → section replaced, marker count
  stays at 1.
- Present-without-markers AGENTS.md → section appended, original
  content preserved.
- Re-running init is idempotent.
- `groundling instructions` prints content starting with the
  template's first heading.

Plus `scripts/smoke_install.sh` for the install-time verification
(not in pytest).

## Out of scope (file as follow-ups if needed)

- `groundling auto <corpus> <question>` one-shot. The AGENTS.md
  workflow is now disciplined enough that a casual user gets
  reasonable behaviour; one-shot is polish.
- `groundling init --stealth` (don't commit AGENTS.md). Add when a
  user asks.
- `groundling init --update-only` (only refresh if markers present;
  don't create). Add when needed.
- Per-agent setup commands (`groundling setup claude`, etc.). Beads
  has these; we only need AGENTS.md right now.
- Publishing to PyPI. Out of scope for this work; smoke test
  validates local install.
