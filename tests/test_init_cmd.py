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
