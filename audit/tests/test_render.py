"""Tests for cabinet rendering and the occupancy grid (issue #3).

The occupancy-grid test asserts a hand-derived 4x10 known-answer grid for
the baseline wardrobe (2000x2400): cells of 500x240 mm. Grid values come
from the fixture's board layout, worked out on paper, not from the code.
"""

import numpy as np
import pytest

from audit_tool import fixtures
from audit_tool.extract import extract_cabinets
from audit_tool.render import EMPTY, H_BOARD, V_BOARD, occupancy_grid, render_cabinet

E, H, V = EMPTY, H_BOARD, V_BOARD


def baseline_cabinet(tmp_path, name="wardrobe_2000_baseline"):
    path = tmp_path / "cab.dxf"
    fixtures.save_dxf(fixtures.build_scenario(name), path)
    return extract_cabinets(path)[0]


def test_render_produces_fixed_size_grayscale_bitmap(tmp_path):
    cabinet = baseline_cabinet(tmp_path)

    img = render_cabinet(cabinet, size=(128, 128))

    assert img.mode == "L"
    assert img.size == (128, 128)


def test_render_is_white_background_with_dark_lines(tmp_path):
    cabinet = baseline_cabinet(tmp_path)

    img = render_cabinet(cabinet, size=(256, 256))
    pixels = np.asarray(img)

    assert pixels[0, 0] == 255  # white margin
    assert pixels.min() < 128  # drawn geometry present (non-empty render)
    assert (pixels < 128).sum() > 50


def test_render_ignores_annotation_entities(tmp_path):
    # a drawing with only text/annotation geometry renders blank, not crashed
    import ezdxf

    from audit_tool.extract import CabinetFront

    doc = ezdxf.new("R2018", setup=False)
    doc.modelspace().add_text("nothing", dxfattribs={"height": 100}).set_placement((0, 0))
    cabinet = CabinetFront(index=0, bbox=(0.0, 0.0, 100.0, 100.0), entities=())

    img = render_cabinet(cabinet, size=(64, 64))

    assert (np.asarray(img) == 255).all()


def _cabinet(tmp_path, name):
    path = tmp_path / f"{name}.dxf"
    fixtures.save_dxf(fixtures.build_scenario(name), path)
    return extract_cabinets(path)[0]


def test_occupancy_grid_matches_wardrobe_structure(tmp_path):
    # Baseline wardrobe 2000x2400 on a 4x10 grid (cols 500 mm, rows 240 mm),
    # worked out by hand from the fixture board layout, row 0 = bottom:
    #   r0-r1: bottom panel + shelves/rods/drawers -> horizontal cells
    #   r2: top shelves (y 582-600, col 0/3) beat the side panels; compartment
    #       dividers (y 18-600, 50% of r2) hold cols 1-2 vertical
    #   r3-r6: bare side panels only
    #   r7: top/bottom-cabinet divider (y 1782-1800)
    #   r8: top-cabinet door divider (x 1000-1018 -> col 2, y 1800-2382)
    #   r9: top panel
    cabinet = _cabinet(tmp_path, "wardrobe_2000_baseline")

    grid = occupancy_grid(cabinet)

    assert grid.shape == (10, 4)  # [row, col], shape arg is (cols, rows)
    expected = [
        [H, H, H, H],
        [H, H, H, H],
        [H, V, V, H],
        [V, E, E, V],
        [V, E, E, V],
        [V, E, E, V],
        [V, E, E, V],
        [H, H, H, H],
        [V, E, V, V],
        [H, H, H, H],
    ]
    assert grid.tolist() == expected


def test_occupancy_grid_matches_base_cabinet_structure(tmp_path):
    # Base cabinet bbox 840x800 (countertop overhang): cells 210x80 mm.
    # Only outline structure: countertop + carcass top in row 9, bottom panel
    # in row 0, side panels in cols 0/3, interior empty.
    cabinet = _cabinet(tmp_path, "base_cabinet_800")

    grid = occupancy_grid(cabinet)

    expected = [[H, H, H, H]] + [[V, E, E, V]] * 8 + [[H, H, H, H]]
    assert grid.tolist() == expected
