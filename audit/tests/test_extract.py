"""Tests for front-view extraction and cabinet splitting (issue #3).

Known-answer tests: the DXF inputs come from the fixture builder with
hand-computable bounding boxes, so expected values are literals derived
from the fixture geometry, never from the code under test.
"""

import ezdxf
import pytest

from audit_tool import fixtures
from audit_tool.extract import extract_cabinets


def save_scenario(tmp_path, name, filename):
    path = tmp_path / filename
    fixtures.save_dxf(fixtures.build_scenario(name), path)
    return path


def compose_sheet(docs, gap=200.0):
    """Place fixture drawings side by side (bottom-aligned) into one DXF doc."""
    sheet = ezdxf.new("R2018", setup=False)
    for layer in (
        fixtures.LAYER_PANEL,
        fixtures.LAYER_PARTITION,
        fixtures.LAYER_SHELF,
        fixtures.LAYER_ROD,
        fixtures.LAYER_DRAWER,
        fixtures.LAYER_COUNTERTOP,
    ):
        sheet.layers.add(name=layer)
    offset_x = 0.0
    for doc in docs:
        for e in doc.modelspace():
            if e.dxftype() == "LWPOLYLINE":
                pts = [(x + offset_x, y) for x, y in e.get_points("xy")]
                pl = sheet.modelspace().add_lwpolyline(
                    pts, format="xy", dxfattribs={"layer": e.dxf.layer}
                )
                pl.closed = e.closed
        extent = max(x for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE" for x, _ in e.get_points("xy"))
        offset_x += extent + gap
    return sheet


def test_single_cabinet_dxf_yields_one_cabinet_with_full_bbox(tmp_path):
    # baseline wardrobe: 2000 wide x 2400 high, origin at bottom-left
    path = save_scenario(tmp_path, "wardrobe_2000_baseline", "one.dxf")

    cabinets = extract_cabinets(path)

    assert len(cabinets) == 1
    (cab,) = cabinets
    assert cab.index == 0
    assert cab.bbox == pytest.approx((0.0, 0.0, 2000.0, 2400.0))
    assert len(cab.entities) > 0


def test_multi_cabinet_sheet_splits_by_vertical_gaps(tmp_path):
    # one wardrobe (2000x2400) + one base cabinet (840x800 incl. countertop
    # overhang of 20 each side) + one wardrobe (2150x2400), 200 mm gaps.
    # Hand-computed bboxes, gap accumulated left to right:
    #   cab0: (0, 0, 2000, 2400)
    #   cab1: (2200-20, 0, 2200+800+20, 800) = (2180, 0, 3020, 800)
    #   cab2: (3020+200, 0, 3220+2150, 2400) = (3220, 0, 5370, 2400)
    sheet = compose_sheet(
        [
            fixtures.build_scenario("wardrobe_2000_baseline"),
            fixtures.build_scenario("base_cabinet_800"),
            fixtures.build_scenario("wardrobe_2150_tol_within"),
        ]
    )
    path = tmp_path / "sheet.dxf"
    fixtures.save_dxf(sheet, path)

    cabinets = extract_cabinets(path)

    assert [c.index for c in cabinets] == [0, 1, 2]
    assert cabinets[0].bbox == pytest.approx((0.0, 0.0, 2000.0, 2400.0))
    assert cabinets[1].bbox == pytest.approx((2180.0, 0.0, 3020.0, 800.0))
    assert cabinets[2].bbox == pytest.approx((3220.0, 0.0, 5370.0, 2400.0))
    # each split keeps its own geometry: baseline wardrobe = 4 carcass panels
    # + 1 divider + 1 door divider + 2 compartment dividers + 8 shelves/rods
    # + 2 drawers = 18 rectangles
    assert len(cabinets[0].entities) == 18
    assert len(cabinets[1].entities) == 5  # 4 carcass + countertop
    assert len(cabinets[2].entities) > 0

