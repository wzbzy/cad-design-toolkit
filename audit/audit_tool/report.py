"""Audit report generation (issue #6): metrics, verdict, JSON + Markdown.

The convergence point of the pipeline: coarse clusters (issue #4) plus
extracted cabinet fronts (issue #3) go in, the audit report artifacts come
out. This module is a library, not a CLI -- the CLI and the tolerance
config file are a later ticket and will call these functions.

- :func:`build_report` computes the cabinet-level parametric coverage
  (柜体级参数化覆盖率), the Top-N curve, the per-source-directory
  (跨月) grouping and the three-level verdict (issue #1 判定标准), and
  assembles the ``report.json`` dict. Thresholds come from
  :class:`ReportConfig` -- never hardcoded.
- :func:`render_markdown` renders the human-readable ``report.md``,
  verdict first.
- :func:`write_report` writes both artifacts (and family-representative
  thumbnails when fronts are supplied).

**Coverage definition.** A cabinet is parametrically covered when it
shares a parametric grade (参数档, from issue #5) with at least one other
cabinet and the grade's max dimension spread stays inside the configured
bin tolerances. A grade of one cabinet means no other order reuses the
template; a transitive-closure grade whose ends have drifted beyond the
bin (issue #5 union-find chains) is not reproducible from one template
by parameter adjustment alone. Both cases count as uncovered.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from audit_tool.grade import DEFAULT_GRADING_CONFIG, GradingConfig, grade_families
from audit_tool.images import (
    DEFAULT_JPEG_QUALITY as IMAGE_QUALITY,
    FAILED_DIR,
    FAMILIES_DIR,
    UNGRADED_DIR,
)

__all__ = [
    "DEFAULT_REPORT_CONFIG",
    "REPORT_SCHEMA",
    "THUMBNAIL_DIR",
    "ReportConfig",
    "build_report",
    "judge_coverage",
    "render_markdown",
    "thumbnail_path",
    "write_report",
]

REPORT_SCHEMA = "audit-report/1"

THUMBNAIL_DIR = "thumbnails"

VERDICT_CONCLUSIONS = {
    "pass": "成立",
    "conditional": "条件成立",
    "fail": "不成立",
}

VERDICT_NOTES = {
    "pass": "覆盖率达标，项目可以立项。",
    "conditional": "仅对高频家族建库，低频品类维持现状手绘。",
    "fail": "订单柜体重复性不足，不建议启动图库/插件建设。",
}


def thumbnail_path(family: str, representative: str) -> str:
    """Relative (report.md-relative) path of one family's thumbnail."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", representative)
    return f"{THUMBNAIL_DIR}/{family}_{safe}.png"


@dataclass(frozen=True)
class ReportConfig:
    """Report thresholds (issue #1: 判定阈值写入配置, not hardcoded).

    ``pass_threshold`` / ``conditional_threshold`` are percentages of
    cabinet-level parametric coverage: coverage >= pass -> 成立;
    conditional <= coverage < pass -> 条件成立; below conditional ->
    不成立. ``grading`` carries the parametric-grade bin tolerances the
    coverage check re-validates.
    """

    pass_threshold: float = 70.0
    conditional_threshold: float = 40.0
    grading: GradingConfig = DEFAULT_GRADING_CONFIG


DEFAULT_REPORT_CONFIG = ReportConfig()


def judge_coverage(coverage_pct: float, config: ReportConfig = DEFAULT_REPORT_CONFIG) -> dict:
    """Three-level verdict for one coverage percentage (issue #1 判定标准)."""
    if coverage_pct >= config.pass_threshold:
        level = "pass"
    elif coverage_pct >= config.conditional_threshold:
        level = "conditional"
    else:
        level = "fail"
    return {
        "level": level,
        "conclusion": VERDICT_CONCLUSIONS[level],
        "coverage_pct": coverage_pct,
        "thresholds": {
            "pass_min_pct": config.pass_threshold,
            "conditional_min_pct": config.conditional_threshold,
        },
    }


def _grade_spread_within_tolerance(members: list, config: ReportConfig) -> bool:
    """True when one grade's max dimension spread stays in the bins."""
    widths = [f.width for f in members]
    heights = [f.height for f in members]
    depths = [f.depth for f in members if f.depth is not None]
    g = config.grading
    if max(widths) - min(widths) > g.width_tolerance:
        return False
    if max(heights) - min(heights) > g.height_tolerance:
        return False
    if depths and max(depths) - min(depths) > g.depth_tolerance:
        return False
    return True


def build_report(cluster: dict, features: dict, sources: dict | None = None,
                 config: ReportConfig = DEFAULT_REPORT_CONFIG) -> dict:
    """Assemble the audit report dict (``report.json`` content).

    ``cluster`` is the :func:`audit_tool.cluster.cluster_hashes` result;
    ``features`` maps cabinet id -> :class:`audit_tool.grade.CabinetFeatures`;
    ``sources`` optionally maps cabinet id -> ``{"order_no", "drawing",
    "directory"}`` (unknown ids fall back to the cabinet id / "unknown").
    """
    if sources is None:
        sources = {}

    families = {}
    for fam in cluster["families"]:
        families[f"f{fam['id']}"] = [features[m] for m in fam["members"]]
    grades = grade_families(families, config.grading)

    covered_ids: list[str] = []
    family_entries = []
    for fam in cluster["families"]:
        key = f"f{fam['id']}"
        member_ids = list(fam["members"])
        members = [features[cid] for cid in member_ids]
        fam_grades = []
        for g in grades[key]["grades"]:
            g_members = [features[cid] for cid in g["members"]]
            is_covered = len(g_members) >= 2 and _grade_spread_within_tolerance(g_members, config)
            if is_covered:
                covered_ids.extend(g["members"])
            fam_grades.append({**g, "member_count": len(g["members"]), "covered": is_covered})

        widths = [f.width for f in members]
        heights = [f.height for f in members]
        depths = [f.depth for f in members if f.depth is not None]
        rep = fam["representative"]
        family_entries.append({
            "family": key,
            "label": None,  # 族名占位: 人工从 GLOSSARY 柜型词表命名
            "label_pending": True,
            "representative": rep,
            "member_count": len(member_ids),
            "members": list(member_ids),
            "width": {"min": min(widths), "max": max(widths)},
            "height": {"min": min(heights), "max": max(heights)},
            "depth": {"min": min(depths), "max": max(depths)} if depths else None,
            "grades": fam_grades,
            "sample_orders": sorted({sources.get(cid, {}).get("order_no", cid) for cid in member_ids}),
            "source_directories": sorted(
                {sources.get(cid, {}).get("directory", "unknown") for cid in member_ids}
            ),
            "thumbnail": thumbnail_path(key, rep),
        })

    covered_set = set(covered_ids)
    total = len(features)
    covered = len(covered_set)
    ratio_pct = round(covered / total * 100, 2) if total else 0.0

    # Top-N curve: families by member count (desc, input order breaks ties),
    # cumulative cabinet share and coverage as N grows (issue #6).
    top_n = []
    cum_ids: list[str] = []
    cum_cabinets = 0
    cum_covered = 0
    ordered = sorted(enumerate(family_entries), key=lambda t: (-t[1]["member_count"], t[0]))
    for n, (_, fam) in enumerate(ordered, 1):
        cum_ids.append(fam["family"])
        cum_cabinets += fam["member_count"]
        cum_covered += sum(len(g["members"]) for g in fam["grades"] if g["covered"])
        top_n.append({
            "n": n,
            "families": n,
            "family_ids": list(cum_ids),
            "cabinets": cum_cabinets,
            "cabinets_pct": round(cum_cabinets / total * 100, 2) if total else 0.0,
            "covered": cum_covered,
            "coverage_pct": round(cum_covered / total * 100, 2) if total else 0.0,
        })

    # Cross-month comparison: group cabinets by source directory (跨月).
    by_directory: dict[str, list[str]] = {}
    for cid in features:
        by_directory.setdefault(sources.get(cid, {}).get("directory", "unknown"), []).append(cid)
    monthly = {}
    for directory in sorted(by_directory):
        ids = by_directory[directory]
        dir_covered = sum(1 for cid in ids if cid in covered_set)
        monthly[directory] = {
            "cabinets": len(ids),
            "covered": dir_covered,
            "coverage_pct": round(dir_covered / len(ids) * 100, 2) if ids else 0.0,
            "families": sum(1 for f in family_entries if set(f["members"]) & set(ids)),
        }

    return {
        "schema": REPORT_SCHEMA,
        "totals": {
            "cabinets": total,
            "families": len(family_entries),
            "grades": sum(len(f["grades"]) for f in family_entries),
            "covered_cabinets": covered,
            "uncovered_cabinets": total - covered,
        },
        "coverage": {
            "total_cabinets": total,
            "covered_cabinets": covered,
            "ratio_pct": ratio_pct,
            "covered_cabinet_ids": sorted(covered_set),
            "uncovered_cabinet_ids": sorted(set(features) - covered_set),
        },
        "verdict": judge_coverage(ratio_pct, config),
        "top_n": top_n,
        "monthly": monthly,
        "families": family_entries,
    }


def _fmt_range(rng) -> str:
    """min-max range as compact markdown cell text."""
    if rng is None:
        return "-"
    lo, hi = rng["min"], rng["max"]
    return f"{lo:g}" if lo == hi else f"{lo:g} - {hi:g}"


def render_markdown(report: dict) -> str:
    """Render the human-readable ``report.md`` (issue #6 deliverable 4).

    Conclusion first: verdict level, coverage figure and thresholds lead
    the document; monthly comparison, Top-N curve and the family detail
    tables (with relative thumbnail links) follow.
    """
    v = report["verdict"]
    cov = report["coverage"]
    totals = report["totals"]
    lines: list[str] = []
    lines.append("# 相似性审计报告")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append(
        f"**{v['conclusion']}**（判定级别 `{v['level']}`）—— "
        f"柜体级参数化覆盖率 **{cov['ratio_pct']:.1f}%**"
        f"（{cov['covered_cabinets']}/{cov['total_cabinets']} 台）。"
    )
    lines.append("")
    lines.append(
        f"判定阈值：成立 ≥ {v['thresholds']['pass_min_pct']:g}%，"
        f"条件成立 {v['thresholds']['conditional_min_pct']:g}%–{v['thresholds']['pass_min_pct']:g}%，"
        f"不成立 < {v['thresholds']['conditional_min_pct']:g}%。{VERDICT_NOTES[v['level']]}"
    )
    lines.append("")
    lines.append(
        f"共 {totals['cabinets']} 台柜体，聚为 {totals['families']} 个家族、"
        f"{totals['grades']} 个参数档；覆盖 {totals['covered_cabinets']} 台，"
        f"未覆盖 {totals['uncovered_cabinets']} 台。"
    )
    lines.append("")

    if report["monthly"]:
        lines.append("## 跨月对比（按来源目录）")
        lines.append("")
        lines.append("| 来源目录 | 柜体数 | 覆盖柜体 | 覆盖率 | 家族数 |")
        lines.append("|---|---:|---:|---:|---:|")
        for directory, m in report["monthly"].items():
            lines.append(
                f"| {directory} | {m['cabinets']} | {m['covered']} | "
                f"{m['coverage_pct']:.1f}% | {m['families']} |"
            )
        lines.append("")

    if report["top_n"]:
        lines.append("## Top-N 模板覆盖率曲线")
        lines.append("")
        lines.append(
            "家族按柜体数降序累计。维护前 N 个模板（家族）可获得："
        )
        lines.append("")
        lines.append("| Top-N | 累计柜体 | 柜体占比 | 累计覆盖 | 覆盖率 |")
        lines.append("|---|---:|---:|---:|---:|")
        for row in report["top_n"]:
            lines.append(
                f"| {row['n']} | {row['cabinets']} | {row['cabinets_pct']:.1f}% | "
                f"{row['covered']} | {row['coverage_pct']:.1f}% |"
            )
        lines.append("")

    lines.append("## 家族明细")
    lines.append("")
    lines.append("族名为占位，待人工从 GLOSSARY 柜型标签词表取值命名。")
    lines.append("")
    lines.append(
        "| 家族 | 柜型命名 | 成员数 | 代表柜 | 宽 min-max | 高 min-max | 深 min-max "
        "| 参数档数 | 样本单号 | 来源目录 | 缩略图 |"
    )
    lines.append("|---|---|---:|---|---|---|---|---:|---|---|---|")
    for fam in report["families"]:
        label = "待人工命名" if fam["label_pending"] else fam["label"]
        lines.append(
            f"| {fam['family']} | {label} | {fam['member_count']} | {fam['representative']} "
            f"| {_fmt_range(fam['width'])} | {_fmt_range(fam['height'])} | {_fmt_range(fam['depth'])} "
            f"| {len(fam['grades'])} | {', '.join(fam['sample_orders'])} "
            f"| {', '.join(fam['source_directories'])} "
            f"| ![{fam['family']}]({fam['thumbnail']}) |"
        )
    lines.append("")

    lines.append("### 参数档明细")
    lines.append("")
    for fam in report["families"]:
        lines.append(f"- **{fam['family']}**（代表柜 {fam['representative']}）:")
        for g in fam["grades"]:
            mark = "覆盖" if g["covered"] else "未覆盖"
            lines.append(
                f"  - `{g['grade']}`（{g['member_count']} 台，{mark}）: "
                f"{', '.join(g['members'])}"
            )
    lines.append("")

    lines.append("## 图片目录结构与抽查方法")
    lines.append("")
    lines.append(
        f"每台柜体导出一张 JPG（质量 {IMAGE_QUALITY}），按"
        f" `{FAMILIES_DIR}/<族ID>/<参数档ID>/<柜ID>.jpg` 归档，"
        "可直接用资源管理器浏览验证聚类与分档："
    )
    lines.append("")
    lines.append(
        f"- 柜ID 文件名为 `<单号>_<柜序号>.jpg`，含来源单号/stem，可回溯到订单图纸；"
        f"- 未归入任何可复现参数档（单件档或超容差档）的柜体在 "
        f"`{FAMILIES_DIR}/{UNGRADED_DIR}/`；"
        f"- 转换/提取失败的图纸在 `{FAMILIES_DIR}/{FAILED_DIR}/<文件名>.txt`，"
        "内容为失败原因（目录、文件名、错误信息）。"
    )
    lines.append("")
    lines.append(
        "抽查方法：任选一个参数档目录，肉眼比对该档内柜体图片是否确实同构且同尺寸档；"
        f"再翻 `{UNGRADED_DIR}/` 确认未覆盖判定合理、`{FAILED_DIR}/` 确认失败原因可接受。"
        "跑批默认导出图片，`--no-export-images` 可关闭。"
    )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, out_dir, fronts: dict | None = None) -> dict:
    """Write ``report.json`` + ``report.md`` into ``out_dir``.

    When ``fronts`` (cabinet id -> :class:`audit_tool.extract.CabinetFront`)
    is given, each family's representative is rendered to
    ``thumbnails/`` so the Markdown links resolve. Returns the artifact
    paths.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path = out / "report.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")

    thumbnails = []
    if fronts:
        from audit_tool.cluster import RENDER_SIZE
        from audit_tool.render import render_cabinet

        (out / THUMBNAIL_DIR).mkdir(exist_ok=True)
        for fam in report["families"]:
            front = fronts[fam["representative"]]
            path = out / fam["thumbnail"]
            render_cabinet(front, size=RENDER_SIZE).save(path)
            thumbnails.append(str(path))

    return {"json": str(json_path), "md": str(md_path), "thumbnails": thumbnails}
