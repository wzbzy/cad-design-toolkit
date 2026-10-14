"""Known-answer DXF fixture builder for the similarity audit test suite.

Constructs unit-cabinet front views programmatically with ezdxf. Every
board/element is drawn as a closed LWPOLYLINE rectangle on a role layer:

- ``PANEL``     carcass panels (left / right / top / bottom)
- ``PARTITION`` vertical splits (top-cabinet doors, bottom-cabinet compartments)
                and the horizontal top/bottom cabinet divider
- ``SHELF``     horizontal shelf boards
- ``ROD``       hanging rods
- ``DRAWER``    drawer fronts
- ``COUNTERTOP`` countertop slab (base cabinets)

Coordinate system: front view, origin at the cabinet's bottom-left outer
corner, x to the right, y up, millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass

import ezdxf

BOARD = 18  # common board thickness, mm

LAYER_PANEL = "PANEL"
LAYER_PARTITION = "PARTITION"
LAYER_SHELF = "SHELF"
LAYER_ROD = "ROD"
LAYER_DRAWER = "DRAWER"
LAYER_COUNTERTOP = "COUNTERTOP"


@dataclass(frozen=True)
class CompartmentLayout:
    """Internal layout of one bottom-cabinet compartment (top to bottom:
    shelves first, then drawers, then rods in the remaining middle zones)."""

    shelves: int = 0
    drawers: int = 0
    rods: int = 0


BASELINE_COMPARTMENTS = (
    CompartmentLayout(shelves=4),  # 左层板x4
    CompartmentLayout(rods=2),  # 中双衣通
    CompartmentLayout(shelves=2, drawers=2),  # 右上层板x2+下抽屉x2
)


def _new_doc() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=False)
    for layer in (
        LAYER_PANEL,
        LAYER_PARTITION,
        LAYER_SHELF,
        LAYER_ROD,
        LAYER_DRAWER,
        LAYER_COUNTERTOP,
    ):
        doc.layers.add(name=layer)
    return doc


def _rect(doc, layer: str, x: float, y: float, w: float, h: float) -> None:
    """Add a closed LWPOLYLINE rectangle (w x h) with lower-left corner at (x, y)."""
    doc.modelspace().add_lwpolyline(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
        format="xy",
        dxfattribs={"layer": layer},
    ).closed = True


def build_wardrobe(
    width: float = 2000,
    height: float = 2400,
    depth: float = 600,
    top_height: float = 600,
    top_doors: int = 2,
    compartment_layouts: tuple[CompartmentLayout, ...] = BASELINE_COMPARTMENTS,
) -> ezdxf.document.Drawing:
    """Build a sliding-door wardrobe front view.

    ``depth`` is accepted so scenario tables stay uniform across cabinet
    kinds; the front view does not encode it.

    ``top_height`` is the top-cabinet (顶柜) height; the rest is the bottom
    cabinet (下柜), split into ``len(compartment_layouts)`` compartments.
    """
    if width <= 2 * BOARD or height <= top_height + 2 * BOARD:
        raise ValueError("cabinet too small for its boards")
    if top_doors < 1 or not compartment_layouts:
        raise ValueError("need at least one top door and one compartment")

    doc = _new_doc()

    # carcass: left / right / top / bottom panels
    _rect(doc, LAYER_PANEL, 0, 0, BOARD, height)
    _rect(doc, LAYER_PANEL, width - BOARD, 0, BOARD, height)
    _rect(doc, LAYER_PANEL, 0, height - BOARD, width, BOARD)
    _rect(doc, LAYER_PANEL, 0, 0, width, BOARD)

    # horizontal divider between top and bottom cabinet
    bottom_top = height - top_height  # y of the bottom cabinet's top edge
    _rect(doc, LAYER_PARTITION, BOARD, bottom_top - BOARD, width - 2 * BOARD, BOARD)

    # top cabinet: vertical door dividers
    inner_w = width - 2 * BOARD
    top_inner_h = top_height - BOARD
    for i in range(1, top_doors):
        x = BOARD + inner_w * i / top_doors
        _rect(doc, LAYER_PARTITION, x, bottom_top, BOARD, top_inner_h)

    # bottom cabinet: vertical compartment dividers + per-compartment layout
    bottom_inner_h = top_height - BOARD
    n = len(compartment_layouts)
    comp_w = (inner_w - (n - 1) * BOARD) / n
    for i in range(1, n):
        x = BOARD + comp_w * i + BOARD * (i - 1)
        _rect(doc, LAYER_PARTITION, x, BOARD, BOARD, bottom_inner_h)
    for i, layout in enumerate(compartment_layouts):
        x0 = BOARD + (comp_w + BOARD) * i
        _build_compartment(doc, x0, BOARD, comp_w, bottom_inner_h, layout)

    return doc


def _build_compartment(
    doc, x0: float, y0: float, w: float, h: float, layout: CompartmentLayout
) -> None:
    """Fill a compartment interior (top-down: shelves, drawers, rods zones)."""
    units = layout.shelves + layout.drawers + layout.rods
    if units == 0:
        return
    zone_h = h / units
    y = y0 + h  # top of the compartment interior
    for _ in range(layout.shelves):
        y -= zone_h
        _rect(doc, LAYER_SHELF, x0, y + zone_h - BOARD, w, BOARD)
    for _ in range(layout.drawers):
        y -= zone_h
        _rect(doc, LAYER_DRAWER, x0, y, w, zone_h - BOARD)
    for _ in range(layout.rods):
        y -= zone_h
        _rect(doc, LAYER_ROD, x0, y + (zone_h - BOARD) / 2, w, BOARD)


def build_base_cabinet(
    width: float = 800,
    height: float = 800,
    depth: float = 580,
    countertop_thickness: float = 40,
    countertop_overhang: float = 20,
    compartments: int = 0,
) -> ezdxf.document.Drawing:
    """Build a 地柜橱柜 (base cabinet with countertop) front view.

    The countertop overhangs ``countertop_overhang`` on each side, so the
    drawing's bounding box is ``(width + 2*overhang) x height``.
    """
    if width <= 2 * countertop_overhang or height <= countertop_thickness + 2 * BOARD:
        raise ValueError("base cabinet too small for its boards")
    if compartments < 0:
        raise ValueError("compartments must be >= 0")

    doc = _new_doc()
    carcass_h = height - countertop_thickness

    # carcass
    _rect(doc, LAYER_PANEL, 0, 0, width, carcass_h)
    _rect(doc, LAYER_PANEL, 0, 0, BOARD, carcass_h)
    _rect(doc, LAYER_PANEL, width - BOARD, 0, BOARD, carcass_h)
    _rect(doc, LAYER_PANEL, 0, 0, width, BOARD)
    _rect(doc, LAYER_PANEL, 0, carcass_h - BOARD, width, BOARD)

    # countertop slab, overhanging on both sides
    _rect(
        doc,
        LAYER_COUNTERTOP,
        -countertop_overhang,
        carcass_h,
        width + 2 * countertop_overhang,
        countertop_thickness,
    )

    # optional vertical compartment dividers
    inner_w = width - 2 * BOARD
    inner_h = carcass_h - 2 * BOARD
    for i in range(1, compartments):
        x = BOARD + inner_w * i / compartments
        _rect(doc, LAYER_PARTITION, x, BOARD, BOARD, inner_h)

    return doc


def save_dxf(doc: ezdxf.document.Drawing, path) -> None:
    """Save a fixture drawing to ``path`` (str or pathlib.Path)."""
    doc.saveas(str(path))


# Known-answer scenarios for the similarity audit (issue #1 Testing Decisions).
# Each entry returns a fresh drawing; later tickets batch-generate test
# directories from these.
SCENARIOS = {
    # 移门衣柜基准 2000x2400
    "wardrobe_2000_baseline": lambda: build_wardrobe(),
    # 同拓扑，宽 +150（L3 容差内）
    "wardrobe_2150_tol_within": lambda: build_wardrobe(width=2150),
    # 同拓扑，宽 +300（L3 容差外）
    "wardrobe_2300_tol_beyond": lambda: build_wardrobe(width=2300),
    # 异拓扑：下柜 4 分区
    "wardrobe_4comp_alt_topology": lambda: build_wardrobe(
        compartment_layouts=(
            CompartmentLayout(shelves=4),
            CompartmentLayout(rods=2),
            CompartmentLayout(drawers=3),
            CompartmentLayout(shelves=1, drawers=2),
        )
    ),
    # 异品类：地柜橱柜 800x800 台面结构
    "base_cabinet_800": lambda: build_base_cabinet(),
}


def build_scenario(name: str) -> ezdxf.document.Drawing:
    """Build one known-answer scenario drawing by name."""
    try:
        return SCENARIOS[name]()
    except KeyError:
        raise ValueError(f"unknown scenario {name!r}; known: {sorted(SCENARIOS)}") from None
