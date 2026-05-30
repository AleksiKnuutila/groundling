"""Build a browser-native answer view: answer.html.

Takes the validated cite records and the rewritten answer markdown
from run_render and emits a single self-contained HTML page with cite
highlights, hover previews of the cited PDF region, and a side-pane
iframe of the full cite page.
"""
from __future__ import annotations


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
    }
    if cite_record["kind"] != "pdf":
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
