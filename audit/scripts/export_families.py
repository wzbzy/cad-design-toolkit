"""Post-run export: one JPG per cabinet, filed by family / parametric grade.

Harness-side post-processing only (ticket #8 acceptance follow-up) -- does
not touch report.py/cli.py (a parallel ticket owns those). Reads the run's
intermediate products and renders/, and writes:

    <out>/families/<族目录>/<档目录>/<柜ID>.jpg      # 族目录 = f<id>_<代表柜>
                                                     # 档目录 = <family>#g<k>
    <out>/families/_未归类/<柜ID>.jpg               # cabinet in no grade
    <out>/families/_失败/<原文件名>.txt              # per-file failure reason

Cabinet IDs are kept verbatim (Chinese included, order no./stem traceable);
only characters Windows forbids in paths are replaced. The cluster/grade
statistics themselves are untouched -- this is purely an evidence export.

Also appends a "家族图片归档" appendix to <out>/report.md describing the
layout and a suggested spot-check method.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]  # repo root (audit/scripts/..)
if (WORKTREE / "audit" / "audit_tool").is_dir():
    sys.path.insert(0, str(WORKTREE))

from PIL import Image  # noqa: E402

JPEG_QUALITY = 85
UNGRADED = "_未归类"
FAILED = "_失败"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(name: str) -> str:
    """Keep the ID readable (Chinese stays); replace path-hostile chars."""
    return _UNSAFE.sub("_", name).strip().rstrip(".") or "_"


def render_png(renders_dir: Path, cabinet_id: str) -> Path | None:
    """Render PNG for one cabinet id.

    Prefers the exact collision-free copy (renders_all/<sha1>.png) written
    by the streaming harness; falls back to the pipeline's safe-stem name
    (collides for Chinese-only stems -- about 10% of January renders were
    overwritten there, so the fallback may show a different cabinet).
    """
    import hashlib

    from audit_tool.cli import _safe_stem

    digest = hashlib.sha1(cabinet_id.encode("utf-8")).hexdigest()
    exact = renders_dir.parent / "renders_all" / f"{digest}.png"
    if exact.is_file():
        return exact
    path = renders_dir / f"{_safe_stem(cabinet_id)}.png"
    return path if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, help="audit run output dir")
    parser.add_argument("--families-dir", default=None,
                        help="export root (default: <run-dir>/families)")
    args = parser.parse_args()

    run = Path(args.run_dir)
    inter = run / "intermediate"
    renders = run / "renders"
    out_root = Path(args.families_dir) if args.families_dir else run / "families"
    families_root = out_root / "families"

    clusters = json.loads((inter / "clusters.json").read_text(encoding="utf-8"))
    grades = json.loads((inter / "grades.json").read_text(encoding="utf-8"))
    processing = json.loads((inter / "processing.json").read_text(encoding="utf-8"))

    cabinet_to_grade: dict[str, tuple[str, str]] = {}
    for family, fam_grades in grades.items():
        for g in fam_grades["grades"]:
            for cid in g["members"]:
                cabinet_to_grade[cid] = (family, g["grade"])

    if families_root.exists():
        import shutil
        shutil.rmtree(families_root)

    stats = {"families": 0, "jpg": 0, "missing_png": 0, "ungraded": 0,
             "per_family": {}}
    for fam in clusters["families"]:
        family, _ = cabinet_to_grade.get(fam["representative"], (None, None))
        if family is None:
            continue  # should not happen: grades cover every family
        rep = fam["representative"]
        fam_dir_name = f"{family}_{_safe(rep)}"
        fam_dir = families_root / _safe(fam_dir_name)
        counts: dict[str, int] = {}
        for cid in fam["members"]:
            dest_pair = cabinet_to_grade.get(cid)
            if dest_pair is None:
                dest_dir = families_root / UNGRADED
                grade_key = UNGRADED
            else:
                _, grade = dest_pair
                dest_dir = fam_dir / _safe(grade)
                grade_key = grade
            dest_dir.mkdir(parents=True, exist_ok=True)
            png = render_png(renders, cid)
            if png is None:
                stats["missing_png"] += 1
                continue
            dest = dest_dir / f"{_safe(cid)}.jpg"
            with Image.open(png) as img:
                img.convert("RGB").save(dest, "JPEG", quality=JPEG_QUALITY)
            stats["jpg"] += 1
            counts[grade_key] = counts.get(grade_key, 0) + 1
        stats["families"] += 1
        stats["per_family"][fam_dir_name] = counts

    ungraded_dir = families_root / UNGRADED
    for cid in sorted(set(cabinet_to_grade) ^ set(
            m for fam in clusters["families"] for m in fam["members"])):
        # members without any grade assignment (defensive; grades partition)
        if cid in cabinet_to_grade:
            continue
        ungraded_dir.mkdir(parents=True, exist_ok=True)
        png = render_png(renders, cid)
        if png is None:
            stats["missing_png"] += 1
            continue
        with Image.open(png) as img:
            img.convert("RGB").save(ungraded_dir / f"{_safe(cid)}.jpg",
                                    "JPEG", quality=JPEG_QUALITY)
        stats["ungraded"] += 1

    failed_dir = families_root / FAILED
    failed_dir.mkdir(parents=True, exist_ok=True)
    for entry in processing["failed"]:
        reason = f"{entry['file']}\n{entry['directory']}\n{entry['error']}\n"
        (failed_dir / f"{_safe(entry['file'])}.txt").write_text(
            reason, encoding="utf-8")

    appendix = [
        "",
        "## 附注：家族图片归档（人工抽查用）",
        "",
        f"全部柜体渲染图已按族/参数档导出为 JPG（质量 {JPEG_QUALITY}），"
        f"目录：`families/`（不入 git）。结构：",
        "",
        "```",
        "families/",
        "├── f<族号>_<代表柜>/            # 一个聚类族一个目录",
        "│   └── <族号>#g<档号>/         # 该族内的一个参数档一个目录",
        "│       └── <单号>#<柜序>.jpg   # 柜ID = 来源文件stem#柜序，可回溯",
        "├── _未归类/                    # 未落入任何参数档的柜",
        "└── _失败/                      # 处理失败的图纸，txt 内为失败原因",
        "```",
        "",
        f"本次导出：{stats['families']} 个族目录，{stats['jpg']} 张 JPG，"
        f"{stats['ungraded']} 张未归类，{len(processing['failed'])} 个失败图纸，"
        f"{stats['missing_png']} 张渲染缺失。柜体图片优先取自无冲突精确命名"
        "副本（renders_all/，按柜ID 哈希命名，文件名与图像严格一致）；仅当"
        "精确副本不存在时才回退安全名副本（纯中文图名会互相覆盖，该回退"
        "可能展示同名的另一台柜，已在导出统计中计数）。",
        "",
        "抽查方法建议：",
        "",
        "1. 任选 3~5 个成员数最多的族目录（代表柜即目录名后缀），核对目录内"
        "柜体外观是否确为同一形态；",
        "2. 进入族内每个 `#g<档号>` 子目录，核对同档柜体的拓扑（门/隔板布局）"
        "是否一致、尺寸是否在分箱容差内（见 report.json 该族 grades）；",
        "3. 对照 `families/_失败/` 中的图纸清单回看原图，确认失败原因是否成立。",
        "",
    ]
    md_path = run / "report.md"
    md_text = md_path.read_text(encoding="utf-8")
    if "## 附注：家族图片归档" not in md_text:
        md_path.write_text(md_text + "\n".join(appendix), encoding="utf-8")

    (out_root / "families_export_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"families exported to {families_root.parent}: "
          f"{stats['families']} families, {stats['jpg']} jpg, "
          f"{stats['ungraded']} ungraded, {stats['missing_png']} missing png, "
          f"{len(processing['failed'])} failed sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
