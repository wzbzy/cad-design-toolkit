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
