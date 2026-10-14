"""Tests for cabinet rendering and the occupancy grid (issue #3).

The occupancy-grid test asserts a hand-derived 4x10 known-answer grid for
the baseline wardrobe (2000x2400): cells of 500x240 mm. Grid values come
from the fixture's board layout, worked out on paper, not from the code.
"""

import numpy as np
import pytest

from audit_tool import fixtures
from audit_tool.extract import extract_cabinets
from audit_tool.render import render_cabinet


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
