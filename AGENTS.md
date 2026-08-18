# AGENTS.md

**Updated:** 2026-08-18 · **Base commit:** `b2ff806` · **Branch:** `main`

本文件给接手本仓库的 AI Agent 使用。改动前先确认当前任务的完成标准，改动后必须验证。

## OVERVIEW

Flomo ZIP/HTML 导出 → LLM 可读 chunk → 完整快照发布的本地 Python 流水线。5 个处理 stage，加一条增量收件/发布工作流；纯本地文件，无数据库，无 Web 服务。栈：Python ≥3.11 + BeautifulSoup4 + Pillow + LM Studio VLM（可选）。

## STRUCTURE

```
flomo-transcriber/
├── src/flomo_pipeline/          # ★ Python 主包 (import: flomo_pipeline)
│   ├── workflow.py              #   核心编排器: run_action(), 5 种操作
│   ├── common/                  #   共享: frozen dataclass, JSONL I/O, ValidationReport
│   ├── extract/                 #   Stage 1: Flomo HTML → raw JSONL (4 files, 664 lines)
│   ├── enrich/                  #   Stage 2: VLM 图片增强 (10 files, 1494 lines) ★ 最复杂
│   │   └── providers/           #     LM Studio / mock provider 工厂
│   ├── merge/                   #   Stage 3: 按月合并 (4 files, 515 lines)
│   ├── chunk/                   #   Stage 4: LLM chunk 组装, 不调模型 (5 files, 795 lines)
│   ├── report/                  #   Stage 5: 可选 LLM 报告 (8 files, 653 lines)
│   │   └── providers/           #     LM Studio / mock report provider 工厂
│   ├── sync/                    #   ZIP 安全收件、导入 manifest、快照发布
│   └── preview/                 #   死目录 — 无 .py 文件, 无 __init__.py
├── scripts/                     # CLI 入口 (17 .py): guide.py ★ 主入口, stage 脚本, validator 脚本
├── tests/                       # pytest (11 files, 84 tests) — no __init__.py
├── gui/                         # Tauri v2 桌面 GUI (React 18 + Rust, 独立构建)
├── raw/    store/    monthly/   # [gitignored] 流水线数据目录
├── llm_chunks/    reports/      # [gitignored] 最终输出
├── pyproject.toml               # hatchling build, ruff/mypy/pytest 配置
└── Makefile                     # 18 个便捷 target
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| 用户入口 / 工作流 | `scripts/guide.py` → `src/flomo_pipeline/workflow.py` | 5 种操作: first / daily / probe / retry / import |
| 增量收件 / 发布 | `src/flomo_pipeline/sync/` | ZIP 安全检查、导入状态、快照清单与 `latest.json` |
| Stage 1: HTML 解析 | `src/flomo_pipeline/extract/parser.py` | `FlomoParser.parse_all()`, `_html_to_markdown()` |
| Stage 2: VLM 调用 | `src/flomo_pipeline/enrich/providers/lmstudio_openai.py` | 整图 → 切片 fallback, retry 逻辑 |
| Stage 2: 图片切片 | `src/flomo_pipeline/enrich/image_slicer.py` | `create_image_slices()`, 长截图降级 |
| Stage 3: 月度合并 | `src/flomo_pipeline/merge/runner.py` | `MonthlyMergeRunner.run()` |
| Stage 4: chunk 装箱 | `src/flomo_pipeline/chunk/runner.py` | ~1200 tokens/chunk, memo 不可拆分 |
| Stage 5: LLM 报告 | `src/flomo_pipeline/report/runner.py` | 可选 stage, 不在默认 guide.py flow 中 |
| JSONL 读写 | `src/flomo_pipeline/common/io.py` | `write_jsonl(atomic=True)`, `read_jsonl()` |
| 校验框架 | `src/flomo_pipeline/common/validation.py` | `Severity`, `Violation`, `ValidationReport` |
| 数据模型 | `src/flomo_pipeline/common/models.py` | `MemoRecord`, `ImageRecord` (frozen dataclass) |
| 测试入口 | `tests/conftest.py` | `sample_raw_root` fixture, `run_fake_lmstudio_server` |
| GUI 后端 | `gui/src-tauri/src/lib.rs` | 8 个 Tauri command |
| GUI 前端 | `gui/src/App.tsx` | React SPA, 5 操作 + inbox queue + settings |
| 桌面打包 | `scripts/build_gui_sidecar.py` → `gui/` npm scripts | PyInstaller → NSIS |
| 开源安全检查 | `scripts/check_open_source_readiness.py` | 数据泄露 / API key / 个人路径 |
| Makefile 快捷入口 | `Makefile` | `make test`, `make enrich-lmstudio`, etc. |

## CODE MAP

| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `run_action()` | function | `workflow.py:run_action` | 2 (guide.py, flomo_sidecar.py) | 核心编排入口 |
| `WorkflowPaths` | frozen dataclass | `workflow.py:WorkflowPaths` | — | 路径配置 |
| `FlomoParser` | class | `extract/parser.py` | — | HTML → 结构化记录 |
| `ImageEnrichmentRunner` | class | `enrich/runner.py` | 2 (scripts) | Stage 2 批处理引擎 |
| `LMStudioEnrichmentProvider` | class | `enrich/providers/lmstudio_openai.py` | 1 (build_provider) | LM Studio VLM 适配器 |
| `EnrichmentProvider` | Protocol | `enrich/provider.py:EnrichmentProvider` | provider implementations | VLM provider 接口 |
| `MonthlyMergeRunner` | class | `merge/runner.py` | 1 (script) | Stage 3 合并引擎 |
| `ChunkBuildRunner` | class | `chunk/runner.py` | 1 (script) | Stage 4 chunk 构建器 |
| `ReportBuildRunner` | class | `report/runner.py` | 1 (script) | Stage 5 报告生成器 |
| `ReportProvider` | Protocol | `report/provider.py` | — | LLM report provider 接口 |
| `ImportManifestStore` | class | `sync/importer.py` | import workflow | ZIP 哈希、状态和建议日期持久化 |
| `publish_chunks_snapshot()` | function | `sync/publisher.py` | import workflow | 完整快照、文件哈希、原子 latest 指针 |
| `ValidationReport` | frozen dataclass | `common/validation.py` | all validators | 校验结果容器 |
| `write_jsonl()` | function | `common/io.py` | all runners | 原子 JSONL 写入 |

## 先读（Agent 接手时）

1. `README.md` 或 `README.en.md`
2. `pyproject.toml`
3. 子模块 AGENTS.md（按需）：`src/flomo_pipeline/common/` `extract/` `enrich/` `merge/` `chunk/` `report/` `sync/` `gui/` `scripts/`
4. 相关 stage 的 `src/flomo_pipeline/<stage>/`
5. 对应测试文件

## 当前边界

- Stage 1 extract：`raw/ -> store/*.raw.jsonl`
- Stage 2 enrich：`store/image.raw.jsonl -> store/image.enriched.jsonl`
- Stage 3 merge：`store/*.jsonl -> monthly/YYYY-MM.enriched.jsonl`
- Stage 4 chunk：`monthly/YYYY-MM.enriched.jsonl -> llm_chunks/YYYY-MM/*.json`
- Stage 5 report：`llm_chunks/YYYY-MM/*.json -> reports/YYYY-MM.report.*`
- Import/publish：`Flomo ZIP -> raw/ + store/ + monthly/ + llm_chunks/ -> flomo-context/snapshots/`

`common/` 只放跨 stage 共享的基础工具（文件读写、校验报告）。**不要把 stage 专属业务规则搬进 `common/`。**

普通用户主入口是 `python scripts/guide.py`。单阶段脚本和 bat/sh 脚本保留给排错、高级参数和自动化使用。

## CONVENTIONS

**工具链**（`pyproject.toml` 统一配置，无独立 config 文件）：
- **Python**: ≥3.11, `from __future__ import annotations` 全局使用
- **Lint**: Ruff — line-length=100, rules: E/F/I/N/UP/B/SIM/TCH
- **Type**: mypy `strict=true`, `explicit_package_bases=true`, mypy_path=["src"]
- **Test**: pytest — testpaths=["tests"], pythonpath=["src"], 无标记, 无 coverage 插件
- **Build**: hatchling, wheel target `packages=["src/flomo_pipeline"]`
- **无** `.editorconfig`, `.pre-commit-config.yaml`, `ruff.toml`, `tox.ini`

**代码风格**：
- 公开名 `flomo-transcriber`, import 名 `flomo_pipeline`（向下兼容）
- 所有数据模型使用 frozen dataclass
- `to_plain_dict()` 是唯一序列化路径
- JSONL 读用 `split("\n")` 而非 `splitlines()`（Unicode 行分隔符安全）
- 每个 stage 都有 validator，遵循 `ValidationReport` 接口

**测试模式**：
- 11 个测试文件, 84 个测试函数
- 无外部 test fixture 文件 — 所有测试数据用 `tmp_path` 程序生成
- Mock 只用 pytest 内置 `monkeypatch` + fake provider 类，不用 `unittest.mock`
- 集成测试集中在 `tests/test_cli.py`（subprocess 方式）
- 调试时先跑相关 stage 测试文件, 交付前跑全量

## ANTI-PATTERNS（改动规则）

- 真实 Flomo 导出、图片、生成的 JSONL、chunks、reports、日志和 `.env` **不得进入 Git。**
- Stage 1 raw JSONL 是事实层，**下游不得改写。**
- 下游产物必须可以**重新生成**（删除后重跑得相同结果）。
- 路径字段保持**相对路径**（POSIX 正斜杠）。
- **不静默丢弃** `failed` / `skipped` 图片 — 保留在记录中带 status + error_message。
- **不在 Stage 4 调用 LLM** — Stage 4 是纯文本组装。
- **不默认重构无关 stage。**
- **不把 common/ 当业务逻辑层** — 只放跨 stage 基础设施。
- **不把 monthly/chunk/report 当 truth layer** — 都是可重新生成的派生输出。
- 不在 Stage 2 处理视频/音频，除非明确新增对应 stage 设计。
- **不在 GUI 前端直接调 Python** — 所有工作流走 Rust `invoke`。
- **不在 GUI 安装包塞真实用户数据。**
- **每次改动后必须更新 `UpdateLog.md`**，记录改动内容、原因和影响范围。
- 开发后更新相关文档；如果没有相关文档，不需要主动新增，除非任务明确要求。

## COMMANDS

```bash
# 测试与校验
python -m pytest                                    # 全量测试
python -m pytest tests/test_extract.py -v           # 单 stage 测试
python -m mypy src                                  # 严格类型检查
python scripts/check_open_source_readiness.py       # 开源安全检查（数据泄露审计）

# 用户入口
python scripts/guide.py                             # 交互式菜单
python scripts/guide.py --action first --provider lmstudio --month 2025-12
python scripts/guide.py --action import --provider lmstudio --zip <flomo.zip> --publish-root flomo-context

# 单 stage 排错（均支持 --month / --overwrite / --summary）
python scripts/extract_raw.py --raw-root raw --store-root store
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --workers 4
python scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-12
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --overwrite

# 校验（每个 stage 有对应 validator）
python scripts/validate_store.py --store-root store --summary
python scripts/validate_enriched_images.py --store-root store --summary
python scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-12 --summary
python scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --summary
python scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports --summary

# GUI（需先安装 Rust/Cargo + Node.js）
cd gui && npm install && npm run tauri dev           # 开发模式
cd gui && npm run sidecar && npm run tauri:build:nsis # 打包 NSIS 安装器
```

**Ruff 按改动范围运行**。全仓库 Ruff 仍有历史格式项；除非任务明确要求清理，不把它当作默认完成条件。

## NOTES

- **无 CI/CD** — 这是故意设计。所有校验本地运行，`check_open_source_readiness.py` 是公开发布前的门禁。
- **preview/** 是死目录（`src/flomo_pipeline/preview/` 只有 `__pycache__`）— 可能是预留或已废弃，不要往里加代码。
- **`\u2028`/`\u2029` bug (2026-06-24 修复)**: JSONL 里可能含 Unicode 行分隔符 — `common/io.py` 的 `_sanitize_jsonl_value()` 写入前转义，读取用 `split("\n")` 而非 `splitlines()`。
- **Provider 模式**: enrich 和 report 各自独立实现 `Protocol` + `build_provider()` 工厂，不共享 provider 基类。
- **GUI 双运行时**: 生产模式用 PyInstaller sidecar 二进制；开发模式 fallback 到本地 Python。
- **路径安全**: `store/images/` 下图片使用相对路径，跨平台兼容。
- **WSL 环境运行（2026-08-10 实战踩坑）**: 本机是 WSL + Windows venv 混合环境，直接跑流水线会踩三个坑：① WSL 的 `python3` 无 bs4/Pillow，必须用 `.venv/Scripts/python.exe`（Windows Python 3.13）；② WSL 内 `export FLOMO_VLM_*` **不会传给** Windows 进程（provider 报 Missing env，全部图片误标 failed），必须用 `cmd.exe /c "set FLOMO_VLM_...&& python ..."` 批处理注入；③ WSL `nohup ... &` 后台启动的 Windows 进程会随 bash 命令退出被杀（中途断在 enrich），必须用 PowerShell `Start-Process -RedirectStandardOutput` 启动。稳定模式：PowerShell Start-Process + cmd 批处理注入 env + `--workers 2`（workers=4 会触发 LM Studio HTTP 500）。LM Studio 在 WSL 内 `curl 127.0.0.1:1234` 不通属正常，用 PowerShell `Invoke-WebRequest` 验证。长图 JSON 截断报 `Unterminated string` 时用 `--slice-long-images` 重试可解。
- **重新 extract 后旧 enriched 孤儿记录**: extract 重建 `store/*.raw.jsonl` 后，若导出被替换（memo 数变化导致 image_id 漂移），`image.enriched.jsonl` 里旧月份记录会变孤儿；重跑该月 enrich 前先删掉 `month == YYYY-MM` 的旧记录（先备份），再 `--month` 重跑。
- 如果改动只影响一个 stage，可以先跑对应测试文件；最终合并前仍建议跑完整测试。
