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


def _json_for_html(obj) -> str:
    """JSON-encode `obj` safely for embedding inside a <script> tag.

    `json.dumps` doesn't escape `<`, `>`, `&`, or U+2028/U+2029, so a
    field containing the literal substring `</script>` would close the
    surrounding script block and inject the rest as HTML. We replace
    the four hazardous code points with their escaped JS-string forms.
    Same trick Flask's `tojson` filter uses."""
    return (
        json.dumps(obj, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


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
    page_title: str | None = None,
    subtitle: str | None = None,
    verdicts: dict[int, dict] | None = None,
    uncited_wraps: list | None = None,
) -> str:
    """Build a single self-contained HTML file. See module docstring.

    When `verdicts` is non-empty (PR 2), each entry in `cites_by_id`
    gets its `state` overridden with the judge's verdict and a
    `judgeNote` added; the trust-strip Spotlight button is rendered
    (has_judge_data=True).

    When `uncited_wraps` is non-empty (PR 3), each entry contributes a
    synthetic `cites_by_id` record keyed by `u1`, `u2`, etc. The
    hover-card + modal JS look these up by data-cite-id on the
    pre-wrapped uncited anchors that already live in `answer_md`."""
    verdicts = verdicts or {}
    uncited_wraps = uncited_wraps or []
    # Slot registry: each unique image path → one data URI.
    path_to_slot: dict[Path, int] = {}
    image_slots: list[str] = []
    slot_by_cite: dict[int, int] = {}
    for cid, path in image_paths.items():
        if path not in path_to_slot:
            path_to_slot[path] = len(image_slots)
            image_slots.append(_png_to_data_uri(path))
        slot_by_cite[cid] = path_to_slot[path]

    # Build the cites-by-id map the new template's JS consumes.
    cites_by_id: dict[str, dict] = {}
    for rec in cite_records:
        cid = rec["cite_id"]
        verdict = verdicts.get(cid)
        entry: dict = {
            "id": cid,
            "kind": rec["kind"],
            "state": (verdict or {}).get("state", "none"),
            "claim": rec.get("claim_text") or "",
            "quote": rec["marker_quote"],
        }
        if verdict and verdict.get("note"):
            entry["judgeNote"] = verdict["note"]
        if rec["kind"] == "pdf":
            image_w, image_h = image_dims[cid]
            x0 = min(s["bbox"][0] for s in rec["spans"])
            y0 = min(s["bbox"][1] for s in rec["spans"])
            x1 = max(s["bbox"][2] for s in rec["spans"])
            y1 = max(s["bbox"][3] for s in rec["spans"])
            bx = int(x0 * scale); by = int(y0 * scale)
            bw = int((x1 - x0) * scale); bh = int((y1 - y0) * scale)
            page = rec["spans"][0]["page"]
            filename = rec.get("pdf_filename", "")
            entry.update({
                "slot": slot_by_cite[cid],
                "imgW": image_w, "imgH": image_h,
                "bx": bx, "by": by, "bw": bw, "bh": bh,
                "bxPct": bx / image_w * 100, "byPct": by / image_h * 100,
                "bwPct": bw / image_w * 100, "bhPct": bh / image_h * 100,
                "page": page,
                "filename": filename,
                "sourceLabel": f"{filename} · p.{page}",
            })
        else:  # web
            excerpt_html = _build_excerpt_html(
                rec["excerpt"], rec["marker_quote"],
                rec["quote_offset_in_excerpt"],
            )
            try:
                from urllib.parse import urlparse
                host = urlparse(rec["url"]).hostname or ""
                if host.startswith("www."):
                    host = host[4:]
            except Exception:
                host = ""
            entry.update({
                "url": rec["url"],
                "host": host,
                "title": rec.get("title", ""),
                "fetchedAt": rec.get("fetched_at", ""),
                "excerptHTML": excerpt_html,
                "sourceLabel": rec.get("title") or rec["url"],
            })
        cites_by_id[str(cid)] = entry

    # PR 3: synthetic entries for uncited (Pass 1) spans. The hover-card
    # + modal JS look these up by data-cite-id (e.g. "u1"). No source
    # crop/excerpt — the modal shows the judge's note in place of source.
    for w in uncited_wraps:
        cites_by_id[w.synthetic_id] = {
            "id": w.synthetic_id,
            "kind": "uncited",
            "state": "needs-citation",
            "claim": w.span_text,
            "quote": "",
            "judgeNote": w.note,
            "sourceLabel": "No source — judge flagged",
        }

    decorated_body = _decorate_for_inline(answer_md, cite_records, verdicts)

    total_cites = len(cite_records)
    if subtitle is None:
        subtitle = f"{total_cites} cites validated" if total_cites else ""

    # PR 2/3: the Spotlight button appears whenever we have any judge
    # data — Pass 2 verdicts OR Pass 1 uncited flags. Without either,
    # every cite stays at data-state="none" and the toggle would just
    # dim the whole page.
    has_judge_data = bool(verdicts or uncited_wraps)

    template = _env.get_template("answer_inline.html.j2")
    return template.render(
        answer_html=decorated_body,
        cites_json=_json_for_html(cites_by_id),
        image_slots_json=_json_for_html(image_slots),
        page_title=page_title,
        subtitle=subtitle,
        total_cites=total_cites,
        has_judge_data=has_judge_data,
    )


def _decorate_for_inline(answer_md, cite_records, verdicts=None):
    """Render markdown to HTML; rewrite cite://N anchors to a.cite with
    data-* attrs. Per-cite imagery and excerpts live in
    window.GROUNDLING_CITES (server-side JSON), not in DOM."""
    md = MarkdownIt("commonmark").enable("table")
    md.validateLink = lambda url: True
    rendered = md.render(answer_md)

    verdicts = verdicts or {}
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
        verdict = verdicts.get(cid)
        state = (verdict or {}).get("state", "none")
        # data-cite-id + data-kind + data-state. Everything else lives in
        # window.GROUNDLING_CITES, looked up by id.
        attrs = (
            f'data-cite-id="{cid}" '
            f'data-kind="{rec["kind"]}" '
            f'data-state="{state}"'
        )
        if verdict and verdict.get("note"):
            note_attr = html_lib.escape(verdict["note"], quote=True)
            attrs += f' data-judge-note="{note_attr}"'
        # No href: in the Claude.ai artifact iframe, navigating to
        # #cite-N bubbles a fragment change to the parent frame, which
        # tries to navigate claudeusercontent.com instead of opening
        # the modal. role+tabindex preserve keyboard a11y.
        return (
            f'<a class="cite" role="button" tabindex="0"{rest} '
            f'{attrs}>{inner}</a>'
        )

    return anchor_re.sub(_replace, rendered)
