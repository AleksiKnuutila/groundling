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
