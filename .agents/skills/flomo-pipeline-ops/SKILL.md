---
name: flomo-pipeline-ops
description: 运行、验证与排错 flomo-transcriber 本地流水线（extract / enrich / merge / chunk / report / import）。关键约定：WSL + Windows venv 混合环境必须用 .venv/Scripts/python.exe 而非 python3；LM Studio 环境变量必须经 cmd.exe 注入而非 WSL export；长任务必须用 PowerShell Start-Process 后台启动。触发词：跑流水线、重跑某月、enrich、切图、构建 chunks、发布快照、导入 flomo ZIP、导入 Notion 链接、LM Studio 报错、图片 failed、JSON 截断、孤儿记录、验证某 stage。
---

# flomo-pipeline-ops

flomo-transcriber 5-stage 流水线的运行手册。**做任何 stage 操作前先读「1. 环境判定」**，出问题时直接翻 `references/troubleshooting.md`。

## 1. 环境判定（必读）

本机是 WSL bash + Windows venv 混合环境。先判断当前 shell：

```bash
echo $0    # /bin/bash = WSL 环境；PowerShell 则直接按 Windows 习惯跑
```

WSL 环境下的铁律：

- **解释器**：一律 `.venv/Scripts/python.exe`（Windows Python 3.13，从 bash 可直接调用）。WSL 自带 `python3` 没有 bs4/Pillow。
- **快速自检**：`.venv/Scripts/python.exe -c "import bs4, PIL, flomo_pipeline; print('deps OK')"`
- **env 注入**：WSL 内 `export FLOMO_VLM_*` **不会**传给 Windows 进程 → LM Studio provider 报 Missing env、图片全被误标 failed。必须经 cmd.exe 注入（见「3. 带 VLM 的 stage」）。
- **后台长任务**：WSL `nohup ... &` 启动的 Windows 进程会随 bash 命令退出被杀（中途断在 enrich）。必须用 PowerShell `Start-Process`。

## 2. 阶段速查（无 VLM 的 stage 可直接跑）

```bash
# Stage 1 extract：raw/ -> store/*.raw.jsonl
.venv/Scripts/python.exe scripts/extract_raw.py --raw-root raw --store-root store

# Stage 3 merge：store/*.jsonl -> monthly/YYYY-MM.enriched.jsonl
.venv/Scripts/python.exe scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-12

# Stage 4 chunk：monthly/ -> llm_chunks/YYYY-MM/*.json（纯文本组装，不调 LLM）
.venv/Scripts/python.exe scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --overwrite
# 带 Notion 双向链接：
.venv/Scripts/python.exe scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --link-map store/link_map.json --overwrite
```

Notion 链接映射（先跑一次，产出 `store/link_map.json`）：

```bash
.venv/Scripts/python.exe scripts/import_notion_links.py --input <notion导出.zip|csv> --store-root store
```

## 3. 带 VLM 的 stage（Stage 2 enrich）

环境变量：`FLOMO_VLM_BASE_URL`（默认 http://localhost:1234/v1）、`FLOMO_VLM_MODEL`、`FLOMO_VLM_API_KEY`、`FLOMO_VLM_TIMEOUT_SECONDS`、`FLOMO_VLM_MAX_TOKENS`。

**前台运行**（WSL 下必须 cmd.exe 注入）：

```bash
cmd.exe /c "set FLOMO_VLM_BASE_URL=http://localhost:1234/v1&& set FLOMO_VLM_MODEL=<model>&& .venv\Scripts\python.exe scripts\enrich_images.py --store-root store --provider lmstudio --month 2025-12 --workers 2"
```

**后台运行**（长任务标准姿势，PowerShell）：

```powershell
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "scripts\enrich_images.py","--store-root","store","--provider","lmstudio","--month","2025-12","--workers","2" -RedirectStandardOutput "enrich-2025-12.log" -NoNewWindow
```

- **workers 上限 2**：workers=4 会触发 LM Studio HTTP 500。
- 图片状态检查：`.venv/Scripts/python.exe scripts/validate_enriched_images.py --store-root store --summary`
- LM Studio 连通性在 WSL 里要用 PowerShell 验证（`Invoke-WebRequest http://127.0.0.1:1234/v1/models`），`curl 127.0.0.1:1234` 不通属正常。

## 4. 增量收件 / 发布（import 工作流）

```bash
.venv/Scripts/python.exe scripts/guide.py --action import --provider lmstudio --zip <flomo.zip> --publish-root flomo-context
```

## 5. 验证（每个 stage 有对应 validator）

```bash
.venv/Scripts/python.exe scripts/validate_store.py --store-root store --summary
.venv/Scripts/python.exe scripts/validate_enriched_images.py --store-root store --summary
.venv/Scripts/python.exe scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-12 --summary
.venv/Scripts/python.exe scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --summary
.venv/Scripts/python.exe scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports --summary
.venv/Scripts/python.exe scripts/validate_link_map.py --store-root store --summary
```

也可以用 pi 扩展工具 `flomo_status` 一键看流水线进度（等价于手动翻各目录计数）。

## 6. 完成标准（改动代码后必做）

1. 相关 stage 测试：`.venv/Scripts/python.exe -m pytest tests/test_<stage>.py -v`
2. 类型检查：`.venv/Scripts/python.exe -m mypy src`
3. **更新 `UpdateLog.md`**（项目硬性约定）
4. 交付前跑全量：`.venv/Scripts/python.exe -m pytest`

## 7. 排错

已知坑全部收录在 `references/troubleshooting.md`：JSON 截断、孤儿 enriched 记录、图片 failed/skipped、WSL 环境问题。遇到问题先查那里，不要凭空改代码。
