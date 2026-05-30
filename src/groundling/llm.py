"""Anthropic Messages API call with native citations + optional web_search."""
from __future__ import annotations

from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "You are answering questions about a set of documents.\n"
    "Cite every concrete claim back to the documents using the "
    "built-in citations feature.\n"
    "\n"
    "Block splitting for fine-grained attribution: emit each distinct "
    "factual claim — every figure, date, name, or assertion — as its "
    "own text block, attached to the citation that supports it. Use "
    "unattributed text blocks only for connective phrases that carry "
    "no factual claim. This lets each cited figure link to its exact "
    "source span instead of dragging a whole sentence with it.\n"
    "\n"
    "Prefer the shortest contiguous source range that grounds each claim "
    "— not the whole table or paragraph around it.\n"
    "Do not invent figures, names, dates, or facts not in the documents.\n"
    "Be concise."
)


def build_documents_payload(docs: list[tuple[str, str]]) -> list[dict]:
    """One document block per (filename, linearized_text). Citations enabled,
    ephemeral cache control on each block so multi-question sessions hit cache."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": text},
            "title": filename,
            "citations": {"enabled": True},
            "cache_control": {"type": "ephemeral"},
        }
        for filename, text in docs
    ]


def ask_with_citations(
    *,
    client: Any,
    model: str,
    docs: list[tuple[str, str]],
    question: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 4096,
    web_search: bool = False,
    web_search_max_uses: int = 5,
) -> Any:
    """Make the API call. Returns the raw response."""
    document_blocks = build_documents_payload(docs)
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": document_blocks + [{"type": "text", "text": question}],
        }],
    )
    if web_search:
        kwargs["tools"] = [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": web_search_max_uses,
        }]
    return client.messages.create(**kwargs)
