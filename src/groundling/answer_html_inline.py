"""Single-file self-contained answer.html for Claude.ai skill use.

Differences from answer_html.py:
- PNGs base64-inlined as data: URIs (no cites/N.png files)
- Cite content in inline <dialog> elements (no iframe)
- Renders standalone — open the .html in a browser, no server needed
"""
from __future__ import annotations

import base64
import html as html_lib
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt

from groundling.answer_html import build_cite_attrs


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "j2")),
)


def _png_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _build_excerpt_html(excerpt: str, quote: str, q_off: int) -> str:
    """Server-side splice: HTML-escape excerpt, wrap quote span in <mark>.

    Caller must ensure `excerpt[q_off : q_off+len(quote)] == quote`."""
    assert excerpt[q_off : q_off + len(quote)] == quote, (
        "quote offset does not match excerpt content"
    )
    before = html_lib.escape(excerpt[:q_off])
    middle = html_lib.escape(quote)
    after = html_lib.escape(excerpt[q_off + len(quote):])
    return f"{before}<mark>{middle}</mark>{after}"


def build_inline_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_paths: dict[int, Path],
    image_dims: dict[int, tuple[int, int]],
    scale: float = 2.0,
) -> str:
    """Build a single self-contained HTML file.

    cite_records entries must include:
      - cite_id, kind ("pdf" or "web"), spans (for pdf)
      - marker_quote: verbatim cited text
      - claim_text: agent's claim wrapping the cite (or None)
      - pdf_filename (for pdf) or url (for web)

    image_paths maps cite_id -> Path to PDF page PNG; base64-inlined.
    image_dims maps cite_id -> (width_px, height_px) of that PNG.
    answer_md uses cite://N as href scheme (rewritten upstream).

    Multiple cites on the same PDF page share an image_paths entry —
    we deduplicate by path so each unique image is base64-encoded
    once into a registry and referenced by slot id everywhere else.
    """
    # Build the slot registry: each unique image path → one data URI.
    path_to_slot: dict[Path, int] = {}
    image_slots: list[str] = []
    slot_by_cite: dict[int, int] = {}
    for cid, path in image_paths.items():
        if path not in path_to_slot:
            path_to_slot[path] = len(image_slots)
            image_slots.append(_png_to_data_uri(path))
        slot_by_cite[cid] = path_to_slot[path]

    inline_cites = []
    excerpt_html_by_id: dict[int, str] = {}
    for rec in cite_records:
        cid = rec["cite_id"]
        if rec["kind"] == "pdf":
            image_w, image_h = image_dims[cid]
            x0 = min(s["bbox"][0] for s in rec["spans"])
            y0 = min(s["bbox"][1] for s in rec["spans"])
            x1 = max(s["bbox"][2] for s in rec["spans"])
            y1 = max(s["bbox"][3] for s in rec["spans"])
            bx = int(x0 * scale)
            by = int(y0 * scale)
            bw = int((x1 - x0) * scale)
            bh = int((y1 - y0) * scale)
            inline_cites.append({
                "cite_id": cid, "kind": "pdf",
                "slot": slot_by_cite[cid],
                "bx": bx, "by": by, "bw": bw, "bh": bh,
                "bx_pct": bx / image_w * 100,
                "by_pct": by / image_h * 100,
                "bw_pct": bw / image_w * 100,
                "bh_pct": bh / image_h * 100,
                "quote": rec["marker_quote"],
                "claim": rec.get("claim_text") or "",
                "filename": rec.get("pdf_filename", ""),
                "page": rec["spans"][0]["page"],
            })
        else:  # web
            excerpt_html = _build_excerpt_html(
                rec["excerpt"], rec["marker_quote"],
                rec["quote_offset_in_excerpt"],
            )
            excerpt_html_by_id[cid] = excerpt_html
            inline_cites.append({
                "cite_id": cid, "kind": "web",
                "url": rec["url"],
                "title": rec["title"],
                "fetched_at": rec["fetched_at"],
                "quote": rec["marker_quote"],
                "claim": rec.get("claim_text") or "",
                "excerpt_html": excerpt_html,
            })

    decorated_body = _decorate_for_inline(
        answer_md, cite_records,
        slot_by_cite=slot_by_cite, image_dims=image_dims, scale=scale,
        excerpt_html_by_id=excerpt_html_by_id,
    )
    template = _env.get_template("answer_inline.html.j2")
    return template.render(
        answer_html=decorated_body,
        inline_cites=inline_cites,
        image_slots_json=json.dumps(image_slots),
    )


def _decorate_for_inline(
    answer_md, cite_records, *, slot_by_cite, image_dims, scale,
    excerpt_html_by_id: dict[int, str],
):
    """Render markdown to HTML; decorate cite anchors with data-* attrs
    and rewrite cite://N hrefs to #cite-N in-page anchors.

    PDF cite anchors carry `data-img-slot=N` instead of the data URI
    itself — runtime JS looks the URI up from the shared registry, so
    each unique image is base64-encoded exactly once in the HTML."""
    md = MarkdownIt("commonmark").enable("table")
    md.validateLink = lambda url: True
    rendered = md.render(answer_md)

    records_by_id = {r["cite_id"]: r for r in cite_records}
    anchor_re = re.compile(
        r'<a\s+href="cite://(\d+)"([^>]*)>(.*?)</a>', re.DOTALL,
    )

    def _replace(m):
        cid = int(m.group(1))
        rest, inner = m.group(2), m.group(3)
        rec = records_by_id.get(cid)
        if rec is None:
            return m.group(0)
        if rec["kind"] == "pdf":
            image_w, image_h = image_dims[cid]
            attrs = build_cite_attrs(
                {"cite_id": cid, "kind": "pdf", "spans": rec["spans"]},
                image_filename=f"_inline_{cid}",
                image_w_px=image_w, image_h_px=image_h, scale=scale,
            )
            # Drop data-img (was the per-cite data URI); use slot id.
            attrs.pop("data-img", None)
            attrs["data-img-slot"] = str(slot_by_cite[cid])
        else:
            attrs = build_cite_attrs(
                {"cite_id": cid, "kind": "web"},
                image_filename=None, image_w_px=None,
                image_h_px=None, scale=scale,
            )
        attrs_str = " ".join(
            f'{k}="{html_lib.escape(v, quote=True)}"'
            for k, v in attrs.items()
        )
        if rec["kind"] == "web":
            preview = (
                f'<span class="preview preview-text">'
                f'{excerpt_html_by_id[cid]}</span>'
            )
        else:
            preview = '<span class="preview"></span>'
        return (
            f'<a class="cite" href="#cite-{cid}"{rest} {attrs_str}>'
            f'{inner}{preview}</a>'
        )

    return anchor_re.sub(_replace, rendered)
