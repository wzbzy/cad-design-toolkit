"""Tests for pHash coarse clustering (issue #4).

Known answers follow issue #1's Testing Decisions: the three width-variant
wardrobes (2000/2150/2300) share one topology and must land in one family;
the 4-compartment variant and the base cabinet must each be their own
family. The default threshold (validated by these tests) is chosen from the
measured fixture distance window: same-topology pairs are at most 26, any
cross-family pair is at least 44.
"""

import itertools
import json

import imagehash
import numpy as np
import pytest

from audit_tool import fixtures
from audit_tool.cluster import (
    DEFAULT_THRESHOLD,
    cluster_hashes,
    pair_key,
    phash_cabinet,
    pairwise_distances,
)
from audit_tool.extract import extract_cabinets

SAME_TOPOLOGY = (
    "wardrobe_2000_baseline",
    "wardrobe_2150_tol_within",
    "wardrobe_2300_tol_beyond",
)
CROSS_FAMILY = ("wardrobe_4comp_alt_topology", "base_cabinet_800")


@pytest.fixture(scope="module")
def hashes(tmp_path_factory):
    """pHash per fixture scenario, extracted and rendered like the pipeline."""
    tmp = tmp_path_factory.mktemp("dxf")
    out = {}
    for name in fixtures.SCENARIOS:
        path = tmp / f"{name}.dxf"
        fixtures.save_dxf(fixtures.build_scenario(name), path)
        out[name] = phash_cabinet(extract_cabinets(path)[0])
    return out


def test_phash_is_deterministic_for_same_input(tmp_path):
    path = tmp_path / "wardrobe.dxf"
    fixtures.save_dxf(fixtures.build_scenario("wardrobe_2000_baseline"), path)
    cabinet = extract_cabinets(path)[0]

    assert phash_cabinet(cabinet) == phash_cabinet(cabinet)


def test_same_topology_pairs_are_closer_than_any_cross_family_pair(hashes):
    distances = pairwise_distances(hashes)

    same = [
        distances[pair_key(a, b)]
        for a, b in itertools.combinations(SAME_TOPOLOGY, 2)
    ]
    cross = [
        distances[pair_key(a, b)]
        for a in SAME_TOPOLOGY
        for b in CROSS_FAMILY
    ]

    assert same and cross
    assert max(same) < min(cross)


def test_default_threshold_groups_fixture_set_into_three_families(hashes):
    families = sorted(
        tuple(f["members"]) for f in cluster_hashes(hashes)["families"]
    )

    assert families == [
        ("base_cabinet_800",),
        ("wardrobe_2000_baseline", "wardrobe_2150_tol_within", "wardrobe_2300_tol_beyond"),
        ("wardrobe_4comp_alt_topology",),
    ]


def test_threshold_is_configurable_merge_all(hashes):
    families = cluster_hashes(hashes, threshold=10_000)["families"]

    assert len(families) == 1
    assert families[0]["members"] == list(hashes)


def test_threshold_zero_separates_all_distinct_hashes(hashes):
    # all five fixture hashes are pairwise distinct (min distance > 0)
    families = cluster_hashes(hashes, threshold=0)["families"]

    assert sorted(f["members"][0] for f in families) == sorted(hashes)


def _hash(bits: str) -> imagehash.ImageHash:
    return imagehash.ImageHash(np.array([c == "1" for c in bits], dtype=bool))


def test_representative_is_member_with_min_average_distance_to_others():
    # known answer, independent of rendering: r is 1 bit from each of
    # a/b/c, while a/b/c are 2 bits from each other, so r's average
    # distance (1) beats every other member's (5/3). Threshold 2 = the
    # family's max pairwise distance, so complete linkage keeps all four.
    fam_hashes = {
        "r": _hash("0000"),
        "a": _hash("0001"),
        "b": _hash("0010"),
        "c": _hash("0100"),
    }

    result = cluster_hashes(fam_hashes, threshold=2)

    assert len(result["families"]) == 1
    family = result["families"][0]
    assert family["members"] == ["r", "a", "b", "c"]
    assert family["representative"] == "r"
    assert family["max_intra_distance"] == 2


def test_single_member_family_represents_itself_with_zero_spread():
    result = cluster_hashes({"x": _hash("0000"), "y": _hash("1111")}, threshold=1)

    by_member = {f["members"][0]: f for f in result["families"]}
    assert by_member["x"]["representative"] == "x"
    assert by_member["x"]["max_intra_distance"] == 0
    assert by_member["y"]["representative"] == "y"
    assert by_member["y"]["max_intra_distance"] == 0


def test_result_is_json_serializable(hashes):
    result = cluster_hashes(hashes)

    restored = json.loads(json.dumps(result))

    assert restored == json.loads(json.dumps(result))
    assert len(restored["families"]) == 3
    assert restored["distances"][pair_key(*SAME_TOPOLOGY[:2])] > 0
