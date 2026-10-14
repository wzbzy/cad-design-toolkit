"""Tests for audit report generation (issue #6).

The seam under test is the report library surface: pipeline result dicts
(coarse clusters from issue #4, extracted cabinets from issue #3) go in,
``report.json`` / ``report.md`` artifacts come out.

Known-answer assertions run against directories of fixture DXFs (issue #1
Testing Decisions): a directory of mutually-similar wardrobes must yield
100% cabinet-level parametric coverage; adding outlier cabinets must lower
it to exactly computable values; the three verdict levels (>=70% pass,
40-70% conditional, <40% fail, thresholds from config) must each be
reachable by a fixture group.
"""

import json

import pytest

from audit_tool import fixtures
from audit_tool.cluster import cluster_hashes, phash_cabinet
from audit_tool.extract import extract_cabinets
from audit_tool.grade import extract_features
from audit_tool.report import (
    DEFAULT_REPORT_CONFIG,
    ReportConfig,
    build_report,
    write_report,
)


def make_drawing(tmp_path, directory, order_no, scenario=None, builder=None):
    """Write one fixture DXF (one unit cabinet) named after the order no."""
    d = tmp_path / directory
    d.mkdir(parents=True, exist_ok=True)
    doc = builder() if builder is not None else fixtures.build_scenario(scenario)
    fixtures.save_dxf(doc, d / f"{order_no}.dxf")


def audit_directories(tmp_path, *directories):
    """Run extract -> hash -> cluster over one or more fixture directories.

    Clustering spans all directories (as the real pipeline does). Returns
    (cluster dict, features by cabinet id, sources by cabinet id) --
    exactly what the report seam consumes.
    """
    fronts = {}
    sources = {}
    for directory in directories:
        for path in sorted((tmp_path / directory).glob("*.dxf")):
            for cabinet in extract_cabinets(path):
                cabinet_id = f"{path.stem}#{cabinet.index}"
                fronts[cabinet_id] = cabinet
                sources[cabinet_id] = {
                    "order_no": path.stem,
                    "drawing": f"{directory}/{path.name}",
                    "directory": directory,
                }
    cluster = cluster_hashes({cid: phash_cabinet(c) for cid, c in fronts.items()})
    features = {cid: extract_features(cid, c) for cid, c in fronts.items()}
    return cluster, features, sources


def audit_directory(tmp_path, directory):
    """Audit a single fixture directory."""
    return audit_directories(tmp_path, directory)


# -- coverage: exact values on partially-outlier fixture groups --

def test_similar_wardrobes_only_yield_full_coverage(tmp_path):
    # 5 mutually-similar wardrobes (2000 x3, 2150 x2; width diff 150 is
    # inside the +-200 bin) -> one family, one grade -> 100% covered.
    for i in range(3):
        make_drawing(tmp_path, "jan", f"SD2601-{i:03d}", "wardrobe_2000_baseline")
    for i in range(2):
        make_drawing(tmp_path, "jan", f"SD2601-1{i:02d}", "wardrobe_2150_tol_within")

    cluster, features, sources = audit_directory(tmp_path, "jan")
    report = build_report(cluster, features, sources)

    assert report["totals"] == {
        "cabinets": 5,
        "families": 1,
        "grades": 1,
        "covered_cabinets": 5,
        "uncovered_cabinets": 0,
    }
    assert report["coverage"]["ratio_pct"] == 100.0


def test_outlier_cabinets_lower_coverage_to_exact_value(tmp_path):
    # 3 covered wardrobes (2x baseline + 1x 2150) + 2 outliers (4-compartment
    # variant, base cabinet: different topology -> singleton grades).
    # Coverage = 3/5 = 60%.
    make_drawing(tmp_path, "jan", "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "SD2601-001", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "SD2601-002", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "jan", "SD2601-003", "wardrobe_4comp_alt_topology")
    make_drawing(tmp_path, "jan", "SD2601-004", "base_cabinet_800")

    cluster, features, sources = audit_directory(tmp_path, "jan")
    report = build_report(cluster, features, sources)

    assert report["totals"]["cabinets"] == 5
    assert report["totals"]["covered_cabinets"] == 3
    assert report["coverage"]["ratio_pct"] == pytest.approx(60.0)


def test_coverage_ratio_rounds_to_two_decimals(tmp_path):
    # 1 covered pair (baseline + 2150) + 3 structurally distinct outliers
    # (identical copies would share a grade and cover each other) -> 40.0%.
    make_drawing(tmp_path, "jan", "A", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "B", "wardrobe_2150_tol_within")
    for stem, comps in (("C", 2), ("D", 3), ("E", 4)):
        make_drawing(
            tmp_path, "jan", stem,
            builder=lambda comps=comps: fixtures.build_base_cabinet(compartments=comps),
        )

    cluster, features, sources = audit_directory(tmp_path, "jan")
    report = build_report(cluster, features, sources)

    assert report["coverage"]["ratio_pct"] == 40.0


def test_transitive_chain_grade_is_not_covered(tmp_path):
    # Grades are transitive closures: baseline ~ (+150) ~ 2150 ~ (+150) ~ 2300
    # chains into ONE grade whose max width spread (300) exceeds the +-200
    # bin -- the grade is not a parametric grade, so none of its members
    # count as covered (issue #6: 落入参数档且档内最大尺寸差在容差内).
    make_drawing(tmp_path, "jan", "A", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "B", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "jan", "C", "wardrobe_2300_tol_beyond")

    cluster, features, sources = audit_directory(tmp_path, "jan")
    report = build_report(cluster, features, sources)

    assert report["totals"]["grades"] == 1
    assert report["totals"]["covered_cabinets"] == 0
    assert report["coverage"]["ratio_pct"] == 0.0


# -- three verdict levels, thresholds from config --

def test_verdict_levels_are_reachable_by_fixture_groups(tmp_path):
    groups = {
        # 80% >= 70 -> 成立
        "high": [("wardrobe_2000_baseline", 2), ("wardrobe_2150_tol_within", 2),
                 ("base_cabinet_800", 1)],
        # 60% in [40, 70) -> 条件成立
        "mid": [("wardrobe_2000_baseline", 2), ("wardrobe_2150_tol_within", 1),
                ("base_cabinet_800", 1), ("wardrobe_4comp_alt_topology", 1)],
        # 0% < 40 -> 不成立
        "low": [("wardrobe_2000_baseline", 1), ("base_cabinet_800", 1)],
    }
    for name, specs in groups.items():
        (tmp_path / name).mkdir()
        n = 0
        for scenario, count in specs:
            for _ in range(count):
                make_drawing(tmp_path, name, f"SD-{n:03d}", scenario)
                n += 1
        # pad the low group with distinct base-cabinet variants (all uncovered)
        if name == "low":
            for comps in (2, 3):
                make_drawing(
                    tmp_path, name, f"SD-{n:03d}",
                    builder=lambda comps=comps: fixtures.build_base_cabinet(compartments=comps),
                )
                n += 1

    levels = {}
    for name in groups:
        cluster, features, sources = audit_directory(tmp_path, name)
        report = build_report(cluster, features, sources)
        levels[name] = report["verdict"]

    assert levels["high"]["level"] == "pass"
    assert levels["high"]["conclusion"] == "成立"
    assert levels["mid"]["level"] == "conditional"
    assert levels["mid"]["conclusion"] == "条件成立"
    assert levels["low"]["level"] == "fail"
    assert levels["low"]["conclusion"] == "不成立"
    assert levels["high"]["coverage_pct"] == 80.0


def test_verdict_thresholds_come_from_config(tmp_path):
    # One 4/5 = 80% group flips through all three levels as the configured
    # thresholds move -- proving the defaults are not hardcoded.
    for i in range(2):
        make_drawing(tmp_path, "jan", f"A{i}", "wardrobe_2000_baseline")
    for i in range(2):
        make_drawing(tmp_path, "jan", f"B{i}", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "jan", "C", "base_cabinet_800")

    cluster, features, sources = audit_directory(tmp_path, "jan")
    pct = 80.0

    assert build_report(cluster, features, sources)["verdict"]["level"] == "pass"
    stricter = ReportConfig(pass_threshold=85.0, conditional_threshold=50.0)
    assert build_report(cluster, features, sources, config=stricter)["verdict"]["level"] == "conditional"
    strictest = ReportConfig(pass_threshold=85.0, conditional_threshold=85.0)
    assert build_report(cluster, features, sources, config=strictest)["verdict"]["level"] == "fail"
    assert pct == pytest.approx(80.0)  # the group's exact coverage


def test_default_verdict_thresholds_match_spec():
    # issue #1 判定标准: >=70% 成立, 40%-70% 条件成立, <40% 不成立.
    assert DEFAULT_REPORT_CONFIG.pass_threshold == 70.0
    assert DEFAULT_REPORT_CONFIG.conditional_threshold == 40.0


# -- Top-N curve: families by member count desc -> cumulative coverage --

@pytest.fixture(scope="module")
def topn_report(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("topn")
    # wardrobe family of 3 (covered), 4-comp family of 1, base family of 1.
    make_drawing(tmp_path, "jan", "A0", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "A1", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "A2", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "jan", "B0", "wardrobe_4comp_alt_topology")
    make_drawing(tmp_path, "jan", "C0", "base_cabinet_800")
    cluster, features, sources = audit_directory(tmp_path, "jan")
    return build_report(cluster, features, sources)


def test_top_n_curve_families_sorted_by_member_count_desc(topn_report):
    counts = [row["families"] for row in topn_report["top_n"]]
    assert counts == [1, 2, 3]
    assert topn_report["top_n"][0]["family_ids"] == ["f0"]  # the 3-member family


def test_top_n_curve_cumulative_coverage(topn_report):
    rows = topn_report["top_n"]
    # top-1: the 3-wardrobe family -> 3/5 cabinets, 3/5 covered
    assert rows[0]["cabinets"] == 3
    assert rows[0]["covered"] == 3
    assert rows[0]["coverage_pct"] == 60.0
    # top-3 (all families) equals the overall totals
    assert rows[-1]["cabinets"] == 5
    assert rows[-1]["covered"] == 3
    assert rows[-1]["coverage_pct"] == 60.0
    assert set(rows[-1]["family_ids"]) == {"f0", "f1", "f2"}


# -- monthly grouping: per source directory (跨月对比) --

def test_monthly_grouping_by_source_directory(tmp_path):
    # jan: 2 covered wardrobes (100%); feb: 1 covered wardrobe + 1 outlier
    # (50%) -> per-directory rows plus overall union (75%).
    make_drawing(tmp_path, "2026-01", "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "2026-01", "SD2601-001", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "2026-03", "SD2603-000", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "2026-03", "SD2603-001", "base_cabinet_800")

    cluster, features, sources = audit_directories(tmp_path, "2026-01", "2026-03")
    report = build_report(cluster, features, sources)

    monthly = report["monthly"]
    assert set(monthly) == {"2026-01", "2026-03"}
    assert monthly["2026-01"]["cabinets"] == 2
    assert monthly["2026-01"]["covered"] == 2
    assert monthly["2026-01"]["coverage_pct"] == 100.0
    assert monthly["2026-03"]["covered"] == 1
    assert monthly["2026-03"]["coverage_pct"] == 50.0
    assert report["coverage"]["ratio_pct"] == 75.0


# -- report.json structure: stable and serializable --

@pytest.fixture(scope="module")
def full_report(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("full")
    # covered wardrobe family of 3 (widths 2000-2150, spread inside the bin)
    # plus one base-cabinet outlier -> 3/4 = 75%, verdict 成立.
    make_drawing(tmp_path, "2026-01", "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "2026-01", "SD2601-001", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "2026-01", "SD2601-002", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "2026-01", "SD2601-003", "base_cabinet_800")
    cluster, features, sources = audit_directory(tmp_path, "2026-01")
    return build_report(cluster, features, sources)


def test_report_json_round_trips_exactly(full_report):
    encoded = json.dumps(full_report, ensure_ascii=False, indent=2)
    assert json.loads(encoded) == full_report


def test_report_json_has_all_ticket_fields(full_report):
    # issue #6 deliverable 3: family list with pending label + representative
    # + member count, per-family size min-max, grade detail, sample orders /
    # source directories, Top-N curve, coverage, verdict.
    assert full_report["schema"] == "audit-report/1"
    for section in ("totals", "coverage", "verdict", "top_n", "monthly", "families"):
        assert section in full_report

    wardrobe = next(f for f in full_report["families"] if f["member_count"] == 3)
    assert wardrobe["label"] is None
    assert wardrobe["label_pending"] is True
    assert wardrobe["representative"].startswith("SD2601-")
    assert wardrobe["width"] == {"min": 2000.0, "max": 2150.0}
    assert wardrobe["height"] == {"min": 2400.0, "max": 2400.0}
    assert wardrobe["grades"] and wardrobe["grades"][0]["grade"].startswith(wardrobe["family"])
    assert "SD2601-000" in wardrobe["sample_orders"]
    assert wardrobe["source_directories"] == ["2026-01"]


def test_report_sources_fallback_without_source_map(tmp_path):
    # build_report stays usable when the caller passes no source map.
    make_drawing(tmp_path, "jan", "A", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "B", "wardrobe_2150_tol_within")
    cluster, features, _ = audit_directory(tmp_path, "jan")

    report = build_report(cluster, features)

    fam = report["families"][0]
    # fallback: the cabinet id stands in for the missing order number
    assert fam["sample_orders"] == ["A#0", "B#0"]
    assert fam["source_directories"] == ["unknown"]
    assert report["monthly"]["unknown"]["cabinets"] == 2


def test_empty_input_yells_fail_with_zero_coverage():
    report = build_report({"families": []}, {})

    assert report["totals"]["cabinets"] == 0
    assert report["coverage"]["ratio_pct"] == 0.0
    assert report["verdict"]["level"] == "fail"
    assert report["top_n"] == []
    assert report["monthly"] == {}


# -- report.md: verdict first, then family details --

def test_markdown_conclusion_first(full_report):
    from audit_tool.report import render_markdown

    md = render_markdown(full_report)

    lines = md.strip().splitlines()
    assert lines[0].startswith("#")
    verdict_idx = next(i for i, ln in enumerate(lines) if "条件成立" in ln or "成立" in ln)
    coverage_idx = next(i for i, ln in enumerate(lines) if "75.0" in ln or "75%" in ln)
    family_idx = next(i for i, ln in enumerate(lines) if "f0" in ln and "|" in ln)
    assert verdict_idx < len(lines) // 2
    assert coverage_idx < family_idx
    assert family_idx < len(lines)


def test_markdown_contains_family_details_and_thumbnail_links(full_report):
    from audit_tool.report import render_markdown

    md = render_markdown(full_report)

    # family table with pending-label placeholder, min-max sizes, samples
    assert "待人工命名" in md
    assert "2000" in md and "2150" in md
    assert "SD2601-000" in md
    # per-family thumbnail as a relative link into the thumbnails directory
    assert "thumbnails/" in md
    assert "](thumbnails/" in md


# -- write_report: artifacts on disk --

def test_write_report_writes_json_md_and_thumbnails(tmp_path):
    make_drawing(tmp_path, "jan", "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(tmp_path, "jan", "SD2601-001", "wardrobe_2150_tol_within")
    make_drawing(tmp_path, "jan", "SD2601-002", "base_cabinet_800")
    cluster, features, sources = audit_directory(tmp_path, "jan")
    report = build_report(cluster, features, sources)

    # fronts by cabinet id, as the pipeline would hand them over
    fronts = {}
    for path in sorted((tmp_path / "jan").glob("*.dxf")):
        for cabinet in extract_cabinets(path):
            fronts[f"{path.stem}#{cabinet.index}"] = cabinet

    out = tmp_path / "out"
    paths = write_report(report, out, fronts=fronts)

    # json round-trips and carries the full structure
    loaded = json.loads(out.joinpath("report.json").read_text(encoding="utf-8"))
    assert loaded == report
    assert out.joinpath("report.md").read_text(encoding="utf-8").startswith("#")

    # every family's representative rendered as a PNG at the linked path
    assert len(paths["thumbnails"]) == len(report["families"])
    for fam in report["families"]:
        png = out / fam["thumbnail"]
        assert png.exists() and png.stat().st_size > 0
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert f"]({fam['thumbnail']})" in out.joinpath("report.md").read_text(encoding="utf-8")


def test_write_report_without_fronts_skips_thumbnails(tmp_path):
    report = build_report({"families": []}, {})

    paths = write_report(report, tmp_path / "out")

    assert paths["thumbnails"] == []
    assert (tmp_path / "out" / "report.json").exists()
    assert (tmp_path / "out" / "report.md").exists()
