# 相似性审计工具（audit）

以真实订单图纸验证"图库 + 插件"立项前提：输入一个或多月的订单图纸目录，
自动把每张图中的单元柜**提取渲染 → pHash 粗聚类 → 特征精分档**，输出
柜体级参数化覆盖率报告（JSON + Markdown + 家族缩略图 + 全部中间产物）。

整条管道对外的唯一入口就是本 CLI（`python -m audit`）；适配器注入点也只在这里暴露。

## 安装

Windows / Python 3.12+：

```powershell
cd audit
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"   # 依赖 ezdxf / pillow / numpy / imagehash；dev 附加组含 pytest
```

验证（`python -m audit` 从 `audit/` 的上级目录解析 `audit` 包）：

```powershell
cd ..
audit\.venv\Scripts\python.exe -m audit --help
```

## ODA File Converter（生产环境需要）

真实订单是 DWG，需要 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
（Open Design Alliance 官方免费工具）做 DWG→DXF 转换：

1. 下载安装后记下 `ODAFileConverter.exe` 的完整路径；
2. 运行时用 `--oda-path` 传入，或写进配置文件 `[adapter] path`。

**没有 ODA / 输入已是 DXF 时**：加 `--adapter dxf` 直接读 DXF（测试即用此路），
全程不依赖任何外部二进制。

## 用法

```powershell
# 生产：ODA 转换 DWG，多月输入做跨月对比
python -m audit --input D:\订单\2026-01 --input D:\订单\2026-03 --output D:\审计结果 --oda-path "C:\...\ODAFileConverter.exe"

# 无 ODA 环境：DXF 直读
python -m audit --input .\fixtures\jan --output .\out --adapter dxf

# 自定义容差/阈值
python -m audit --input D:\订单\2026-01 --output D:\审计结果 --config audit\config.example.toml --adapter dxf
```

参数：

| 参数 | 说明 |
|---|---|
| `--input DIR` | 订单图纸目录（`.dxf`/`.dwg`），可多次传入对比多月；目录下无图纸时会向下扫一层子目录（月名子目录）。目录名作为跨月对比的来源标识 |
| `--output DIR` | 报告输出目录（自动创建） |
| `--config FILE` | TOML 配置文件，默认 `audit/config.example.toml`（带注释，所有键可省略） |
| `--adapter {dxf,oda}` | 转换适配器，默认 `oda`；`dxf` 为 DXF 直读（无 ODA 环境与测试） |
| `--oda-path EXE` | ODA File Converter 路径（`--adapter oda` 时必填，或写在配置 `[adapter] path`） |
| `--no-export-images` | 不导出 `families/` 分类图片目录（默认导出 JPG+DXF，见下；此开关同时关两者） |

### 输出目录结构（证据可追溯）

```
out/
├── report.json                  # 结构化报告：家族清单、尺寸 min-max、覆盖率、Top-N 曲线、跨月对比、判定结论
├── report.md                    # 人读报告（结论置顶，含缩略图链接与图片抽查说明）
├── thumbnails/                  # 每个家族代表柜缩略图
├── families/                    # 分类图片（issue #9，可直接人眼浏览验证）
│   ├── <族ID>/<参数档ID>/<柜ID>.jpg + <柜ID>.dxf
│   ├── _未归类/<柜ID>.jpg|.dxf  # 未归入任何可复现参数档的柜体
│   └── _失败/<文件名>.txt       # 转换/提取失败的图纸及原因（已转换出 DXF 的附副本）
├── renders/                     # 每台单元柜的渲染图（中间产物）
└── intermediate/
    ├── hashes.json              # 柜 -> pHash（中间产物）
    ├── clusters.json            # 粗聚类结果 + 完整汉明距离矩阵（中间产物）
    ├── features.json            # 柜 -> 结构特征向量（中间产物）
    ├── grades.json              # 族 -> 参数档划分（中间产物）
    └── processing.json          # 每个图纸文件的处理记录（含失败原因）
```

`families/` 里每台柜体一对同名文件：JPG 渲染图（质量 85）+ DXF 几何图，
文件名为 `<单号>_<柜序号>.jpg|.dxf`（柜ID 含来源单号/stem，可回溯到订单图纸；
DXF 为该柜提取图元的独立文件，仅含普通二维几何，不含块引用）。
抽查方法：任选一个参数档目录，肉眼比对该档内柜体 JPG 是否确实同构同尺寸档，
需核对几何时用 CAD 打开同名 DXF；再翻 `_未归类/` 确认未覆盖判定合理、
`_失败/` 确认失败原因可接受（`report.md` 末尾也附有此说明）。

## 配置（audit/config.example.toml）

| 节 | 键 | 默认 | 说明 |
|---|---|---|---|
| `[render]` | `size` / `grid_cols` / `grid_rows` | 512 / 4 / 10 | 渲染边长与占用网格；为夹具实证参数，改动前先跑测试 |
| `[cluster]` | `hash_size` / `threshold` | 12 / 32 | pHash 边长（12→144 bit）与汉明距离阈值 |
| `[grading]` | `width_tolerance` / `height_tolerance` / `depth_tolerance` | 200 / 100 / 100 | L3 尺寸分箱容差（mm） |
| `[grading]` | `grid_iou_threshold` | 0.85 | 布局占用网格 IoU 阈值 |
| `[report]` | `pass_threshold` / `conditional_threshold` | 70 / 40 | 覆盖率判定阈值（%） |
| `[report]` | `export_images` | true | 是否导出 `families/` 分类图片目录（JPG+DXF，issue #9） |
| `[adapter]` | `path` | （无） | ODA File Converter 路径 |

## 判定标准

核心口径是**柜体级参数化覆盖率**：一台订单柜"被覆盖"指它所在参数档
（拓扑字段全等 + 尺寸差在分箱容差内 + 布局 IoU 达标）至少有另一台柜共享，
且档内最大尺寸差不超过分箱容差——即能由同一模板纯改参数还原。

| 覆盖率 | 结论 | 含义 |
|---|---|---|
| ≥ 70% | **成立** | 项目可以立项 |
| 40% ~ 70% | **条件成立** | 仅对高频家族建库，低频品类维持现状手绘 |
| < 40% | **不成立** | 不建议启动图库/插件建设 |

`report.md` 结论置顶；跨月对比表回答"相似性是否稳定规律"；Top-N 曲线回答
"维护多少个模板能到多少覆盖率"。族名为占位，需人工从 GLOSSARY 柜型标签词表取值命名。

## 测试

```powershell
cd audit
.venv\Scripts\python -m pytest
```

测试全部经由唯一 seam（CLI）做已知答案断言，夹具由 ezdxf 程序构造，
不依赖 ODA/DWG（spec 测试决策）。
