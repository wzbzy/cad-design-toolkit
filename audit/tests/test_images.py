"""Per-cabinet JPG export by family / parametric grade (issue #9).

Library seam: :func:`audit_tool.images.export_family_images`, driven with a
hand-built known-answer report dict (independent of the pipeline, so the
expected directory tree is the source of truth) and small in-memory images.
End-to-end behavior through the CLI seam lives in ``test_cli.py``.
"""

from PIL import Image

from audit_tool.images import (
    FAILED_DIR,
    FAMILIES_DIR,
    UNGRADED_DIR,
    export_family_images,
)


def _img(color=0):
    return Image.new("L", (32, 32), color)


def _fronts(tmp_path):
    """Extract real cabinet fronts from a fixture wardrobe (one cabinet)."""
    from audit_tool.extract import extract_cabinets
    from audit_tool.fixtures import build_wardrobe, save_dxf

    save_dxf(build_wardrobe(), tmp_path / "SD2601-000.dxf")
    return {f"SD2601-000#{c.index}": c for c in extract_cabinets(tmp_path / "SD2601-000.dxf")}


def _report():
    return {
        "families": [
            {
                "family": "f0",
                "grades": [
                    {"grade": "f0#g0", "members": ["SD2601-000#0", "SD2601-001#0"],
                     "covered": True},
                ],
            },
        ],
    }


# -- covered cabinets: families/<族ID>/<档ID>/<柜ID>.jpg --

def test_covered_cabinets_exported_into_family_grade_directories(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}

    export_family_images(report, tmp_path, images=images)

    grade_dir = tmp_path / FAMILIES_DIR / "f0" / "g0"
    assert sorted(p.name for p in grade_dir.glob("*.jpg")) == [
        "SD2601-000_0.jpg",
        "SD2601-001_0.jpg",
    ]


def test_exported_jpgs_are_readable_by_pillow(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}

    export_family_images(report, tmp_path, images=images)

    path = tmp_path / FAMILIES_DIR / "f0" / "g0" / "SD2601-000_0.jpg"
    with Image.open(path) as im:
        im.verify()  # raises on a corrupt / truncated file


# -- uncovered cabinets: families/_未归类/<柜ID>.jpg --

def test_uncovered_cabinets_land_in_the_ungraded_directory(tmp_path):
    report = _report()
    report["families"][0]["grades"].append(
        {"grade": "f0#g1", "members": ["SD2603-000#0"], "covered": False}
    )
    images = {
        "SD2601-000#0": _img(),
        "SD2601-001#0": _img(),
        "SD2603-000#0": _img(255),
    }

    export_family_images(report, tmp_path, images=images)

    ungraded = tmp_path / FAMILIES_DIR / UNGRADED_DIR
    assert sorted(p.name for p in ungraded.glob("*.jpg")) == ["SD2603-000_0.jpg"]
    # no grade subdirectory is created for the uncovered cabinet
    assert not (tmp_path / FAMILIES_DIR / "f0" / "g1").exists()


# -- failed drawings: families/_失败/<文件名>.txt with the reason --

def test_failed_drawings_become_txt_notes_with_the_reason(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}
    failed = [{"file": "broken_order.dwg", "directory": "2026-03",
               "error": "unknown DWG version"}]

    result = export_family_images(report, tmp_path, images=images, failed=failed)

    note = tmp_path / FAMILIES_DIR / FAILED_DIR / "broken_order.dwg.txt"
    assert note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "broken_order.dwg" in text
    assert "2026-03" in text
    assert "unknown DWG version" in text
    assert result["failed"] == [str(note)]


# -- every cabinet ends up as exactly one JPG somewhere under families/ --

def test_exported_jpg_count_equals_reported_cabinet_count(tmp_path):
    report = _report()
    report["families"][0]["grades"].append(
        {"grade": "f0#g1", "members": ["SD2603-000#0"], "covered": False}
    )
    images = {
        "SD2601-000#0": _img(),
        "SD2601-001#0": _img(),
        "SD2603-000#0": _img(255),
    }

    result = export_family_images(report, tmp_path, images=images)

    all_jpgs = list((tmp_path / FAMILIES_DIR).rglob("*.jpg"))
    assert len(all_jpgs) == 3
    assert len(result["jpgs"]) == 3


# -- per-cabinet DXF (issue #9 范围补充): <柜ID>.dxf next to <柜ID>.jpg --

def test_cabinet_dxf_is_exported_next_to_the_jpg(tmp_path):
    report = _report()
    fronts = _fronts(tmp_path)
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}

    export_family_images(report, tmp_path, images=images, fronts=fronts)

    grade_dir = tmp_path / FAMILIES_DIR / "f0" / "g0"
    assert (grade_dir / "SD2601-000_0.dxf").is_file()
    assert (grade_dir / "SD2601-000_0.jpg").is_file()


def test_cabinet_dxf_reads_back_with_the_extracted_entity_set(tmp_path):
    import ezdxf

    report = _report()
    report["families"][0]["grades"] = [
        {"grade": "f0#g0", "members": ["SD2601-000#0"], "covered": True}
    ]
    fronts = _fronts(tmp_path)

    export_family_images(report, tmp_path, images={"SD2601-000#0": _img()}, fronts=fronts)

    path = tmp_path / FAMILIES_DIR / "f0" / "g0" / "SD2601-000_0.dxf"
    doc = ezdxf.readfile(str(path))
    # the standalone sheet carries exactly the cabinet's extracted geometry
    assert len(list(doc.modelspace())) == len(fronts["SD2601-000#0"].entities)
    assert len(list(doc.modelspace())) > 0


def test_cabinets_without_fronts_get_jpg_only(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}

    export_family_images(report, tmp_path, images=images)

    grade_dir = tmp_path / FAMILIES_DIR / "f0" / "g0"
    assert list(grade_dir.glob("*.jpg"))
    assert not list(grade_dir.glob("*.dxf"))


# -- ungraded cabinets get the same jpg + dxf pair --

def test_ungraded_cabinet_gets_jpg_and_dxf_pair(tmp_path):
    report = _report()
    report["families"][0]["grades"] = [
        {"grade": "f0#g1", "members": ["SD2601-000#0"], "covered": False}
    ]
    fronts = _fronts(tmp_path)

    export_family_images(report, tmp_path, images={"SD2601-000#0": _img()}, fronts=fronts)

    ungraded = tmp_path / FAMILIES_DIR / UNGRADED_DIR
    assert (ungraded / "SD2601-000_0.jpg").is_file()
    assert (ungraded / "SD2601-000_0.dxf").is_file()


# -- failed drawings whose sheet converted keep the dxf for inspection --

def test_failed_record_with_dxf_copies_the_sheet(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}
    sheet = tmp_path / "converted.dxf"
    sheet.write_text("0\nSECTION\nENDSEC\n0\nEOF\n", encoding="ascii")
    failed = [{"file": "broken_order.dwg", "directory": "2026-03",
               "error": "no unit cabinets extracted", "dxf": str(sheet)}]

    export_family_images(report, tmp_path, images=images, failed=failed)

    failed_dir = tmp_path / FAMILIES_DIR / FAILED_DIR
    assert (failed_dir / "broken_order.dwg.txt").is_file()
    assert (failed_dir / "broken_order.dwg.dxf").is_file()


def test_failed_record_without_dxf_gets_txt_only(tmp_path):
    report = _report()
    images = {"SD2601-000#0": _img(), "SD2601-001#0": _img()}
    failed = [{"file": "broken_order.dwg", "directory": "2026-03",
               "error": "unknown DWG version"}]

    export_family_images(report, tmp_path, images=images, failed=failed)

    failed_dir = tmp_path / FAMILIES_DIR / FAILED_DIR
    assert (failed_dir / "broken_order.dwg.txt").is_file()
    assert not (failed_dir / "broken_order.dwg.dxf").exists()
