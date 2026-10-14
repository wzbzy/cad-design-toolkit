"""Front-view extraction: split a DXF sheet into unit cabinets (issue #3).

No layer or viewport conventions are assumed (store drawings are wildly
inconsistent). The front view is the horizontally arranged drawing region:
all 2D geometry in modelspace is projected onto the x axis, contiguous
x-intervals are merged, and each merged interval is one cabinet region.
Boards span their cabinet's full width, so interior partitions never create
a full-height x gap; only true gaps between cabinets do.

Text, dimensions and other annotations are ignored throughout -- the
render+hash route deliberately bypasses drawing semantics (issue #1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf
from ezdxf import bbox

__all__ = ["CabinetFront", "extract_cabinets", "load_geometry"]

# Entity types treated as drawing geometry. Everything else (TEXT, MTEXT,
# DIMENSION, ...) is annotation and ignored.
GEOMETRY_DXFTYPES = frozenset(
    {"LWPOLYLINE", "POLYLINE", "LINE", "CIRCLE", "ARC", "ELLIPSE", "SPLINE"}
)

# x-intervals closer than this are considered part of the same cabinet.
_MERGE_EPS = 1e-6


@dataclass(frozen=True)
class CabinetFront:
    """One unit cabinet extracted from a sheet: bbox and its geometry."""

    index: int  # left-to-right position on the sheet
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (drawing mm)
    entities: tuple  # ezdxf entities whose geometry falls in this region


def load_geometry(dxf_path):
    """Read a DXF and return its modelspace geometry entities.

    Goes through the conversion seam indirectly: callers pass a path that
    an adapter (:mod:`audit_tool.converters`) has already resolved to DXF.
    """
    doc = ezdxf.readfile(str(dxf_path))
    entities = []
    for e in doc.modelspace():
        if e.dxftype() not in GEOMETRY_DXFTYPES:
            continue
        extent = bbox.extents([e], fast=True)
        if extent.has_data:
            entities.append(e)
    return entities


def _entity_bbox(entity) -> tuple[float, float, float, float]:
    extent = bbox.extents([entity], fast=True)
    return extent.extmin.x, extent.extmin.y, extent.extmax.x, extent.extmax.y


def extract_cabinets(dxf_path) -> list[CabinetFront]:
    """Split a DXF sheet into unit cabinets, left to right.

    Returns one :class:`CabinetFront` per merged x-interval; an empty
    drawing yields an empty list.
    """
    entities = load_geometry(dxf_path)
    if not entities:
        return []

    boxes = [_entity_bbox(e) for e in entities]
    order = sorted(range(len(entities)), key=lambda i: boxes[i][0])

    cabinets: list[CabinetFront] = []
    cluster: list[int] = []
    cluster_x1 = -float("inf")
    for i in order:
        x0, _, x1, _ = boxes[i]
        if cluster and x0 > cluster_x1 + _MERGE_EPS:
            cabinets.append(_make_cabinet(len(cabinets), cluster, entities, boxes))
            cluster = []
        cluster.append(i)
        cluster_x1 = max(cluster_x1, x1)
    if cluster:
        cabinets.append(_make_cabinet(len(cabinets), cluster, entities, boxes))
    return cabinets


def _make_cabinet(index, members, entities, boxes) -> CabinetFront:
    xs0 = min(boxes[i][0] for i in members)
    ys0 = min(boxes[i][1] for i in members)
    xs1 = max(boxes[i][2] for i in members)
    ys1 = max(boxes[i][3] for i in members)
    return CabinetFront(
        index=index,
        bbox=(xs0, ys0, xs1, ys1),
        entities=tuple(entities[i] for i in members),
    )
