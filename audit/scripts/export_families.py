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

from PIL import Image

WORKTREE = Path(r"D:\phpstudy_pro\WWW\cad-design-toolkit\.claude\worktrees\t8")
sys.path.insert(0, str(WORKTREE))

JPEG_QUALITY = 85
UNGRADED = "_未归类"
FAILED = "_失败"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(name: str) -> str:
    """Keep the ID readable (Chinese stays); replace path-hostile chars."""
    return _UNSAFE.sub("_", name).strip().rstrip(".") or "_"


def exact_copy(renders_dir: Path, cabinet_id: str, kind: str) -> Path | None:
    """Exact collision-free harness copy (renders_all/ or splits_all/),
    keyed by sha1 of the full cabinet id: filename always matches content."""
    import hashlib

    extension = {"renders_all": "png", "splits_all": "dxf"}[kind]
    digest = hashlib.sha1(cabinet_id.encode("utf-8")).hexdigest()
    path = renders_dir.parent / kind / f"{digest}.{extension}"
    return path if path.is_file() else None


def render_png(renders_dir: Path, cabinet_id: str) -> Path | None:
    """Render PNG for one cabinet id.

    Prefers the exact collision-free copy (renders_all/<sha1>.png) written
    by the streaming harness; falls back to the pipeline's safe-stem name
    (collides for Chinese-only stems -- about 10% of January renders were
    overwritten there, so the fallback may show a different cabinet).
    """
    from audit_tool.cli import _safe_stem

    exact = exact_copy(renders_dir, cabinet_id, "renders_all")
    if exact is not None:
        return exact
    path = renders_dir / f"{_safe_stem(cabinet_id)}.png"
    return path if path.is_file() else None


def split_dxf(renders_dir: Path, cabinet_id: str) -> Path | None:
    """Split DXF for one cabinet id (splits_all/<sha1>.dxf) or None."""
    return exact_copy(renders_dir, cabinet_id, "splits_all")


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

    stats = {"families": 0, "jpg": 0, "dxf": 0, "missing_png": 0,
             "missing_dxf": 0, "ungraded": 0, "per_family": {}}

    def export_one(cid: str, dest_dir: Path, grade_key: str,
                   counts: dict | None) -> None:
        """One cabinet -> <柜ID>.jpg + <柜ID>.dxf pair (either may be absent)."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe(cid)
        png = render_png(renders, cid)
        if png is None:
            stats["missing_png"] += 1
        else:
            with Image.open(png) as img:
                img.convert("RGB").save(dest_dir / f"{stem}.jpg", "JPEG",
                                        quality=JPEG_QUALITY)
            stats["jpg"] += 1
            counts[grade_key] = counts.get(grade_key, 0) + 1 if counts else 0
        dxf = split_dxf(renders, cid)
        if dxf is None:
            stats["missing_dxf"] += 1
        else:
            import shutil
            shutil.copyfile(dxf, dest_dir / f"{stem}.dxf")
            stats["dxf"] += 1

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
            export_one(cid, dest_dir, grade_key, counts)
        stats["families"] += 1
        stats["per_family"][fam_dir_name] = counts

    ungraded_dir = families_root / UNGRADED
    for cid in sorted(set(cabinet_to_grade) ^ set(
            m for fam in clusters["families"] for m in fam["members"])):
        # members without any grade assignment (defensive; grades partition)
        if cid in cabinet_to_grade:
            continue
        export_one(cid, ungraded_dir, UNGRADED, None)
        stats["ungraded"] += 1

    failed_dir = families_root / FAILED
    failed_dir.mkdir(parents=True, exist_ok=True)
    for entry in processing["failed"]:
        reason = f"{entry['file']}\n{entry['directory']}\n{entry['error']}\n"
        (failed_dir / f"{_safe(entry['file'])}.txt").write_text(
            reason, encoding="utf-8")

    appendix = [
        "",
        "## 附注：家族拆分包（人工抽查用）",
        "",
        "每个柜体一对文件（同名，可看图↔开图对照）：`<柜ID>.jpg` 渲染图 + "
        "`<柜ID>.dxf` 独立可打开的拆分图元文件。目录结构"
        f"（`families/` 不入 git）：",
        "",
        "```",
        "families/",
        "├── f<族号>_<代表柜>/            # 一个聚类族一个目录",
        "│   └── <族号>#g<档号>/         # 该族内的一个参数档一个目录",
        "│       ├── <单号>#<柜序>.jpg   # 柜ID = 来源文件stem#柜序，可回溯",
        "│       └── <单号>#<柜序>.dxf   # 与 JPG 同名的拆分 DXF",
        "├── _未归类/                    # 未落入任何参数档的柜（同样成对）",
        "└── _失败/                      # 处理失败的图纸，txt 内为失败原因",
        "```",
        "",
        f"本次导出：{stats['families']} 个族目录，{stats['jpg']} 张 JPG，"
        f"{stats['dxf']} 个拆分 DXF（JPG/DXF 成对，缺一即计缺失），"
        f"{stats['ungraded']} 张未归类，{len(processing['failed'])} 个失败图纸，"
        f"{stats['missing_png']} 张渲染缺失，{stats['missing_dxf']} 个拆分 DXF "
        "缺失。图片优先取自无冲突精确命名副本（renders_all/，按柜ID 哈希"
        "命名）；拆分 DXF 由该柜图元跨文档复制生成（同文档坐标系），图层/"
        "线型/文字样式表项随迁；INSERT 块定义复制一层深，块内嵌套 INSERT "
        "不再展开（已知限制）。",
        "",
        "抽查方法建议：",
        "",
        "1. 任选 3~5 个成员数最多的族目录（代表柜即目录名后缀），核对目录内"
        "柜体外观是否确为同一形态；",
        "2. 进入族内每个 `#g<档号>` 子目录，核对同档柜体的拓扑（门/隔板布局）"
        "是否一致、尺寸是否在分箱容差内（见 report.json 该族 grades）；",
        "3. 打开任一 `<柜ID>.dxf`，核对图元与同名 JPG 中的柜体一致"
        "（DXF 保留源图坐标）；",
        "4. 对照 `families/_失败/` 中的图纸清单回看原图，确认失败原因是否成立。",
        "",
    ]
    md_path = run / "report.md"
    md_path.write_text(md_path.read_text(encoding="utf-8") + "\n".join(appendix),
                       encoding="utf-8")

    (out_root / "families_export_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"families exported to {families_root.parent}: "
          f"{stats['families']} families, {stats['jpg']} jpg, "
          f"{stats['dxf']} dxf, {stats['ungraded']} ungraded, "
          f"{stats['missing_png']} missing png, {stats['missing_dxf']} missing dxf, "
          f"{len(processing['failed'])} failed sheets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
