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


def layer_counts(doc):
    """Map layer name -> number of closed rectangles on it."""
    counts = {}
    for e in closed_polylines(doc):
        counts[e.dxf.layer] = counts.get(e.dxf.layer, 0) + 1
    return counts


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


class TestWidthVariants:
    """同拓扑变体：仅宽 2150（差 150，容差内）与宽 2300（差 300，容差外）。"""

    @pytest.mark.parametrize("width", [2150, 2300])
    def test_same_topology_as_baseline(self, width):
        baseline_counts = layer_counts(fixtures.build_wardrobe())
        variant_counts = layer_counts(fixtures.build_wardrobe(width=width))
        assert variant_counts == baseline_counts

    @pytest.mark.parametrize("width", [2000, 2150, 2300])
    def test_bounding_box_tracks_width(self, width):
        doc = fixtures.build_wardrobe(width=width)
        assert doc_bbox(doc) == (0.0, 0.0, float(width), 2400.0)


class TestAltTopology:
    """异拓扑：下柜 4 分区版，必须与 3 分区基准的拓扑计数不同。"""

    def test_four_compartments_have_more_partitions(self):
        alt = fixtures.build_wardrobe(
            compartment_layouts=(
                fixtures.CompartmentLayout(shelves=4),
                fixtures.CompartmentLayout(rods=2),
                fixtures.CompartmentLayout(drawers=3),
                fixtures.CompartmentLayout(shelves=1, drawers=2),
            )
        )
        # top/bottom divider + 1 top door divider + 3 compartment dividers
        assert len(closed_polylines(alt, "PARTITION")) == 5
        assert layer_counts(alt) != layer_counts(fixtures.build_wardrobe())


class TestBaseCabinet:
    """异品类：一台地柜橱柜（800x800 台面结构）。"""

    def test_countertop_overhangs_both_sides(self):
        doc = fixtures.build_base_cabinet()
        assert doc_bbox(doc) == (-20.0, 0.0, 820.0, 800.0)

    def test_structure_is_carcass_plus_countertop(self):
        doc = fixtures.build_base_cabinet()
        assert len(closed_polylines(doc, "PANEL")) == 4
        assert len(closed_polylines(doc, "COUNTERTOP")) == 1
        assert len(closed_polylines(doc, "PARTITION")) == 0


class TestScenarioRegistry:
    """场景注册表：5 类已知答案场景，供后续 ticket 批量造测试目录。"""

    def test_all_five_scenarios_build(self, tmp_path):
        assert set(fixtures.SCENARIOS) == {
            "wardrobe_2000_baseline",
            "wardrobe_2150_tol_within",
            "wardrobe_2300_tol_beyond",
            "wardrobe_4comp_alt_topology",
            "base_cabinet_800",
        }
        for name in fixtures.SCENARIOS:
            doc = fixtures.build_scenario(name)
            fixtures.save_dxf(doc, tmp_path / f"{name}.dxf")
            assert ezdxf.readfile(tmp_path / f"{name}.dxf") is not None

    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError):
            fixtures.build_scenario("no_such_cabinet")
