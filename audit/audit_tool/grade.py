"""Structural feature-vector fine grading within clusters (issue #5).

Inside each coarse cluster ("family", from issue #4) cabinets are compared
field by field to split them into parametric grades (参数档): cabinets that
are identical in structure and within dimensional bin tolerances are
assumed reproducible from one template by parameter adjustment alone.

- :func:`extract_features` reduces an extracted cabinet front (issue #3)
  to a structural feature vector: topology fields (top-cabinet presence,
  top-cabinet door count, bottom-cabinet compartment count), dimension
  fields (width / height / depth) and the occupancy layout grid.
  Topology is derived from the geometry's board structure only -- no layer
  or block semantics (store drawings are inconsistent, issue #1).
- :func:`same_parametric_grade` compares two feature vectors: topology
  fields must match exactly, dimensions must fall within the configured
  bin tolerances (:class:`GradingConfig`, never hardcoded), and the
  occupancy grids must overlap at least at the configured IoU threshold
  (layout fallback for structure the coarse fields cannot see).
- :func:`grade_families` grades each family by pairwise comparison plus
  transitive closure (union-find) and returns a JSON-serializable
  ``family -> grades -> member cabinet ids`` structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from audit_tool.extract import CabinetFront, _entity_bbox
from audit_tool.render import DEFAULT_GRID_SHAPE, occupancy_grid

__all__ = [
    "GradingConfig",
    "DEFAULT_GRADING_CONFIG",
    "CabinetFeatures",
    "extract_features",
    "grid_iou",
    "same_parametric_grade",
    "grade_family",
    "grade_families",
]


@dataclass(frozen=True)
class GradingConfig:
    """Fine-grading tolerances (issue #1: config object, not hardcoded).

    Dimension fields match when the absolute difference is within the
    tolerance; L3 default bins: width +-200, height +-100, depth +-100.
    Layout grids match when their occupancy IoU reaches the threshold.
    """

    width_tolerance: float = 200.0
    height_tolerance: float = 100.0
    depth_tolerance: float = 100.0
    grid_iou_threshold: float = 0.85


DEFAULT_GRADING_CONFIG = GradingConfig()


@dataclass(frozen=True)
class CabinetFeatures:
    """Structural feature vector of one unit cabinet (issue #5 deliverable 1)."""

    cabinet_id: str
    # topology fields -- must match exactly between grades
    has_top_cabinet: bool
    top_doors: int
    bottom_compartments: int
    # dimension fields -- compared with binned tolerances
    width: float
    height: float
    depth: float | None
    # layout grid, [row][col] row 0 = bottom, values from render (0/1/2)
    grid: tuple[tuple[int, ...], ...] = field(repr=False)

    def to_dict(self) -> dict:
        """JSON-serializable form of the feature vector."""
        return {
            "cabinet_id": self.cabinet_id,
            "has_top_cabinet": self.has_top_cabinet,
            "top_doors": self.top_doors,
            "bottom_compartments": self.bottom_compartments,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "grid": [list(row) for row in self.grid],
        }


# A divider must sit this far (as a fraction of the carcass width, i.e. the
# span of the vertical boards) inside it to count as interior -- excludes the
# carcass side panels.
_EDGE_MARGIN_FRACTION = 0.02

# Two interior vertical boards belong to the same structural section when
# their vertical extents start within this fraction of cabinet height.
_SECTION_TOLERANCE_FRACTION = 0.05


def extract_features(
    cabinet_id: str,
    cabinet: CabinetFront,
    depth: float | None = None,
    grid_shape=DEFAULT_GRID_SHAPE,
) -> CabinetFeatures:
    """Extract the structural feature vector from one cabinet front.

    ``depth`` cannot be seen in a front view; callers pass it when known
    (drawing metadata), otherwise it stays ``None`` and is ignored in
    comparisons.
    """
    x0, y0, x1, y1 = cabinet.bbox
    rects = [_entity_bbox(e) for e in cabinet.entities]
    sections = _divider_sections(rects, cabinet.bbox)

    bottom = sections[0] if sections else None
    top = sections[-1] if len(sections) > 1 else None

    return CabinetFeatures(
        cabinet_id=cabinet_id,
        has_top_cabinet=top is not None,
        top_doors=len(top) + 1 if top is not None else 0,
        bottom_compartments=len(bottom) + 1 if bottom is not None else 1,
        width=x1 - x0,
        height=y1 - y0,
        depth=depth,
        grid=tuple(tuple(int(v) for v in row) for row in occupancy_grid(cabinet, grid_shape)),
    )


def grid_iou(grid_a, grid_b) -> float:
    """Occupancy IoU of two layout grids: cells occupied (non-empty) in
    both over cells occupied in either. Two empty grids count as identical.
    """
    mask_a = [v != 0 for row in grid_a for v in row]
    mask_b = [v != 0 for row in grid_b for v in row]
    union = sum(a or b for a, b in zip(mask_a, mask_b))
    if union == 0:
        return 1.0
    inter = sum(a and b for a, b in zip(mask_a, mask_b))
    return inter / union


def same_parametric_grade(
    a: CabinetFeatures, b: CabinetFeatures, config: GradingConfig = DEFAULT_GRADING_CONFIG
) -> bool:
    """True when ``a`` and ``b`` can come from one template by parameter
    adjustment alone (issue #1 L2+L3).

    Topology fields must be exactly equal; each dimension field must fall
    within its configured bin tolerance (unknown depth, ``None``, is not
    compared); the layout grids must overlap at least at the configured
    IoU threshold.
    """
    if (a.has_top_cabinet, a.top_doors, a.bottom_compartments) != (
        b.has_top_cabinet,
        b.top_doors,
        b.bottom_compartments,
    ):
        return False
    if abs(a.width - b.width) > config.width_tolerance:
        return False
    if abs(a.height - b.height) > config.height_tolerance:
        return False
    if a.depth is not None and b.depth is not None:
        if abs(a.depth - b.depth) > config.depth_tolerance:
            return False
    return grid_iou(a.grid, b.grid) >= config.grid_iou_threshold


def grade_family(
    members: list[CabinetFeatures], config: GradingConfig = DEFAULT_GRADING_CONFIG
) -> list[list[CabinetFeatures]]:
    """Split one family's cabinets into parametric grades.

    Grades are the transitive closure of pairwise
    :func:`same_parametric_grade` matches (union-find): cabinets linked
    directly or through a chain of matches share a grade. Deterministic:
    members are ordered by ``cabinet_id`` within a grade, grades by their
    first member.
    """
    parent = list(range(len(members)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if same_parametric_grade(members[i], members[j], config):
                parent[find(i)] = find(j)

    groups: dict[int, list[CabinetFeatures]] = {}
    for i, feats in enumerate(members):
        groups.setdefault(find(i), []).append(feats)

    ordered = sorted(
        (sorted(g, key=lambda f: f.cabinet_id) for g in groups.values()),
        key=lambda g: g[0].cabinet_id,
    )
    return ordered


def grade_families(
    families: dict[str, list[CabinetFeatures]],
    config: GradingConfig = DEFAULT_GRADING_CONFIG,
) -> dict:
    """Grade every family; returns a JSON-serializable structure:

    ``{family_id: {"grades": [{"grade": "<family>#g<k>", "members": [ids]}]}}``
    """
    result = {}
    for family_id, members in families.items():
        result[family_id] = {
            "grades": [
                {"grade": f"{family_id}#g{k}", "members": [f.cabinet_id for f in group]}
                for k, group in enumerate(grade_family(members, config))
            ]
        }
    return result


def _divider_sections(rects, bbox) -> list[list[tuple[float, float, float, float]]]:
    """Group interior vertical dividers into structural sections.

    Dividers sharing (approximately) the same vertical extent belong to one
    section -- e.g. the compartment splits of the bottom cabinet, or the
    door splits of the top cabinet. Sections are returned bottom-up.

    The carcass side panels are excluded as the extreme vertical boards:
    the edge margin is measured from the span of the vertical boards, not
    the bbox, so countertop overhangs cannot push panels into "interior".
    """
    h = bbox[3] - bbox[1]
    tol = _SECTION_TOLERANCE_FRACTION * h

    vertical = [r for r in rects if (r[3] - r[1]) > (r[2] - r[0])]
    if not vertical:
        return []
    span = max(r[2] for r in vertical) - min(r[0] for r in vertical)
    margin = _EDGE_MARGIN_FRACTION * span
    left_limit = min(r[0] for r in vertical) + margin
    right_limit = max(r[2] for r in vertical) - margin

    dividers = [r for r in vertical if r[0] > left_limit and r[2] < right_limit]
    dividers.sort(key=lambda r: r[1])

    sections: list[list[tuple[float, float, float, float]]] = []
    for r in dividers:
        if sections and abs(r[1] - sections[-1][0][1]) <= tol:
            sections[-1].append(r)
        else:
            sections.append([r])
    return sections
