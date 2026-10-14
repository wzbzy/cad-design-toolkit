"""Tests for feature-vector fine grading (issue #5).

Known-answer assertions on the fixture set (issue #1 Testing Decisions):
same topology with width diff 150 -> same parametric grade; width diff 300
-> different grade; 4-compartment variant -> different grade; base cabinet
-> different grade. Tolerances come from the config object, proven by
flipping the 300 case via a widened config.

Features are extracted from the extracted cabinet geometry (issue #3), not
from drawing semantics: topology comes from structural board analysis of
the front view, dimensions from the bbox, layout from the occupancy grid.
"""

import json

import pytest

from audit_tool import fixtures
from audit_tool.extract import extract_cabinets
from audit_tool.grade import (
    DEFAULT_GRADING_CONFIG,
    CabinetFeatures,
    GradingConfig,
    extract_features,
    grade_families,
    same_parametric_grade,
)


def cabinet_of(tmp_path, name):
    path = tmp_path / f"{name}.dxf"
    fixtures.save_dxf(fixtures.build_scenario(name), path)
    return extract_cabinets(path)[0]


def features_of(tmp_path, name, depth=None):
    return extract_features(name, cabinet_of(tmp_path, name), depth=depth)


def test_baseline_wardrobe_topology_and_dimensions(tmp_path):
    feats = features_of(tmp_path, "wardrobe_2000_baseline", depth=600)

    assert feats.has_top_cabinet is True
    assert feats.top_doors == 2
    assert feats.bottom_compartments == 3
    assert feats.width == pytest.approx(2000)
    assert feats.height == pytest.approx(2400)
    assert feats.depth == 600


def test_four_compartment_variant_topology(tmp_path):
    feats = features_of(tmp_path, "wardrobe_4comp_alt_topology")

    assert feats.has_top_cabinet is True
    assert feats.top_doors == 2
    assert feats.bottom_compartments == 4


def test_base_cabinet_has_no_top_cabinet(tmp_path):
    feats = features_of(tmp_path, "base_cabinet_800")

    assert feats.has_top_cabinet is False
    assert feats.top_doors == 0
    assert feats.bottom_compartments == 1
    assert feats.width == pytest.approx(840)  # countertop overhang included
    assert feats.height == pytest.approx(800)


# -- comparison rules (issue #5 deliverable 2) --

NAMES = (
    "wardrobe_2000_baseline",
    "wardrobe_2150_tol_within",
    "wardrobe_2300_tol_beyond",
    "wardrobe_4comp_alt_topology",
    "base_cabinet_800",
)


@pytest.fixture(scope="module")
def scenario_features(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("grade")
    return {name: features_of(tmp_path, name) for name in NAMES}


def test_width_diff_150_same_grade(scenario_features):
    assert same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["wardrobe_2150_tol_within"],
    )


def test_width_diff_300_different_grade(scenario_features):
    assert not same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["wardrobe_2300_tol_beyond"],
    )


def test_four_compartment_variant_different_grade(scenario_features):
    assert not same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["wardrobe_4comp_alt_topology"],
    )


def test_base_cabinet_different_grade(scenario_features):
    assert not same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["base_cabinet_800"],
    )


def test_widened_width_tolerance_flips_300_case(scenario_features):
    # Proves tolerances come from the config object, not hardcoded values:
    # the width-diff-300 pair rejected at the default bin flips to the same
    # grade once the configured bin widens to +-400.
    wide = GradingConfig(width_tolerance=400.0)
    assert not same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["wardrobe_2300_tol_beyond"],
    )  # default config rejects
    assert same_parametric_grade(
        scenario_features["wardrobe_2000_baseline"],
        scenario_features["wardrobe_2300_tol_beyond"],
        config=wide,
    )


def test_default_config_matches_spec_bins():
    # issue #1 L3: width +-200, height +-100, depth +-100.
    assert DEFAULT_GRADING_CONFIG.width_tolerance == 200.0
    assert DEFAULT_GRADING_CONFIG.height_tolerance == 100.0
    assert DEFAULT_GRADING_CONFIG.depth_tolerance == 100.0


# -- family grading: pairwise comparison + transitive closure (deliverable 3) --

def synthetic_features(cabinet_id, width):
    """Same-topology feature vector with a hand-built layout grid."""
    grid = ((1, 1, 1, 1), (2, 0, 0, 2), (1, 1, 1, 1))
    return CabinetFeatures(
        cabinet_id=cabinet_id,
        has_top_cabinet=True,
        top_doors=2,
        bottom_compartments=3,
        width=width,
        height=2400.0,
        depth=None,
        grid=grid,
    )


def test_family_splits_into_grades(scenario_features):
    families = {
        "wardrobes": [
            scenario_features["base_cabinet_800"],
            scenario_features["wardrobe_2150_tol_within"],
            scenario_features["wardrobe_4comp_alt_topology"],
            scenario_features["wardrobe_2000_baseline"],
        ]
    }

    result = grade_families(families)

    grades = result["wardrobes"]["grades"]
    # grades ordered deterministically by their first member id
    assert [g["members"] for g in grades] == [
        ["base_cabinet_800"],
        ["wardrobe_2000_baseline", "wardrobe_2150_tol_within"],
        ["wardrobe_4comp_alt_topology"],
    ]


def test_grading_closes_transitively():
    # A~B (diff 150) and B~C (diff 150) chain into one grade even though
    # A and C themselves differ by 300 (beyond the bin): grades are the
    # transitive closure of pairwise matches, per issue #5.
    a = synthetic_features("a", 2000.0)
    b = synthetic_features("b", 2150.0)
    c = synthetic_features("c", 2300.0)
    assert not same_parametric_grade(a, c)

    result = grade_families({"fam": [c, a, b]})

    assert [g["members"] for g in result["fam"]["grades"]] == [["a", "b", "c"]]


def test_grading_result_is_json_serializable(scenario_features):
    families = {
        "wardrobes": [scenario_features["wardrobe_2000_baseline"]],
        "kitchen": [scenario_features["base_cabinet_800"]],
    }

    result = grade_families(families)

    encoded = json.dumps(result, ensure_ascii=False)
    assert "wardrobe_2000_baseline" in encoded
    assert json.loads(encoded) == result


def test_feature_vectors_are_json_serializable(scenario_features):
    encoded = json.dumps({n: f.to_dict() for n, f in scenario_features.items()})

    assert json.loads(encoded)["wardrobe_2000_baseline"]["bottom_compartments"] == 3
