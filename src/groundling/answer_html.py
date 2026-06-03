"""Build a browser-native answer view: answer.html.

Takes the validated cite records and the rewritten answer markdown
from run_render and emits a single self-contained HTML page with cite
highlights, hover previews of the cited PDF region, and a side-pane
iframe of the full cite page.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "j2"),
    ),
)


def build_cite_attrs(
    cite_record: dict,
    *,
    image_filename: str | None,
    image_w_px: int | None,
    image_h_px: int | None,
    scale: float,
) -> dict[str, str]:
    """Compute the data-* attributes for one cite anchor.

    PDF cites get image + union-bbox geometry; web cites get just
    cite_id + kind. All bbox values are in image pixels (PDF points
    times scale)."""
    attrs = {
        "data-cite-id": str(cite_record["cite_id"]),
        "data-kind": cite_record["kind"],
        "data-state": "none",  # PR 2 overrides per verdicts.json.
    }
    if cite_record["kind"] != "pdf":
        url = cite_record.get("url")
        if url:
            attrs["data-url"] = url
        return attrs

    # Union bbox across all spans (PDF points).
    spans = cite_record["spans"]
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)

    attrs["data-img"] = f"cites/{image_filename}"
    attrs["data-img-w"] = str(int(image_w_px))
    attrs["data-img-h"] = str(int(image_h_px))
    attrs["data-bx"] = str(int(x0 * scale))
    attrs["data-by"] = str(int(y0 * scale))
    attrs["data-bw"] = str(int((x1 - x0) * scale))
    attrs["data-bh"] = str(int((y1 - y0) * scale))
    return attrs


def _cite_id_from_href(
    href: str,
    *,
    run_dir_name: str,
) -> int | None:
    """Extract cite_id from a `…/<run_dir_name>/cites/N.html` href.
    Returns None if href doesn't match the cite URL pattern."""
    m = re.search(
        rf"/{re.escape(run_dir_name)}/cites/(\d+)\.html$", href,
    )
    return int(m.group(1)) if m else None


def decorate_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_dims: dict[int, tuple[str, int, int]],
    run_dir_name: str,
    scale: float,
) -> str:
    """Render answer_md to HTML and decorate cite anchors with
    `class="cite"` + data-* attributes.

    Non-cite links (any other href) are left untouched.

    image_dims maps cite_id -> (image_filename, image_w_px, image_h_px)
    for PDF cites. Web cites are absent."""
    records_by_id = {r["cite_id"]: r for r in cite_records}

    md = MarkdownIt("commonmark").enable("table")
    # Allow file:// URLs so local-file cite hrefs survive rendering.
    md.validateLink = lambda url: True
    rendered_html = md.render(answer_md)

    # Walk anchors via regex. The HTML markdown-it emits is well-formed
    # enough that a single non-greedy <a …>…</a> regex catches every
    # link cleanly. We rewrite each anchor in place.
    anchor_re = re.compile(
        r'<a\s+href="([^"]+)"([^>]*)>(.*?)</a>',
        re.DOTALL,
    )

    def _replace(m: re.Match) -> str:
        href, rest, inner = m.group(1), m.group(2), m.group(3)
        cite_id = _cite_id_from_href(href, run_dir_name=run_dir_name)
        if cite_id is None or cite_id not in records_by_id:
            return m.group(0)  # not a cite link — leave alone

        record = records_by_id[cite_id]
        if record["kind"] == "pdf":
            image_filename, image_w_px, image_h_px = image_dims[cite_id]
        else:
            image_filename, image_w_px, image_h_px = None, None, None

        attrs = build_cite_attrs(
            record,
            image_filename=image_filename,
            image_w_px=image_w_px,
            image_h_px=image_h_px,
            scale=scale,
        )
        attrs_str = " ".join(
            f'{k}="{html.escape(v, quote=True)}"' for k, v in attrs.items()
        )
        return (
            f'<a class="cite" href="{href}"{rest} {attrs_str}>'
            f'{inner}</a>'
        )

    return anchor_re.sub(_replace, rendered_html)


def build_answer_html(
    *,
    answer_md: str,
    cite_records: list[dict],
    image_dims: dict[int, tuple[str, int, int]],
    run_dir_name: str,
    scale: float = 2.0,
    page_title: str | None = None,
    subtitle: str | None = None,
) -> str:
    """Build the full answer.html page from the rewritten markdown.

    Returns a self-contained HTML string. Cite anchors are decorated
    for hover preview + click-to-modal-iframe behaviour."""
    answer_html = decorate_answer_html(
        answer_md=answer_md,
        cite_records=cite_records,
        image_dims=image_dims,
        run_dir_name=run_dir_name,
        scale=scale,
    )
    total_cites = len(cite_records)
    if subtitle is None:
        subtitle = f"{total_cites} cites validated" if total_cites else ""
    template = _env.get_template("answer.html.j2")
    return template.render(
        answer_html=answer_html,
        page_title=page_title,
        subtitle=subtitle,
        total_cites=total_cites,
        has_judge_data=False,  # PR 2 sets this when verdicts.json is present.
    )
