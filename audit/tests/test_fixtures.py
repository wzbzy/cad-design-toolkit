"""Tests for the DXF fixture builder (known-answer cabinets).

The builder is the seam agreed for this ticket: tests assert on the DXF
entities it produces (entity counts per layer, bounding box), never on
internal helper calls.
"""

import ezdxf
import pytest

from audit_tool import fixtures


def closed_polylines(doc, layer=None):
    """Return all closed LWPOLYLINE entities in modelspace, optionally by layer."""
    msp = doc.modelspace()
    return [
        e
        for e in msp
        if e.dxftype() == "LWPOLYLINE" and e.closed and (layer is None or e.dxf.layer == layer)
    ]


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def doc_bbox(doc):
    pts = []
    for e in closed_polylines(doc):
        pts.extend(e.get_points("xy"))
    return bbox(pts)


class TestBaselineWardrobe:
    """移门衣柜基准：2000x2400，顶柜 2 门，下柜 3 分区，左层板x4/中双衣通/右上层板x2+下抽屉x2。"""

    def test_saves_and_reads_back_as_valid_dxf(self, tmp_path):
        doc = fixtures.build_wardrobe()
        path = tmp_path / "wardrobe_baseline.dxf"
        fixtures.save_dxf(doc, path)

        reloaded = ezdxf.readfile(path)
        assert reloaded is not None
        # all geometry survives the roundtrip
        assert len(closed_polylines(reloaded)) == len(closed_polylines(doc))

    def test_bounding_box_is_full_cabinet_outline(self):
        doc = fixtures.build_wardrobe()
        assert doc_bbox(doc) == (0.0, 0.0, 2000.0, 2400.0)

    def test_entity_counts_match_described_structure(self):
        doc = fixtures.build_wardrobe()
        # 4 carcass panels (left/right/top/bottom)
        assert len(closed_polylines(doc, "PANEL")) == 4
        # top/bottom divider + 1 divider for 2 top doors + 2 dividers for 3 compartments
        assert len(closed_polylines(doc, "PARTITION")) == 4
        # left compartment: 4 shelves; right compartment: 2 more
        assert len(closed_polylines(doc, "SHELF")) == 6
        # middle compartment: double hanging rod
        assert len(closed_polylines(doc, "ROD")) == 2
        # right compartment: 2 drawers
        assert len(closed_polylines(doc, "DRAWER")) == 2
