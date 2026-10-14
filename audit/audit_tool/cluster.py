"""Perceptual-hash coarse clustering of cabinet renderings (issue #4).

Pipeline stage: rendered cabinet fronts -> pHash -> hamming distance
matrix -> greedy complete-linkage clustering -> shape families. Purpose:
collapse hundreds of unit cabinets into tens of families for the fine
grading of issue #5 and the report of issue #6.

Determinism: fixed dict iteration order everywhere, no randomized
initialization -- same input, same output.
"""

from __future__ import annotations

import imagehash
from PIL import Image

from audit_tool.extract import CabinetFront
from audit_tool.render import render_cabinet

__all__ = [
    "RENDER_SIZE",
    "DEFAULT_HASH_SIZE",
    "DEFAULT_THRESHOLD",
    "pair_key",
    "phash_image",
    "phash_cabinet",
    "pairwise_distances",
    "cluster_hashes",
]

# 512 px keeps thin boards resolvable after the DCT downscale; 256 px washes
# the 4-compartment fixture into the 3-compartment topology.
RENDER_SIZE = (512, 512)
# 144-bit hash. The textbook 8x8 (64-bit) pHash scores the 2300-wide
# baseline variant farther from the 2000 baseline (10) than the 4-compartment
# topology (8); hash_size >= 10 separates them with a usable margin.
DEFAULT_HASH_SIZE = 12
# Hamming-distance threshold (of 144 bits). Fixture-set window: same-topology
# pairs measure <= 26, cross-family pairs >= 44; 32 sits mid-window.
DEFAULT_THRESHOLD = 32


def pair_key(a: str, b: str) -> str:
    """Canonical JSON-safe key for one pair of cabinet ids ("min|max")."""
    return f"{a}|{b}" if a <= b else f"{b}|{a}"


def phash_image(img: Image.Image, hash_size: int = DEFAULT_HASH_SIZE) -> imagehash.ImageHash:
    """Compute the pHash of a rendered cabinet image."""
    return imagehash.phash(img, hash_size=hash_size)


def phash_cabinet(cabinet: CabinetFront, hash_size: int = DEFAULT_HASH_SIZE) -> imagehash.ImageHash:
    """Render one extracted cabinet and hash it (deterministic)."""
    return phash_image(render_cabinet(cabinet, size=RENDER_SIZE), hash_size=hash_size)


def pairwise_distances(hashes: dict[str, imagehash.ImageHash]) -> dict[str, int]:
    """Hamming distance matrix as a flat dict keyed by :func:`pair_key`.

    Self-distances (always 0) are omitted; iteration order follows the
    input dict order, so the serialization is stable.
    """
    names = list(hashes)
    return {
        pair_key(a, b): int(hashes[a] - hashes[b])  # plain int: JSON-safe
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    }


def cluster_hashes(
    hashes: dict[str, imagehash.ImageHash], threshold: int = DEFAULT_THRESHOLD
) -> dict:
    """Greedy complete-linkage clustering over pHash hamming distances.

    Cabinets are visited in input dict order; a cabinet joins the first
    family it is within ``threshold`` of every member of, otherwise it
    opens a new family. Complete linkage keeps every family's internal
    max distance at or below ``threshold``. Deterministic: same input
    order, same output.

    Returns a JSON-serializable dict: threshold/hash provenance, the
    family list (members, representative, max intra-family distance) and
    the full distance matrix for downstream tickets and audit trail.
    """
    distances = pairwise_distances(hashes)
    families: list[list[str]] = []
    for name in hashes:
        for family in families:
            if all(distances[pair_key(name, m)] <= threshold for m in family):
                family.append(name)
                break
        else:
            families.append([name])

    return {
        "algorithm": "phash-complete-linkage",
        "threshold": threshold,
        "hash_bits": len(next(iter(hashes.values())).hash.ravel()) if hashes else 0,
        "families": [
            _family_dict(i, members, distances) for i, members in enumerate(families)
        ],
        "distances": distances,
    }


def _family_dict(family_id: int, members: list[str], distances: dict[str, int]) -> dict:
    """One family: members, representative (min average distance to the
    other members, earliest member wins ties) and the max intra-family
    distance (0 for a single-member family)."""
    spread = {m: [distances[pair_key(m, o)] for o in members if o != m] for m in members}
    representative = min(members, key=lambda m: sum(spread[m]) / len(members))
    return {
        "id": family_id,
        "members": members,
        "representative": representative,
        "max_intra_distance": max((max(d) for d in spread.values() if d), default=0),
    }
