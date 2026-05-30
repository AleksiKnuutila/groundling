from __future__ import annotations

from unittest.mock import MagicMock

from groundling.llm import (
    DEFAULT_SYSTEM_PROMPT,
    ask_with_citations,
    build_documents_payload,
)


def test_build_documents_payload_shape():
    blocks = build_documents_payload([("BYD.pdf", "Hello world.")])
    assert len(blocks) == 1
    b = blocks[0]
    assert b["type"] == "document"
    assert b["source"] == {
        "type": "text", "media_type": "text/plain", "data": "Hello world.",
    }
    assert b["title"] == "BYD.pdf"
    assert b["citations"] == {"enabled": True}
    assert b["cache_control"] == {"type": "ephemeral"}


def test_build_documents_payload_preserves_order():
    blocks = build_documents_payload([("a.pdf", "AAA"), ("b.pdf", "BBB")])
    assert [b["title"] for b in blocks] == ["a.pdf", "b.pdf"]


def test_ask_with_citations_calls_client_without_tools():
    fake = MagicMock()
    fake.messages.create.return_value = "RESP"
    out = ask_with_citations(
        client=fake, model="claude-sonnet-4-6",
        docs=[("a.pdf", "AAA")], question="what?",
    )
    assert out == "RESP"
    kwargs = fake.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["system"] == DEFAULT_SYSTEM_PROMPT
    # No tools by default.
    assert kwargs.get("tools") in (None, [])
    content = kwargs["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[-1] == {"type": "text", "text": "what?"}


def test_ask_with_citations_adds_web_search_tool():
    fake = MagicMock()
    fake.messages.create.return_value = "RESP"
    ask_with_citations(
        client=fake, model="m", docs=[("a.pdf", "x")],
        question="q", web_search=True,
    )
    tools = fake.messages.create.call_args.kwargs.get("tools")
    assert tools and tools[0]["type"] == "web_search_20250305"
    assert tools[0]["name"] == "web_search"
