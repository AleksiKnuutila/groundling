"""Single-file self-contained answer.html for Claude.ai skill use.

Differences from answer_html.py:
- PNGs base64-inlined as data: URIs (no cites/N.png files)
- Cite content in inline <dialog> elements (no iframe)
- Renders standalone — open the .html in a browser, no server needed
"""
from __future__ import annotations

import base64
import html as html_lib
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
    """
    inline_cites = []
    for rec in cite_records:
        cid = rec["cite_id"]
        if rec["kind"] == "pdf":
            data_uri = _png_to_data_uri(image_paths[cid])
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
                "cite_id": cid, "kind": "pdf", "data_uri": data_uri,
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
        else:
            inline_cites.append({
                "cite_id": cid, "kind": "web",
                "url": rec["url"],
                "quote": rec["marker_quote"],
                "claim": rec.get("claim_text") or "",
            })

    decorated_body = _decorate_for_inline(
        answer_md, cite_records,
        image_paths=image_paths, image_dims=image_dims, scale=scale,
    )
    template = _env.get_template("answer_inline.html.j2")
    return template.render(
        answer_html=decorated_body, inline_cites=inline_cites,
    )


def _decorate_for_inline(
    answer_md, cite_records, *, image_paths, image_dims, scale,
):
    """Render markdown to HTML; decorate cite anchors with data-* attrs
    and rewrite cite://N hrefs to #cite-N in-page anchors."""
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
            attrs["data-img"] = _png_to_data_uri(image_paths[cid])
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
        return (
            f'<a class="cite" href="#cite-{cid}"{rest} {attrs_str}>'
            f'{inner}<span class="preview"></span></a>'
        )

    return anchor_re.sub(_replace, rendered)
