"""End-to-end tests for the audit CLI (issue #7) -- the single seam.

Per issue #1 (Testing Decisions / 单一 seam) every test here drives the
whole pipeline the way a user does: ``python -m audit`` (in-process
``main(argv)`` for speed, one subprocess test proving the module entry)
with fixture directories in, an audit report directory out. Nothing
internal is imported or asserted against; ``report.json`` structure and
values are the contract. No ODA/DWG dependency: DXF fixtures +
``--adapter dxf`` throughout.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from audit_tool import fixtures
from audit_tool.cli import main

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_DIR.parent  # `python -m audit` resolves the audit/ package from here


def make_drawing(directory, order_no, scenario=None, builder=None):
    """Write one fixture DXF (one unit cabinet) named after the order no."""
    directory.mkdir(parents=True, exist_ok=True)
    doc = builder() if builder is not None else fixtures.build_scenario(scenario)
    fixtures.save_dxf(doc, directory / f"{order_no}.dxf")


def run_cli(*args):
    """Run the CLI seam; returns (exit code, captured stdout, stderr via capsys)."""
    return main(["--adapter", "dxf", *args])


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# -- the module entry really is ``python -m audit`` --

def test_python_m_audit_help_is_self_explanatory():
    result = subprocess.run(
        [sys.executable, "-m", "audit", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for flag in ("--input", "--output", "--config", "--adapter", "--no-export-images"):
        assert flag in result.stdout
    assert "oda" in result.stdout.lower()  # adapter choices documented


# -- known-answer end-to-end: similar wardrobes only -> 100% / 成立 --

def test_similar_wardrobes_end_to_end_full_coverage(tmp_path, capsys):
    inputs = tmp_path / "in" / "jan"
    for i in range(3):
        make_drawing(inputs, f"SD2601-{i:03d}", "wardrobe_2000_baseline")
    for i in range(2):
        make_drawing(inputs, f"SD2601-1{i:02d}", "wardrobe_2150_tol_within")
    out = tmp_path / "out"

    rc = run_cli("--input", str(inputs), "--output", str(out))

    assert rc == 0
    # report artifacts
    report = read_json(out / "report.json")
    assert report["schema"] == "audit-report/1"
    assert report["totals"]["cabinets"] == 5
    assert report["totals"]["families"] == 1
    assert report["totals"]["grades"] == 1
    assert report["coverage"]["ratio_pct"] == 100.0
    assert report["verdict"]["level"] == "pass"
    assert report["verdict"]["conclusion"] == "成立"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "成立" in md
    # family representative thumbnail exists and the md link resolves
    thumbs = list((out / "thumbnails").glob("*.png"))
    assert len(thumbs) == 1
    assert (out / report["families"][0]["thumbnail"]).is_file()

    # intermediate products are on disk (issue #7 deliverable 3)
    hashes = read_json(out / "intermediate" / "hashes.json")
    assert len(hashes) == 5
    clusters = read_json(out / "intermediate" / "clusters.json")
    assert clusters["algorithm"] == "phash-complete-linkage"
    assert len(clusters["families"]) == 1
    features = read_json(out / "intermediate" / "features.json")
    assert len(features) == 5
    grades = read_json(out / "intermediate" / "grades.json")
    assert list(grades) == ["f0"]
    # per-cabinet renders: one png per cabinet
    assert len(list((out / "renders").glob("*.png"))) == 5

    # families image export is on by default (issue #9): one jpg per cabinet,
    # all covered -> families/f0/g0/
    grade_dir = out / "families" / "f0" / "g0"
    assert sorted(p.name for p in grade_dir.glob("*.jpg")) == [
        "SD2601-000_0.jpg",
        "SD2601-001_0.jpg",
        "SD2601-002_0.jpg",
        "SD2601-100_0.jpg",
        "SD2601-101_0.jpg",
    ]
    # cabinet ids keep the order stem -> traceable back to the drawing
    from PIL import Image
    with Image.open(grade_dir / "SD2601-000_0.jpg") as im:
        im.verify()


# -- families image export (issue #9): ungraded + failed archiving --

def test_image_export_archives_ungraded_and_failed(tmp_path):
    jan = tmp_path / "in" / "jan"
    make_drawing(jan, "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-001", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2603-000", "base_cabinet_800")  # own family, singleton grade
    (jan / "broken_order.dwg").write_bytes(b"not a real dwg")
    out = tmp_path / "out"

    rc = run_cli("--input", str(jan), "--output", str(out))

    assert rc == 0
    report = read_json(out / "report.json")
    assert report["totals"]["cabinets"] == 3
    families = out / "families"
    # covered pair lands in its family/grade directory
    assert len(list((families / "f0" / "g0").glob("*.jpg"))) == 2
    # the singleton base cabinet has no reproducible grade -> _未归类
    assert sorted(p.name for p in (families / "_未归类").glob("*.jpg")) == [
        "SD2603-000_0.jpg"
    ]
    # every cabinet exported exactly once, plus the failed drawing note
    assert len(list(families.rglob("*.jpg"))) == 3
    note = families / "_失败" / "broken_order.dwg.txt"
    assert note.is_file()
    assert "broken_order.dwg" in note.read_text(encoding="utf-8")
    # report.md documents the layout and how to spot-check it
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "图片目录结构与抽查方法" in md
    assert "_未归类" in md
    assert "_失败" in md


def test_no_export_images_flag_skips_the_families_tree(tmp_path):
    jan = tmp_path / "in" / "jan"
    make_drawing(jan, "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-001", "wardrobe_2000_baseline")
    out = tmp_path / "out"

    rc = run_cli("--input", str(jan), "--output", str(out), "--no-export-images")

    assert rc == 0
    assert not (out / "families").exists()
    # the report itself is still complete
    assert read_json(out / "report.json")["totals"]["cabinets"] == 2


# -- multi-month input + outliers -> exact coverage / 条件成立 / 跨月 --

def test_multi_month_with_outliers_exact_coverage(tmp_path):
    jan = tmp_path / "in" / "2026-01"
    feb = tmp_path / "in" / "2026-03"
    make_drawing(jan, "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-001", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-002", "wardrobe_2150_tol_within")
    make_drawing(feb, "SD2603-000", "wardrobe_4comp_alt_topology")
    make_drawing(feb, "SD2603-001", "base_cabinet_800")
    out = tmp_path / "out"

    rc = run_cli("--input", str(jan), "--input", str(feb), "--output", str(out))

    assert rc == 0
    report = read_json(out / "report.json")
    # 3 covered wardrobes of 5 cabinets -> 60% -> 条件成立
    assert report["totals"]["covered_cabinets"] == 3
    assert report["coverage"]["ratio_pct"] == pytest.approx(60.0)
    assert report["verdict"]["level"] == "conditional"
    # cross-month comparison keyed by input directory name
    assert set(report["monthly"]) == {"2026-01", "2026-03"}
    assert report["monthly"]["2026-01"] == {
        "cabinets": 3,
        "covered": 3,
        "coverage_pct": 100.0,
        "families": 1,
    }


# -- config file drives thresholds and tolerances (no hardcoded knobs) --

def test_config_file_overrides_thresholds_and_tolerances(tmp_path):
    jan = tmp_path / "in" / "jan"
    make_drawing(jan, "SD2601-000", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-001", "wardrobe_2000_baseline")
    make_drawing(jan, "SD2601-002", "wardrobe_2150_tol_within")
    make_drawing(jan, "SD2603-003", "wardrobe_4comp_alt_topology")
    make_drawing(jan, "SD2603-004", "base_cabinet_800")
    out = tmp_path / "out"
    # 60% coverage by default -> conditional; a 50% pass bar makes it 成立
    config = tmp_path / "audit.toml"
    config.write_text(
        "[report]\n"
        "pass_threshold = 50.0\n"
        "conditional_threshold = 30.0\n",
        encoding="utf-8",
    )

    rc = run_cli("--input", str(jan), "--output", str(out), "--config", str(config))

    assert rc == 0
    report = read_json(out / "report.json")
    assert report["coverage"]["ratio_pct"] == pytest.approx(60.0)
    assert report["verdict"]["level"] == "pass"
    assert report["verdict"]["thresholds"]["pass_min_pct"] == 50.0


def test_config_file_overrides_grading_tolerances(tmp_path):
    jan = tmp_path / "in" / "jan"
    make_drawing(jan, "A", "wardrobe_2000_baseline")
    make_drawing(jan, "B", "wardrobe_2150_tol_within")  # width diff 150
    out = tmp_path / "out"
    # width bin +-100 splits the pair into singleton grades -> 0% covered
    config = tmp_path / "audit.toml"
    config.write_text("[grading]\nwidth_tolerance = 100.0\n", encoding="utf-8")

    rc = run_cli("--input", str(jan), "--output", str(out), "--config", str(config))

    assert rc == 0
    report = read_json(out / "report.json")
    assert report["coverage"]["ratio_pct"] == 0.0
    assert report["totals"]["grades"] == 2
    assert report["verdict"]["level"] == "fail"


# -- adapter selection: dxf adapter never touches ODA, failures are recorded --

def test_dxf_adapter_records_unreadable_dwg_as_failed(tmp_path):
    inputs = tmp_path / "in" / "jan"
    make_drawing(inputs, "SD2601-000", "wardrobe_2000_baseline")
    (inputs / "broken_order.dwg").write_bytes(b"not a real dwg")
    out = tmp_path / "out"

    rc = run_cli("--input", str(inputs), "--output", str(out))

    assert rc == 0  # the audit completes; the failure is evidence, not a crash
    processing = read_json(out / "intermediate" / "processing.json")
    assert processing["files_processed"] == 2
    failed = {f["file"]: f for f in processing["failed"]}
    assert "broken_order.dwg" in failed
    assert "DXF" in failed["broken_order.dwg"]["error"]
    report = read_json(out / "report.json")
    assert report["totals"]["cabinets"] == 1  # only the DXF cabinet


def test_default_oda_adapter_without_oda_path_is_a_usage_error(tmp_path, capsys):
    inputs = tmp_path / "in" / "jan"
    make_drawing(inputs, "SD2601-000", "wardrobe_2000_baseline")

    rc = main(["--input", str(inputs), "--output", str(tmp_path / "out")])

    assert rc == 2
    assert "ODA" in capsys.readouterr().err
