# Adoption Readiness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make groundling install-and-go for a fresh Claude Code session — `pipx install`, point Claude at a corpus folder, get a grounded answer with cite links on first try.

**Architecture:** Four self-contained changes: (1) move AGENTS.md into the wheel and symlink at root; (2) a `groundling init` command that idempotently injects/updates a marked section into the corpus dir's AGENTS.md (beads pattern); (3) a `groundling instructions` command that prints the bundled template; (4) a README rewrite; (5) a shell smoke test that builds the wheel, installs via `uv tool install`, and exercises the CLI end-to-end.

**Tech Stack:** Python 3.11+, `importlib.resources` for template loading, Hatch build backend (already configured), Typer CLI (already configured), bash for the smoke test.

**Design doc:** `docs/plans/2026-05-30-adoption-readiness-design.md` — read first if any task is ambiguous.

---

## Reading the existing code

Before Task 1, skim these for context (don't memorise; reach for them when needed):

- `AGENTS.md` (repo root) — the 118-line file we're moving + bundling. The body becomes the template.
- `src/groundling/cli.py` — Typer app, existing subcommands (`ask`, `prep`, `render`, `serve`). Add `init` and `instructions` here.
- `src/groundling/templates/` — already ships in the wheel; we add `agents_template.md` here.
- `pyproject.toml` — Hatch wheel target already includes everything under `src/groundling/`. No changes expected.
- `tests/conftest.py` — `text_pdf` fixture. New init tests don't need it (they only need a temp dir).
- `README.md` — the 75-line file we're rewriting in Task 5.

`importlib.resources` quick reference (Python 3.11+):

```python
from importlib.resources import files
content = files("groundling.templates").joinpath("agents_template.md").read_text(encoding="utf-8")
```

This works regardless of whether the package is editable-installed, wheel-installed, or zipped — the standard cross-distribution way.

---

## Task 1: Move AGENTS.md into the package + symlink at root

**Why first:** every later task depends on the template being loadable from the package. Doing this first means subsequent tasks can `import groundling.init_cmd` and have the file exist.

**Files:**
- Move: `AGENTS.md` → `src/groundling/templates/agents_template.md` (content unchanged).
- Create: symlink `AGENTS.md` → `src/groundling/templates/agents_template.md` at repo root.
- Test: `tests/test_template_bundling.py` (new).

**Step 1: Write the failing test**

Create `tests/test_template_bundling.py`:

```python
"""Verify AGENTS.md template is bundled and loadable from the package."""
from __future__ import annotations

from importlib.resources import files


def test_agents_template_loadable_from_package():
    """The bundled AGENTS.md template must be readable via importlib.resources.

    This test fails if Hatch ever stops shipping the file in the wheel
    (e.g. because of a typo in pyproject.toml or a renamed directory).
    """
    template = (
        files("groundling.templates")
        .joinpath("agents_template.md")
        .read_text(encoding="utf-8")
    )
    # Sanity-check the content: the existing AGENTS.md starts with this
    # heading. If someone replaces the template with something else,
    # this will fail loudly so we can confirm intent.
    assert template.startswith("# Grounded Q&A — groundling"), (
        f"unexpected template start: {template[:80]!r}"
    )
    # And it should be the full file, not a stub.
    assert len(template) > 1000, "template suspiciously short — was it truncated?"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_template_bundling.py -v`
Expected: FAIL with `FileNotFoundError` or similar — `agents_template.md` doesn't exist in templates dir.

**Step 3: Move the file + create symlink**

```bash
git mv AGENTS.md src/groundling/templates/agents_template.md
ln -s src/groundling/templates/agents_template.md AGENTS.md
```

Verify:
```bash
cat AGENTS.md | head -3  # should print first lines via the symlink
ls -la AGENTS.md          # should show the -> arrow
test -L AGENTS.md && echo "is symlink"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_template_bundling.py -v`
Expected: PASS — the template loads from the package.

**Step 5: Run full suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: 132 + 1 = 133 passing.

**Step 6: Commit**

```bash
git add -A  # the move, the symlink, the test
git commit -m "refactor: move AGENTS.md into wheel templates, symlink at root"
```

---

## Task 2: `groundling.init_cmd` — pure logic with markers

The brain of the init command: parse-or-create AGENTS.md content, inject/update a marked section, return the new content. Pure function, no I/O. Tests pin all three cases (absent / present-with-markers / present-without-markers) without touching the disk.

**Files:**
- Create: `src/groundling/init_cmd.py`
- Test: `tests/test_init_cmd.py`

**Step 1: Write the failing tests**

Create `tests/test_init_cmd.py`:

```python
"""Pure-function tests for inject_section: no I/O, no fixtures."""
from __future__ import annotations

from groundling.init_cmd import (
    BEGIN_MARKER,
    END_MARKER,
    inject_section,
)


TEMPLATE_BODY = (
    "# Grounded Q&A — groundling\n\nDo stuff with PDFs.\n"
)


def test_inject_into_absent_file_creates_wrapped_content():
    """When existing is None (file absent), output is just the wrapped
    template — no extra blank lines, ends with a newline."""
    result = inject_section(existing=None, template=TEMPLATE_BODY)
    assert result.startswith(BEGIN_MARKER + "\n")
    assert TEMPLATE_BODY in result
    assert result.rstrip().endswith(END_MARKER)
    assert result.endswith("\n")


def test_inject_into_marked_file_replaces_only_the_section():
    """When existing AGENTS.md already has our markers, replace ONLY
    the content between them. User content above/below is preserved."""
    existing = (
        "# My project\n"
        "\n"
        "Some user prose here.\n"
        "\n"
        f"{BEGIN_MARKER}\n"
        "# Old groundling content\n\n"
        "outdated stuff.\n"
        f"{END_MARKER}\n"
        "\n"
        "More user content after.\n"
    )
    result = inject_section(existing=existing, template=TEMPLATE_BODY)
    # User content above and below survives.
    assert "# My project" in result
    assert "Some user prose here." in result
    assert "More user content after." in result
    # Old groundling content is gone.
    assert "Old groundling content" not in result
    assert "outdated stuff." not in result
    # New template content is present.
    assert TEMPLATE_BODY in result
    # Exactly one pair of markers (no duplicates).
    assert result.count(BEGIN_MARKER) == 1
    assert result.count(END_MARKER) == 1


def test_inject_into_unmarked_file_appends_section():
    """When existing AGENTS.md has no markers, append our wrapped
    section at the end. All existing content is preserved."""
    existing = "# User's existing AGENTS.md\n\nTheir stuff.\n"
    result = inject_section(existing=existing, template=TEMPLATE_BODY)
    # User content is at the top, unchanged.
    assert result.startswith("# User's existing AGENTS.md")
    assert "Their stuff." in result
    # Our markers + template appended.
    assert BEGIN_MARKER in result
    assert END_MARKER in result
    assert TEMPLATE_BODY in result
    # Markers come AFTER user content.
    assert result.index("Their stuff.") < result.index(BEGIN_MARKER)


def test_inject_is_idempotent():
    """Running inject twice produces the same result as running it once
    (the second run replaces the section we just wrote)."""
    once = inject_section(existing=None, template=TEMPLATE_BODY)
    twice = inject_section(existing=once, template=TEMPLATE_BODY)
    assert once == twice
    assert twice.count(BEGIN_MARKER) == 1


def test_inject_preserves_trailing_newline_when_appending():
    """When appending to existing content that lacks a trailing newline,
    the output still has a clean separator (no glued markers)."""
    existing = "# Title\n\nNo trailing newline"  # deliberately no \n
    result = inject_section(existing=existing, template=TEMPLATE_BODY)
    # Should not have "No trailing newline<!-- BEGIN" mashed together.
    assert "No trailing newline\n" in result
    assert "No trailing newline" + BEGIN_MARKER not in result


def test_markers_include_v1_version_suffix():
    """Marker constants must include 'v1' so we can evolve the format
    later. Regression guard against silently changing the marker string
    in a way that orphans existing user files."""
    assert "v1" in BEGIN_MARKER
    assert BEGIN_MARKER == "<!-- BEGIN GROUNDLING INSTRUCTIONS v1 -->"
    assert END_MARKER == "<!-- END GROUNDLING INSTRUCTIONS -->"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init_cmd.py -v`
Expected: 6 FAIL with `ModuleNotFoundError: No module named 'groundling.init_cmd'`.

**Step 3: Implement init_cmd.py**

Create `src/groundling/init_cmd.py`:

```python
"""groundling init: drop or update AGENTS.md in cwd via marked section.

Pattern stolen from beads (https://github.com/gastownhall/beads): an
idempotent section between BEGIN/END markers means re-running init
updates the section in place without clobbering the rest of the file.
"""
from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path


BEGIN_MARKER = "<!-- BEGIN GROUNDLING INSTRUCTIONS v1 -->"
END_MARKER = "<!-- END GROUNDLING INSTRUCTIONS -->"


def load_template() -> str:
    """Return the bundled AGENTS.md template body."""
    return (
        files("groundling.templates")
        .joinpath("agents_template.md")
        .read_text(encoding="utf-8")
    )


def _wrapped_section(template: str) -> str:
    body = template.rstrip()
    return f"{BEGIN_MARKER}\n{body}\n{END_MARKER}\n"


def inject_section(*, existing: str | None, template: str) -> str:
    """Return AGENTS.md content with our wrapped section injected.

    - existing=None → output is just the wrapped section.
    - existing contains our markers → replace section in place,
      preserving everything outside the markers.
    - existing has no markers → append wrapped section at the end,
      with a clean newline separator.
    """
    wrapped = _wrapped_section(template)

    if existing is None:
        return wrapped

    # Replace existing marked section if present.
    section_re = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
        re.DOTALL,
    )
    if section_re.search(existing):
        return section_re.sub(wrapped, existing)

    # Append: ensure a clean newline separator between user content and
    # our section.
    sep = "" if existing.endswith("\n") else "\n"
    return f"{existing}{sep}\n{wrapped}"
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_init_cmd.py -v`
Expected: 6 passed.

**Step 5: Run full suite**

Run: `uv run pytest -q`
Expected: 133 + 6 = 139 passing.

**Step 6: Commit**

```bash
git add src/groundling/init_cmd.py tests/test_init_cmd.py
git commit -m "feat(init): inject_section + marker constants — pure logic"
```

---

## Task 3: `run_init()` orchestrator + CLI wiring

Wraps `inject_section` with the filesystem read/write. Adds the `groundling init` and `groundling instructions` Typer commands.

**Files:**
- Modify: `src/groundling/init_cmd.py` — add `run_init(cwd) -> InitResult`.
- Modify: `src/groundling/cli.py` — add `init` and `instructions` subcommands.
- Test: `tests/test_init_cmd.py` — append integration tests using `tmp_path`.

**Step 1: Write the failing tests**

Append to `tests/test_init_cmd.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from groundling.cli import app
from groundling.init_cmd import InitResult, run_init


def test_run_init_creates_agents_md_in_empty_dir(tmp_path):
    """When AGENTS.md doesn't exist, run_init creates it with our
    wrapped section."""
    result = run_init(tmp_path)
    target = tmp_path / "AGENTS.md"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert BEGIN_MARKER in content
    assert END_MARKER in content
    assert "# Grounded Q&A — groundling" in content
    assert result.path == target
    assert result.action == "created"


def test_run_init_updates_existing_marked_file(tmp_path):
    """When AGENTS.md exists with our markers, run_init replaces the
    section in place — preserving user content around it."""
    target = tmp_path / "AGENTS.md"
    target.write_text(
        f"# My project\n\nUser content.\n\n"
        f"{BEGIN_MARKER}\nold stuff\n{END_MARKER}\n",
        encoding="utf-8",
    )
    result = run_init(tmp_path)
    content = target.read_text(encoding="utf-8")
    assert "User content." in content
    assert "old stuff" not in content
    assert "# Grounded Q&A — groundling" in content
    assert content.count(BEGIN_MARKER) == 1
    assert result.action == "updated"


def test_run_init_appends_to_unmarked_file(tmp_path):
    """When AGENTS.md exists without our markers, run_init appends our
    section at the end, preserving all user content."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# Their stuff\n\nPre-existing prose.\n", encoding="utf-8")
    result = run_init(tmp_path)
    content = target.read_text(encoding="utf-8")
    assert content.startswith("# Their stuff")
    assert "Pre-existing prose." in content
    assert BEGIN_MARKER in content
    assert "# Grounded Q&A — groundling" in content
    assert result.action == "appended"


def test_cli_init_creates_file_in_cwd(tmp_path, monkeypatch):
    """`groundling init` writes AGENTS.md in the current working dir."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (tmp_path / "AGENTS.md").exists()
    # Stdout reports what happened (path + action).
    assert "AGENTS.md" in result.stdout
    assert "created" in result.stdout.lower()


def test_cli_init_is_idempotent_on_repeat(tmp_path, monkeypatch):
    """Two runs of `groundling init` produce the same file content."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    first = (tmp_path / "AGENTS.md").read_text()
    result = runner.invoke(app, ["init"])
    second = (tmp_path / "AGENTS.md").read_text()
    assert result.exit_code == 0
    assert first == second
    # Second run reports "updated" (markers present from first run).
    assert "updated" in result.stdout.lower()


def test_cli_instructions_prints_template(tmp_path, monkeypatch):
    """`groundling instructions` prints the bundled template to stdout."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["instructions"])
    assert result.exit_code == 0
    assert "# Grounded Q&A — groundling" in result.stdout
    assert "Mode A" in result.stdout
    assert "Mode B" in result.stdout
    # Does NOT write anything to disk.
    assert not (tmp_path / "AGENTS.md").exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init_cmd.py -v`
Expected: 6 prior PASS + 6 new FAIL with `ImportError: cannot import name 'run_init'` and missing CLI subcommands.

**Step 3: Implement run_init + InitResult**

Append to `src/groundling/init_cmd.py`:

```python
from dataclasses import dataclass


@dataclass
class InitResult:
    path: Path
    action: str  # "created" | "updated" | "appended"


def run_init(cwd: Path) -> InitResult:
    """Read existing AGENTS.md (if any), inject/replace our section,
    write back. Returns what happened so the CLI can report it."""
    target = cwd / "AGENTS.md"
    template = load_template()

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        action = "updated" if BEGIN_MARKER in existing else "appended"
    else:
        existing = None
        action = "created"

    new_content = inject_section(existing=existing, template=template)
    target.write_text(new_content, encoding="utf-8")
    return InitResult(path=target, action=action)
```

**Step 4: Wire CLI subcommands**

In `src/groundling/cli.py`, after the existing `serve` subcommand block, append:

```python
@app.command()
def init():
    """Drop or refresh AGENTS.md in the current directory.

    Creates AGENTS.md with groundling's workflow instructions if absent.
    If AGENTS.md exists and already has our marked section, updates it
    in place. If AGENTS.md exists without our markers, appends our
    section at the end — preserving the user's content.
    """
    from pathlib import Path

    from groundling.init_cmd import run_init

    result = run_init(Path.cwd())
    typer.echo(f"{result.action}: {result.path}")


@app.command()
def instructions():
    """Print the bundled AGENTS.md template to stdout — no write."""
    from groundling.init_cmd import load_template

    typer.echo(load_template())
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_init_cmd.py -v`
Expected: 12 passed (6 prior + 6 new).

**Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: 145 passing (139 + 6 new).

**Step 7: Commit**

```bash
git add src/groundling/init_cmd.py src/groundling/cli.py tests/test_init_cmd.py
git commit -m "feat(cli): groundling init + instructions subcommands"
```

---

## Task 4: README rewrite

The current README describes only mode A and tells users to download AGENTS.md from a URL that doesn't exist. Replace it with a structure that describes both modes, the `groundling init` flow, browser viewing via `groundling serve` + `answer.html`, and a real install path.

**Files:**
- Modify: `README.md`

**Step 1: Replace README content**

Replace the entire contents of `README.md` with:

````markdown
# groundling

Grounded Q&A over a folder of PDFs, with cite links you can click to
verify. Designed for use from Claude Code (or any AGENTS.md-aware
agent).

Two modes — pick based on what you have:

- **Mode A — API-backed.** `groundling ask "..."` calls the Anthropic
  Messages API with citations enabled. Single command, pay-per-token.
- **Mode B — agent-driven.** `groundling prep` + agent fan-out +
  `groundling render` uses your Claude subscription. The agent reads
  per-PDF linearized text, emits cite markers, render validates them
  into clickable links.

Both modes produce `answer.md` + a self-contained `answer.html`
browser view with cite highlights, hover-to-preview-PDF popovers,
and click-opens-side-pane source viewing.

## Install

    pipx install groundling
    # or, for local development:
    pipx install /path/to/groundling

## Quick start

    cd ~/my-research/        # contains your PDFs
    groundling init          # drops AGENTS.md
    claude                   # or codex, or any AGENTS.md-aware agent

In the agent session:

    > what does Q1 say about revenue growth?

The agent reads AGENTS.md, picks the appropriate mode (Mode A if
`ANTHROPIC_API_KEY` is set, Mode B otherwise), runs groundling, prints
the answer with cite links.

## Browser viewing

    groundling serve                                    # in another shell
    # then open in browser:
    http://localhost:8123/<run_id>/answer.html

Cite spans are highlighted; hover any cite to see a popover with the
source PDF region; click to open the full cite page in a side pane.

## Commands

| Command | Purpose |
| --- | --- |
| `groundling init` | Drop or refresh AGENTS.md in cwd |
| `groundling instructions` | Print AGENTS.md template to stdout |
| `groundling ask` | Mode A: one-shot question via Anthropic API |
| `groundling prep` | Mode B step 1: per-PDF chunks + linearized text |
| `groundling render` | Mode B step 2: validate agent cite markers → answer.md + answer.html |
| `groundling serve` | Static HTTP server for cite pages (default port 8123) |

Run any command with `--help` for full flag listings.

## State on disk

Per corpus directory:

- `qa-runs/<run-id>/` — one subdir per question, contains `answer.md`,
  `answer.html`, `manifest.json`, `cites/N.html`+`cites/N.png`.
- `.groundling-prep/<stamp>/` — mode-B chunks + linearized text +
  `dispatch_hint.json`.
- `.groundling-cache/` — per-PDF word-extraction cache.

All three are gitignore candidates.

## How it works

See `docs/plans/` for design docs covering each mode and the
intermediate artefacts:

- v1 / Mode A — Anthropic Messages API with citations enabled
- Agent mode / Mode B — prep + render + marker contract
- Wrapping-cite contract — wrapping markdown links vs point markers
- answer.html — browser view with hover preview + side pane

## Limits

- **No OCR.** Scanned PDFs without extractable text exit early
  (`groundling ask` exit code 3). OCR externally first.
- **No table-structure inference for prose linearization.** Mode A
  uses PyMuPDF's reading order as-is; complex multi-column layouts
  may produce garbled linearization, though cited bboxes remain
  correct per-word. Mode B uses `find_tables()` for tighter
  per-cell chunks when `--tables` is on.
- **No persistent project model.** Each invocation is a fresh,
  isolated run. Past runs accumulate under `qa-runs/`.

## License

TBD.
````

**Step 2: Verify the README still renders cleanly as markdown**

Quick sanity check:

```bash
head -30 README.md
wc -l README.md
```

Expected: starts with `# groundling`, ~75-90 lines.

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): rewrite for both modes, init flow, answer.html"
```

---

## Task 5: Shell smoke test for install path

A bash script that builds the wheel, installs into an isolated `uv tool` env, exercises each new CLI command, and asserts the obvious things work. Catches wheel-packaging bugs (missing templates in wheel, broken entry points) that pytest can't catch because pytest runs inside the dev venv.

**Files:**
- Create: `scripts/smoke_install.sh` (executable).

**Step 1: Write the script**

Create `scripts/smoke_install.sh`:

```bash
#!/usr/bin/env bash
# Smoke-test the pipx install path. Builds the wheel, installs into
# an isolated uv tool env, exercises the CLI end-to-end. Run before
# tagging a release or after touching pyproject.toml / build config.
#
# Usage: ./scripts/smoke_install.sh
# Exit: 0 on success, non-zero on any failure.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

echo "== Building wheel =="
rm -rf dist/
uv build --wheel

WHEEL=$(ls -t dist/groundling-*.whl | head -1)
test -f "$WHEEL"
echo "Built: $WHEEL"

echo "== Installing into isolated tool env =="
uv tool install --force "$WHEEL"

echo "== Verifying entry point =="
groundling --help >/dev/null

echo "== Verifying bundled template via 'instructions' =="
groundling instructions | head -5 | grep -q "Grounded Q&A — groundling"

echo "== Verifying init in a temp dir =="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

groundling init
test -f AGENTS.md
grep -q "BEGIN GROUNDLING INSTRUCTIONS v1" AGENTS.md

echo "== Verifying init idempotency =="
groundling init
count=$(grep -c "BEGIN GROUNDLING INSTRUCTIONS v1" AGENTS.md)
test "$count" = "1" || {
    echo "FAIL: expected 1 BEGIN marker, found $count"
    exit 1
}

echo "== Verifying init preserves user content =="
printf '\n# My own notes\n\nHere is some prose.\n' >> AGENTS.md
groundling init
grep -q "My own notes" AGENTS.md

cd "$REPO_ROOT"
echo "== Cleanup =="
uv tool uninstall groundling
rm -rf dist/

echo ""
echo "SMOKE TEST PASSED"
```

**Step 2: Make it executable**

```bash
chmod +x scripts/smoke_install.sh
```

**Step 3: Run it once to verify it actually passes**

```bash
./scripts/smoke_install.sh
```

Expected: every section logs progress, final line is `SMOKE TEST PASSED`, exit 0. This is the real verification — the script *itself* is the test.

If it fails, fix whatever it surfaces (most likely candidates: wheel doesn't include `agents_template.md`, or `groundling` entry point doesn't resolve, or `uv tool install` can't find a dep). Don't suppress failures.

**Step 4: Commit**

```bash
git add scripts/smoke_install.sh
git commit -m "test(install): shell smoke test for wheel build + uv tool install"
```

---

## Task 6: Verify everything end-to-end

No new files. This is the final integration check.

**Step 1: Run the full pytest suite**

```bash
uv run pytest -q
```

Expected: 145 passing (132 baseline + 1 bundling + 12 init).

**Step 2: Run the smoke install script**

```bash
./scripts/smoke_install.sh
```

Expected: `SMOKE TEST PASSED`.

**Step 3: Manually verify the README renders**

```bash
head -50 README.md
```

Expected: clean markdown, headings, install instructions, command table.

**Step 4: Manually verify the symlinked AGENTS.md still works**

```bash
ls -la AGENTS.md  # should show -> arrow
head -3 AGENTS.md  # should print first lines of the real file
```

Expected: symlink points at `src/groundling/templates/agents_template.md`, `cat`/`head` work transparently.

**No commit for this task** — it's verification.

---

## Out of scope (file as follow-ups if needed)

- `groundling auto <corpus> <question>` one-shot — defer until adoption shows it's needed.
- `groundling init --stealth` — add when a user asks.
- `groundling init --update-only` — add when needed.
- Per-agent setup commands (`groundling setup claude`, etc.).
- Publishing to PyPI. Smoke test validates local install; pypi push is a separate concern.
- README badges (build status, version) — add when there's a CI/release pipeline.
