"""Rendering of extracted cabinet front views (issue #3).

- :func:`render_cabinet` rasterizes one cabinet to a fixed-size grayscale
  bitmap: equal-ratio scale, centered, white background, black lines.
  Line weights, text and dimensions are ignored -- comparison happens on
  rendered geometry only (issue #1).
- :func:`occupancy_grid` reduces the same geometry to a small cell grid
  (default 4x10) with values empty / horizontal board / vertical board,
  for layout IoU in later tickets.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from audit_tool.extract import CabinetFront, _entity_bbox

__all__ = [
    "EMPTY",
    "H_BOARD",
    "V_BOARD",
    "render_cabinet",
    "occupancy_grid",
    "DEFAULT_GRID_SHAPE",
]

DEFAULT_SIZE = (256, 256)
DEFAULT_MARGIN = 8  # pixels kept clear around the drawing
DEFAULT_GRID_SHAPE = (4, 10)  # (cols, rows)

EMPTY = 0
H_BOARD = 1
V_BOARD = 2


def _polyline_paths(cabinet: CabinetFront):
    """Yield drawable paths [(x, y), ...] in drawing coordinates."""
    for e in cabinet.entities:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            pts = [(x, y) for x, y, *_ in e.get_points("xy")]
            if e.closed and len(pts) > 2:
                pts.append(pts[0])
            yield pts
        elif t == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            if e.is_closed and len(pts) > 2:
                pts.append(pts[0])
            yield pts
        elif t == "LINE":
            yield [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        elif t == "CIRCLE":
            yield _arc_points(e.dxf.center.x, e.dxf.center.y, e.dxf.radius, 0.0, 360.0, closed=False)
        elif t == "ARC":
            yield _arc_points(
                e.dxf.center.x,
                e.dxf.center.y,
                e.dxf.radius,
                e.dxf.start_angle,
                e.dxf.end_angle,
            )


def _arc_points(cx, cy, r, start_deg, end_deg, closed=True):
    a0, a1 = math.radians(start_deg), math.radians(end_deg)
    if closed and a1 <= a0:
        a1 += 2 * math.pi
    steps = max(8, int(abs(a1 - a0) / (math.pi / 24)))
    return [
        (cx + r * math.cos(a0 + (a1 - a0) * i / steps),
         cy + r * math.sin(a0 + (a1 - a0) * i / steps))
        for i in range(steps + 1)
    ]


def render_cabinet(cabinet: CabinetFront, size=DEFAULT_SIZE, margin=DEFAULT_MARGIN) -> Image.Image:
    """Rasterize a cabinet front view to a fixed-size grayscale image."""
    x0, y0, x1, y1 = cabinet.bbox
    w = max(x1 - x0, 1e-9)
    h = max(y1 - y0, 1e-9)
    scale = min((size[0] - 2 * margin) / w, (size[1] - 2 * margin) / h)

    def to_px(pt):
        px = margin + (pt[0] - x0) * scale + (size[0] - 2 * margin - w * scale) / 2
        py = size[1] - (margin + (pt[1] - y0) * scale + (size[1] - 2 * margin - h * scale) / 2)
        return (px, py)

    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for path in _polyline_paths(cabinet):
        if len(path) > 1:
            draw.line([to_px(p) for p in path], fill=0, width=1)
    return img
