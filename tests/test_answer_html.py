"""build_cite_attrs() unit tests — pure function, no fixtures needed."""
from __future__ import annotations

from groundling.answer_html import build_cite_attrs


def test_build_cite_attrs_pdf_single_span():
    cite_record = {
        "cite_id": 1,
        "kind": "pdf",
        "spans": [{"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]}],
    }
    attrs = build_cite_attrs(
        cite_record, image_filename="1.png", image_w_px=1240, image_h_px=1754,
        scale=2.0,
    )
    assert attrs == {
        "data-cite-id": "1",
        "data-kind": "pdf",
        "data-img": "cites/1.png",
        "data-img-w": "1240",
        "data-img-h": "1754",
        "data-bx": "20",       # 10.0 * 2.0
        "data-by": "40",       # 20.0 * 2.0
        "data-bw": "40",       # (30-10) * 2.0
        "data-bh": "40",       # (40-20) * 2.0
    }


def test_build_cite_attrs_pdf_multi_span_uses_union_bbox():
    """Multi-span cite: union bbox spans from leftmost-topmost to
    rightmost-bottommost word, in image pixels."""
    cite_record = {
        "cite_id": 2,
        "kind": "pdf",
        "spans": [
            {"page": 1, "bbox": [10.0, 20.0, 30.0, 40.0]},
            {"page": 1, "bbox": [50.0, 25.0, 80.0, 45.0]},
            {"page": 1, "bbox": [12.0, 22.0, 28.0, 38.0]},
        ],
    }
    attrs = build_cite_attrs(
        cite_record, image_filename="2.png", image_w_px=1240, image_h_px=1754,
        scale=2.0,
    )
    # Union bbox in PDF pts: x0=10, y0=20, x1=80, y1=45
    # Scaled 2x: bx=20, by=40, bw=(80-10)*2=140, bh=(45-20)*2=50
    assert attrs["data-bx"] == "20"
    assert attrs["data-by"] == "40"
    assert attrs["data-bw"] == "140"
    assert attrs["data-bh"] == "50"


def test_build_cite_attrs_web():
    cite_record = {"cite_id": 3, "kind": "web"}
    attrs = build_cite_attrs(
        cite_record, image_filename=None, image_w_px=None, image_h_px=None,
        scale=2.0,
    )
    assert attrs == {"data-cite-id": "3", "data-kind": "web"}
