"""CLI entry point -- the single seam of the audit tool (issue #7).

The only public entry of the whole pipeline (issue #1 单一 seam):

    python -m audit --input ORDERS/JAN --input ORDERS/MAR --output REPORT

Inputs are order drawing directories (one per month; a directory that
itself only contains month subdirectories is expanded one level). Output
is an audit report directory: ``report.json`` + ``report.md`` + family
thumbnails, plus every intermediate product (per-cabinet renders, pHash
values, clustering, features, grades) so any verdict can be traced to
its evidence (spec user story 11).

The conversion adapter is injected here (issue #1 转换适配器注入):
``--adapter oda`` (default, production) shells out to the ODA File
Converter; ``--adapter dxf`` reads DXF directly (no external binary --
tests and ODA-free environments). Tolerances and thresholds come from a
TOML config file, defaulting to the annotated ``config.example.toml``
next to this package.

This module is thin on purpose: orchestration lives in
:func:`run_pipeline`, argument parsing in :func:`main`, config parsing
in :class:`Settings`/:func:`load_settings`. Behavior is contract-tested
end to end in ``tests/test_cli.py`` -- nothing in this module is tested
directly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from audit_tool.cluster import (
    DEFAULT_HASH_SIZE,
    DEFAULT_THRESHOLD,
    RENDER_SIZE,
    cluster_hashes,
    phash_image,
)
from audit_tool.converters import ConversionAdapter, DxfDirectAdapter, OdaFileConverterAdapter
from audit_tool.extract import CabinetFront, extract_cabinets
from audit_tool.grade import DEFAULT_GRADING_CONFIG, GradingConfig, extract_features
from audit_tool.images import export_family_images
from audit_tool.render import DEFAULT_GRID_SHAPE, render_cabinet
from audit_tool.report import DEFAULT_REPORT_CONFIG, ReportConfig, build_report, write_report

# The annotated default config ships with the project (audit/ root).
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.example.toml"

DRAWING_SUFFIXES = (".dxf", ".dwg")

INTERMEDIATE_DIR = "intermediate"


@dataclass(frozen=True)
class Settings:
    """Everything the pipeline takes from the config file + CLI defaults.

    Bundles the library config objects (:class:`GradingConfig`,
    :class:`ReportConfig`) with the render/cluster parameters the CLI
    owns. Defaults mirror the empirically validated fixture parameters
    (512 px render, hash_size 12, distance threshold 32).
    """

    render_size: tuple[int, int] = RENDER_SIZE
    grid_shape: tuple[int, int] = DEFAULT_GRID_SHAPE  # (cols, rows)
    hash_size: int = DEFAULT_HASH_SIZE
    cluster_threshold: int = DEFAULT_THRESHOLD
    grading: GradingConfig = DEFAULT_GRADING_CONFIG
    report: ReportConfig = DEFAULT_REPORT_CONFIG
    export_images: bool = True  # families/ JPG tree (issue #9); --no-export-images / [report] export_images
    oda_path: str | None = None


def load_settings(config_path: str | None) -> Settings:
    """Parse the TOML config into :class:`Settings`.

    Unknown keys and absent sections are ignored / defaulted, so a
    minimal ``[report]``-only file (as in the tests) is valid.
    """
    if config_path is None:
        return Settings()
    data = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))

    render = data.get("render", {})
    size = int(render.get("size", Settings.render_size[0]))
    cluster = data.get("cluster", {})
    grading = GradingConfig(
        width_tolerance=float(data.get("grading", {}).get("width_tolerance",
                                                          DEFAULT_GRADING_CONFIG.width_tolerance)),
        height_tolerance=float(data.get("grading", {}).get("height_tolerance",
                                                           DEFAULT_GRADING_CONFIG.height_tolerance)),
        depth_tolerance=float(data.get("grading", {}).get("depth_tolerance",
                                                          DEFAULT_GRADING_CONFIG.depth_tolerance)),
        grid_iou_threshold=float(data.get("grading", {}).get("grid_iou_threshold",
                                                             DEFAULT_GRADING_CONFIG.grid_iou_threshold)),
    )
    report_section = data.get("report", {})
    return Settings(
        render_size=(size, size),
        grid_shape=(
            int(render.get("grid_cols", DEFAULT_GRID_SHAPE[0])),
            int(render.get("grid_rows", DEFAULT_GRID_SHAPE[1])),
        ),
        hash_size=int(cluster.get("hash_size", DEFAULT_HASH_SIZE)),
        cluster_threshold=int(cluster.get("threshold", DEFAULT_THRESHOLD)),
        grading=grading,
        report=ReportConfig(
            pass_threshold=float(report_section.get("pass_threshold",
                                                    DEFAULT_REPORT_CONFIG.pass_threshold)),
            conditional_threshold=float(
                report_section.get("conditional_threshold",
                                   DEFAULT_REPORT_CONFIG.conditional_threshold)
            ),
            grading=grading,
        ),
        export_images=bool(report_section.get("export_images", True)),
        oda_path=data.get("adapter", {}).get("path"),
    )


def _unique_label(label: str, used: set[str]) -> str:
    """Directory label for the 跨月 comparison; deduplicated on collision."""
    candidate, n = label, 1
    while candidate in used:
        n += 1
        candidate = f"{label}-{n}"
    used.add(candidate)
    return candidate


def _drawing_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for suffix in DRAWING_SUFFIXES:
        files.extend(directory.glob(f"*{suffix}"))
    return sorted(files, key=lambda p: p.name.lower())


def discover_drawings(inputs: list[str]) -> list[tuple[str, Path]]:
    """Resolve ``--input`` directories to ``(directory label, file)`` pairs.

    Each ``--input`` is scanned directly for ``*.dxf``/``*.dwg``; when it
    holds none, its immediate subdirectories are scanned (one level) so a
    single ``--input ORDERS`` with ``JAN/``, ``MAR/``... month folders
    works too. Labels come from the directory name and feed the report's
    cross-month (跨月) comparison.
    """
    pairs: list[tuple[str, Path]] = []
    used: set[str] = set()
    for raw in inputs:
        directory = Path(raw)
        if not directory.is_dir():
            raise NotADirectoryError(f"input directory not found: {directory}")
        sources = [(directory, _drawing_files(directory))]
        if not sources[0][1]:
            sources = [(sub, _drawing_files(sub))
                       for sub in sorted(directory.iterdir()) if sub.is_dir()]
        for subdir, files in sources:
            if not files:
                continue
            label = _unique_label(subdir.name, used)
            pairs.extend((label, f) for f in files)
    return pairs


def _safe_stem(name: str) -> str:
    """Filesystem-safe form of a cabinet id / drawing name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def run_pipeline(inputs: list[str], out_dir, adapter: ConversionAdapter,
                 settings: Settings, log=print) -> dict:
    """Assemble the whole audit pipeline (issue #1 管道分段).

    转换 -> 提取渲染 -> 哈希粗聚类 -> 特征精分档 -> 报告. Returns the
    report dict; every intermediate product is written under ``out_dir``
    for evidence tracing:

    - ``renders/<cabinet>.png``      per-cabinet render
    - ``intermediate/hashes.json``   cabinet id -> pHash hex
    - ``intermediate/clusters.json`` families + full distance matrix
    - ``intermediate/features.json`` cabinet id -> feature vector
    - ``intermediate/grades.json``   family -> parametric grades
    - ``intermediate/processing.json`` per-file processing record
    - ``families/``                  browsable per-cabinet JPG + same-named
      DXF pairs grouped by family/parametric grade (issue #9;
      ``--no-export-images`` skips it)
    """
    out = Path(out_dir)
    renders_dir = out / "renders"
    inter_dir = out / INTERMEDIATE_DIR
    renders_dir.mkdir(parents=True, exist_ok=True)
    inter_dir.mkdir(parents=True, exist_ok=True)

    pairs = discover_drawings(inputs)

    fronts: dict[str, CabinetFront] = {}
    sources: dict[str, dict] = {}
    failed: list[dict] = []
    files_seen = 0
    for directory_label, path in pairs:
        files_seen += 1
        dxf = None
        try:
            dxf = adapter.to_dxf(path)
            cabinets = extract_cabinets(dxf)
        except Exception as exc:  # noqa: BLE001 - one bad sheet must not kill a batch
            record = {"file": path.name, "directory": directory_label, "error": str(exc)}
            if dxf is not None:
                # the sheet converted; keep the dxf path so the families
                # export can copy it next to the failure note (issue #9)
                record["dxf"] = str(dxf)
            failed.append(record)
            log(f"FAILED  {directory_label}/{path.name}: {exc}")
            continue
        for cabinet in cabinets:
            cabinet_id = f"{path.stem}#{cabinet.index}"
            img = render_cabinet(cabinet, size=settings.render_size)
            img.save(renders_dir / f"{_safe_stem(cabinet_id)}.png")
            fronts[cabinet_id] = cabinet
            sources[cabinet_id] = {
                "order_no": path.stem,
                "drawing": f"{directory_label}/{path.name}",
                "directory": directory_label,
            }

    processing = {
        "adapter": type(adapter).__name__,
        "inputs": [str(Path(p)) for p in inputs],
        "files_processed": files_seen,
        "files_ok": files_seen - len(failed),
        "cabinets": len(fronts),
        "failed": failed,
    }
    if not fronts:
        raise RuntimeError(
            "no unit cabinets extracted from the given inputs "
            f"({files_seen} file(s), {len(failed)} failed); nothing to audit"
        )

    hashes: dict[str, object] = {}
    images: dict[str, object] = {}
    for cid, cabinet in fronts.items():
        img = render_cabinet(cabinet, size=settings.render_size)
        images[cid] = img
        hashes[cid] = phash_image(img, hash_size=settings.hash_size)
    cluster = cluster_hashes(hashes, threshold=settings.cluster_threshold)
    features = {cid: extract_features(cid, c, grid_shape=settings.grid_shape)
                for cid, c in fronts.items()}

    report = build_report(cluster, features, sources, settings.report)

    (inter_dir / "hashes.json").write_text(
        json.dumps({cid: str(h) for cid, h in hashes.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (inter_dir / "clusters.json").write_text(
        json.dumps(cluster, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (inter_dir / "features.json").write_text(
        json.dumps({cid: f.to_dict() for cid, f in features.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (inter_dir / "grades.json").write_text(
        json.dumps(
            {fam["family"]: {"grades": [{"grade": g["grade"], "members": g["members"],
                                         "covered": g["covered"]}
                                        for g in fam["grades"]]}
             for fam in report["families"]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    (inter_dir / "processing.json").write_text(
        json.dumps(processing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_report(report, out, fronts)

    if settings.export_images:
        exported = export_family_images(report, out, images=images, fronts=fronts,
                                        failed=failed)
        log(f"families images written to {exported['dir']} "
            f"({len(exported['jpgs'])} jpg + dxf, {len(exported['failed'])} failed note(s))")

    v = report["verdict"]
    log(
        f"{report['totals']['cabinets']} cabinets -> {report['totals']['families']} families, "
        f"coverage {report['coverage']['ratio_pct']:.1f}% -> {v['conclusion']} ({v['level']})"
    )
    log(f"report written to {out}")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit",
        description=(
            "相似性审计：把一个或多月订单图纸目录跑完整条审计管道"
            "（转换 -> 提取渲染 -> pHash 粗聚类 -> 特征精分档 -> 报告），"
            "输出 report.json / report.md、家族缩略图、按族/参数档归档的"
            "柜体 JPG 图片目录与全部中间产物。"
        ),
        epilog=(
            "示例：python -m audit --input 订单/2026-01 --input 订单/2026-03 "
            "--output 审计结果 --adapter oda --oda-path "
            r'"C:\ODA\ODAFileConverter.exe"'
        ),
    )
    parser.add_argument(
        "--input", action="append", required=True, metavar="DIR",
        help="订单图纸目录（.dxf/.dwg），可多次传入对比多月；"
             "目录下无图纸时会向下扫一层子目录（月名子目录）",
    )
    parser.add_argument(
        "--output", required=True, metavar="DIR",
        help="审计报告输出目录（自动创建；已有内容会被覆盖）",
    )
    parser.add_argument(
        "--config", default=None, metavar="FILE",
        help=f"容差/阈值 TOML 配置文件（默认：{DEFAULT_CONFIG_PATH.name}，"
             f"位于 {DEFAULT_CONFIG_PATH.parent}）",
    )
    parser.add_argument(
        "--adapter", choices=("dxf", "oda"), default="oda",
        help="DWG->DXF 转换适配器：oda=ODA File Converter（生产默认），"
             "dxf=直接读 DXF（无 ODA 环境与测试用）；默认 oda",
    )
    parser.add_argument(
        "--oda-path", default=None, metavar="EXE",
        help="ODA File Converter 可执行文件路径（--adapter oda 时必填，"
             "或写在配置文件 [adapter] path）",
    )
    parser.add_argument(
        "--no-export-images", action="store_true",
        help="不导出 families/ 分类图片目录（柜体 JPG 按族/参数档归档，默认导出）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry; returns the process exit code (0 ok, 1 runtime, 2 usage)."""
    parser = build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse usage errors / --help: normalize to int
        return int(exc.code or 0)

    config_path = args.config
    if config_path is None and DEFAULT_CONFIG_PATH.is_file():
        config_path = str(DEFAULT_CONFIG_PATH)
    settings = load_settings(config_path)
    if args.no_export_images:
        settings = replace(settings, export_images=False)

    if args.adapter == "oda":
        oda_path = args.oda_path or settings.oda_path
        if not oda_path:
            print(
                "usage: audit [-h] --input DIR --output DIR [--config FILE] "
                "[--adapter {dxf,oda}] [--oda-path EXE]\n"
                "audit: error: --adapter oda needs the ODA File Converter path: "
                "pass --oda-path or set [adapter] path in the config file "
                "(use --adapter dxf for DXF-only input without ODA)",
                file=sys.stderr,
            )
            return 2
        adapter = OdaFileConverterAdapter(oda_path)
    else:
        adapter = DxfDirectAdapter()

    try:
        run_pipeline(args.input, args.output, adapter, settings)
    except (RuntimeError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
