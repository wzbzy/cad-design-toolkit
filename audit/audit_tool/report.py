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

from dataclasses import dataclass

from audit_tool.grade import DEFAULT_GRADING_CONFIG, GradingConfig, grade_families

__all__ = [
    "DEFAULT_REPORT_CONFIG",
    "REPORT_SCHEMA",
    "ReportConfig",
    "build_report",
    "judge_coverage",
    "render_markdown",
    "write_report",
]

REPORT_SCHEMA = "audit-report/1"

VERDICT_CONCLUSIONS = {
    "pass": "成立",
    "conditional": "条件成立",
    "fail": "不成立",
}


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
        fam_covered = 0
        for g in grades[key]["grades"]:
            g_members = [features[cid] for cid in g["members"]]
            is_covered = len(g_members) >= 2 and _grade_spread_within_tolerance(g_members, config)
            if is_covered:
                covered_ids.extend(g["members"])
                fam_covered += len(g["members"])
            fam_grades.append({**g, "member_count": len(g["members"]), "covered": is_covered})

        widths = [f.width for f in members]
        heights = [f.height for f in members]
        depths = [f.depth for f in members if f.depth is not None]
        rep = fam["representative"]
        src = sources.get(rep, {})
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
