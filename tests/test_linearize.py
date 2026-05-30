from __future__ import annotations

from groundling.linearize import linearize_words, resolve_range


def _words(*tuples):
    """tuples of (content, page, x0, y0, x1, y1) — concise test helper."""
    return [
        {"content": c, "page": p, "bbox": [x0, y0, x1, y1]}
        for (c, p, x0, y0, x1, y1) in tuples
    ]


def test_linearize_joins_words_with_single_space():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 1, 11, 0, 25, 5),
    )
    text, entries = linearize_words(words)
    assert text == "Hello world."
    assert len(entries) == 2


def test_first_entry_starts_at_zero():
    words = _words(("Hello", 1, 0, 0, 10, 5))
    text, entries = linearize_words(words)
    assert entries[0]["char_start"] == 0
    assert entries[0]["char_end"] == len("Hello")


def test_second_entry_starts_after_separator():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 1, 11, 0, 25, 5),
    )
    text, entries = linearize_words(words)
    assert entries[1]["char_start"] == len("Hello ")
    assert entries[1]["char_end"] == len(text)


def test_entries_carry_page_and_bbox():
    words = _words(
        ("Hello", 1, 0, 0, 10, 5),
        ("world.", 2, 30, 40, 50, 45),
    )
    _, entries = linearize_words(words)
    assert entries[0]["page"] == 1
    assert entries[0]["bbox"] == [0, 0, 10, 5]
    assert entries[1]["page"] == 2
    assert entries[1]["bbox"] == [30, 40, 50, 45]


def test_empty_words_yields_empty_text():
    text, entries = linearize_words([])
    assert text == ""
    assert entries == []


# resolve_range tests --------------------------------------------------

def _fixture_entries():
    # Three entries: "Hello" [0,5), "world." [6,12), "Page two" [14,22)
    return [
        {"char_start": 0, "char_end": 5, "page": 1, "bbox": [0]*4},
        {"char_start": 6, "char_end": 12, "page": 1, "bbox": [0]*4},
        {"char_start": 14, "char_end": 22, "page": 2, "bbox": [0]*4},
    ]


def test_resolve_inside_one_entry():
    hits = resolve_range(_fixture_entries(), 1, 4)
    assert [h["char_start"] for h in hits] == [0]


def test_resolve_exact_one_entry():
    hits = resolve_range(_fixture_entries(), 0, 5)
    assert [h["char_start"] for h in hits] == [0]


def test_resolve_overlapping_two_entries():
    hits = resolve_range(_fixture_entries(), 3, 9)
    assert [h["char_start"] for h in hits] == [0, 6]


def test_resolve_separator_returns_empty():
    # Char 5 is the space between "Hello" and "world.".
    hits = resolve_range(_fixture_entries(), 5, 6)
    assert hits == []


def test_resolve_past_end_returns_empty():
    hits = resolve_range(_fixture_entries(), 500, 600)
    assert hits == []


def test_resolve_inverted_range_returns_empty():
    hits = resolve_range(_fixture_entries(), 10, 5)
    assert hits == []
