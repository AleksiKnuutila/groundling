"""groundling init: drop or update AGENTS.md in cwd via marked section.

Pattern stolen from beads (https://github.com/gastownhall/beads): an
idempotent section between BEGIN/END markers means re-running init
updates the section in place without clobbering the rest of the file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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


@dataclass
class InitResult:
    path: Path
    action: str  # "created" | "updated" | "appended"


def run_init(cwd: Path) -> InitResult:
    """Read existing AGENTS.md (if any), inject/replace our section,
    write back. Returns what happened so the CLI can report it.
    """
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
