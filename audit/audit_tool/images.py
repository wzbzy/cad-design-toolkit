"""Browsable per-cabinet JPG export by family / parametric grade (issue #9).

The audit verdict (issue #6) is numbers; this module turns the same report
into something a human can flip through to verify clustering and grading by
eye (issue #9 数据分析可验证性):

- ``families/<族ID>/<参数档ID>/<柜ID>.jpg``  one JPG per covered cabinet
  (Pillow, :data:`DEFAULT_JPEG_QUALITY`), the grade directory named after
  the ``#g<k>`` suffix of the report's grade id;
- ``families/_未归类/<柜ID>.jpg``            cabinets in no reproducible
  parametric grade (singleton grades, union-find chains drifted beyond the
  bins -- the report's uncovered set);
- ``families/_失败/<文件名>.txt``            per drawing file that failed
  conversion/extraction, content = the failure reason.

Cabinet ids already carry their source order (``<stem>#<index>``, issue #3)
and that stem survives in the file name, so every JPG traces back to the
order drawing it came from.

- :func:`export_family_images` is the library seam: report dict + rendered
  images (or cabinet fronts to render) in, families/ tree out. It is called
  by the CLI after :func:`audit_tool.report.write_report` unless disabled.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "DEFAULT_JPEG_QUALITY",
    "FAILED_DIR",
    "FAMILIES_DIR",
    "UNGRADED_DIR",
    "export_family_images",
]

FAMILIES_DIR = "families"

UNGRADED_DIR = "_未归类"

FAILED_DIR = "_失败"

DEFAULT_JPEG_QUALITY = 85


def _safe_name(name: str) -> str:
    """Filesystem-safe form of a cabinet id / grade id / file name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _grade_dir_name(grade_id: str) -> str:
    """Directory name for one grade: the ``g<k>`` suffix of ``<family>#g<k>``."""
    return _safe_name(grade_id.split("#")[-1])


def _to_jpeg_image(img):
    """JPG has no alpha/palette edge cases to trip over -- normalize modes."""
    if img.mode not in ("L", "RGB"):
        return img.convert("RGB")
    return img


def export_family_images(report: dict, out_dir, images: dict | None = None,
                         fronts: dict | None = None, failed: list | None = None,
                         quality: int = DEFAULT_JPEG_QUALITY) -> dict:
    """Export every cabinet of a report as a browsable JPG tree (issue #9).

    ``report`` is the :func:`audit_tool.report.build_report` dict (its
    families/grades/``covered`` flags decide where each cabinet lands).
    Cabinet pixels come from ``images`` (cabinet id -> PIL image) or, when
    absent, are rendered from ``fronts`` (cabinet id ->
    :class:`audit_tool.extract.CabinetFront`). ``failed`` optionally lists
    per-file processing records (``{"file", "directory", "error"}``) that
    become ``_失败/<file>.txt`` notes.

    Returns ``{"dir", "jpgs", "ungraded", "failed"}`` with the families
    directory and the artifact paths.
    """
    if images is None and fronts is None:
        raise ValueError("export_family_images needs images or fronts")

    out = Path(out_dir)
    families_dir = out / FAMILIES_DIR
    ungraded_dir = families_dir / UNGRADED_DIR
    failed_dir = families_dir / FAILED_DIR
    families_dir.mkdir(parents=True, exist_ok=True)

    def pixels(cid: str):
        if images is not None and cid in images:
            return images[cid]
        from audit_tool.render import DEFAULT_SIZE, render_cabinet
        return render_cabinet(fronts[cid], size=DEFAULT_SIZE)

    jpgs: list[str] = []
    ungraded: list[str] = []
    for fam in report["families"]:
        for grade in fam["grades"]:
            if grade["covered"]:
                target = families_dir / _safe_name(fam["family"]) / _grade_dir_name(grade["grade"])
            else:
                target = ungraded_dir
            target.mkdir(parents=True, exist_ok=True)
            for cid in grade["members"]:
                path = target / f"{_safe_name(cid)}.jpg"
                _to_jpeg_image(pixels(cid)).save(path, quality=quality)
                jpgs.append(str(path))
                if not grade["covered"]:
                    ungraded.append(str(path))

    failed_notes: list[str] = []
    if failed:
        failed_dir.mkdir(parents=True, exist_ok=True)
        for record in failed:
            path = failed_dir / f"{_safe_name(record['file'])}.txt"
            path.write_text(
                f"directory: {record.get('directory', 'unknown')}\n"
                f"file: {record['file']}\n"
                f"error: {record.get('error', 'unknown')}\n",
                encoding="utf-8",
            )
            failed_notes.append(str(path))

    return {
        "dir": str(families_dir),
        "jpgs": jpgs,
        "ungraded": ungraded,
        "failed": failed_notes,
    }
