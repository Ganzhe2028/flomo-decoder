# flomo-transcriber

[English](README.en.md) | [更新日志](UpdateLog.md)

把你的 Flomo 记忆库变成 **LLM 友好**的资料包。

> [!NOTE]
> 亲测自己的 Flomo 导出包：缩减至原大小的约 **0.059%**，即减少了约 **99.94%**。

很多人把几千条 Flomo 记成了自己的长期记忆，但导出后很难直接交给模型处理：文字分散，图片没人读，月份不好拆，来源也不好追。`flomo-transcriber` 会把本地 Flomo 导出整理成干净、可检查、可重复生成的文件。

它会保留 memo 原文，也可以用本地 LM Studio 视觉模型把图片里的文字和画面信息转成文本，最后生成外部 LLM 可以直接读取的 chunk 文件：

```text
llm_chunks/YYYY-MM/*.json
```

它不是 Web 应用，不需要数据库。所有输入输出都是本地文件。

## 你应该从哪里开始

- 只是想把 Flomo 数据整理给 LLM 用：看 [第一次使用](#第一次使用) 和 [日常使用](#日常使用)。
- 想用图形界面操作：看 [桌面 GUI](#桌面-gui)。
- 需要排错、处理长截图、单独跑某个阶段：看 [高级用法和排错](#高级用法和排错)。
- 想改代码、跑测试、维护项目：看 [开发者：项目结构和测试](#开发者项目结构和测试)。

## 第一次使用

### 1. 安装

```bash
pip install -e .[dev]
```

### 2. 准备配置

Windows：

```bat
copy .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

打开 `.env`，至少改成你自己的视觉模型名：

```text
FLOMO_VLM_BASE_URL=http://127.0.0.1:1234/v1
FLOMO_VLM_MODEL=<你的视觉模型名>
# 可选：失败图片重试时使用的更强视觉模型
# FLOMO_VLM_RETRY_MODEL=<你的重试视觉模型名>
FLOMO_VLM_TIMEOUT_SECONDS=180
FLOMO_VLM_MAX_TOKENS=4096
```

脚本不会自动选择模型，只读取 `.env` 或当前环境变量里的模型名。
如果配置了 `FLOMO_VLM_RETRY_MODEL`，失败图片重试会使用这个模型；如果没配置，会继续使用 `FLOMO_VLM_MODEL` 并给出提示。两个模型名不能相同。

如果只是测试流程，不想连接 LM Studio，后面在引导脚本里选择 `mock`。

### 3. 放入 Flomo 导出

把 Flomo 的 HTML 导出内容放到：

```text
raw/
```

支持常规结构 `raw/YYYY/flomo@User-YYYYMMDD/*.html`，也支持部分解压工具生成的同名包裹结构 `raw/YYYY/flomo@User-YYYYMMDD/flomo@User-YYYYMMDD/*.html`。

这个仓库不会自带你的真实 Flomo 数据。`raw/`、`store/`、`monthly/`、`llm_chunks/`、`reports/` 默认都被 `.gitignore` 保护，避免误传到 GitHub。

### 4. 运行引导脚本

```bash
python scripts/guide.py
```

第一次运行选择：

```text
1. First run: build LLM chunks from raw/
```

按提示选择月份和图片处理方式：

- `lmstudio`：用 LM Studio 读取真实图片内容。
- `mock`：只测试流程，不调用模型。

完成后，给外部 LLM 读取的文件在：

```text
llm_chunks/YYYY-MM/*.json
```

## 日常使用

配置完成后，平时只需要继续运行：

```bash
python scripts/guide.py
```

常用选择：

| 选项 | 什么时候用 | 结果 |
| --- | --- | --- |
| `1. First run` | 第一次从 `raw/` 生成 chunks | 生成 `llm_chunks/YYYY-MM/*.json` |
| `2. Daily update` | 更新了 `raw/`，想重新生成 chunks | 跳过已成功图片，补齐新内容 |
| `3. Probe one image` | 不确定 LM Studio 是否能读图 | 单独测试一张图片 |
| `4. Retry failed image records` | 有图片识别失败 | 只重试失败图片 |
| `5. Import Flomo ZIP` | 想直接处理新的 Flomo ZIP | 安全解压、去重、识图并发布完整快照 |

如果只想处理某个月，按提示输入 `2025-12` 这样的月份；直接回车会处理全部月份。

也可以不用菜单，直接运行：

```bash
python scripts/guide.py --action first --provider lmstudio --month 2025-12
python scripts/guide.py --action daily --provider lmstudio --month 2025-12
python scripts/guide.py --action retry --provider lmstudio --month 2025-12
python scripts/guide.py --action probe --image store/images/2025/2025-12/example.png
python scripts/guide.py --action import --zip "Downloads/flomo@User-20260817.zip" --publish-root "flomo-context" --provider lmstudio
```

## 增量收件与 Mac 同步

Windows GUI 可以直接接收 Flomo ZIP，不再需要手动解压、改名和搬入 `raw/`。

日期规则是：下次导出从“上次成功发布的最后一天”开始，**不要加一天**。例如最后一条已处理 memo 是 `2026-08-17 18:51:37`，下次仍从 `2026-08-17` 导出。当天已处理的内容会被去重，18:51 之后继续写下的内容不会丢失。

在 GUI 中选择“增量收件”，或使用：

```bash
python scripts/guide.py --action import --zip "Downloads/flomo@User-20260817.zip" --publish-root "flomo-context" --provider lmstudio
```

成功后会生成：

```text
flomo-context/
├── latest.json
└── snapshots/<release-id>/
    ├── manifest.json
    └── llm_chunks/YYYY-MM/*.json
```

`latest.json` 只会在解压、去重、图片识别、chunks 生成和全部校验完成后更新。单张图片最终识别失败不会阻塞整批 memo，但失败数量和原因会写入发布清单并显示在 GUI。

首次使用增量收件时，会自动重建一次历史月份，以迁移旧批次的重叠记录；完成后，后续导入只重建 ZIP 影响的月份。

程序按 ZIP 内容识别重复导入。同一个 ZIP 已成功发布时会直接复用已有文字和图片识别结果，因此不会再次出现 Gemma 处理进度。`.mov`、`.mp4`、`.m4a` 等视频或音频附件仍会明确标记为 skipped。

### 使用 Syncthing 在 Windows 和 Mac 之间传递

Syncthing 不会随本工具安装。在 Windows 和 Mac 上分别安装、互相添加设备后，建议创建两个共享文件夹：

| 文件夹 | Windows | Mac | 用途 |
| --- | --- | --- | --- |
| `flomo-inbox` | Send & Receive | Send & Receive | 从任意一台电脑放入 Flomo ZIP |
| `flomo-context` | Send Only | Receive Only | Windows 发布完整 chunks，Mac 只接收 |

在 GUI 设置中选择这两个本地目录，并开启自动收件。GUI 开启期间会监控 inbox，也可同时扫描 Windows Downloads。ZIP 尚未下载完成时不会启动；LM Studio 未开启时会保持等待。

启用 Downloads 扫描后，GUI 会处理该目录内所有符合 Flomo 命名且尚未导入的 ZIP。只想处理 Syncthing inbox 时，应关闭 Downloads 扫描，或把旧 ZIP 移出 Downloads。

Mac 上的 Hermes/OpenClaw 应先读取 `latest.json`，再按它指向的 `manifest.json` 读取当前快照。清单包含文件哈希，用来避免 Agent 读到尚在同步的半成品。

传输安全、中继和设备身份说明见 [Syncthing Security Principles](https://docs.syncthing.net/v1.0.0/users/security.html)。两端磁盘上仍是正常可读文件，建议保持系统登录与磁盘加密。

## 桌面 GUI

仓库里包含一个开发版 Tauri 桌面 GUI，位置在：

```text
gui/
```

GUI 封装普通用户最常用的五个操作：

| 操作 | 对应命令 |
| --- | --- |
| 首次生成 | `python scripts/guide.py --action first` |
| 日常更新 | `python scripts/guide.py --action daily` |
| 探测图片 | `python scripts/guide.py --action probe` |
| 重试失败 | `python scripts/guide.py --action retry` |
| 增量收件 | `python scripts/guide.py --action import` |

GUI 会直接读写 `.env`，可在界面里设置 LM Studio 地址、视觉模型、重试模型、超时和 max tokens；也可设置 inbox、发布目录、Downloads 扫描和自动收件。文件夹路径会保存到 `.flomo-gui-settings.json`，下次打开会继续使用上次选择的位置。`.env` 和 `.flomo-gui-settings.json` 都会被 Git 忽略。

开发版启动：

```bat
cd gui
cmd /c npm install
cmd /c npm run tauri dev
```

Windows 上运行 Tauri 需要先安装 Rust/Cargo、Microsoft C++ Build Tools 和 WebView2。开发模式下，如果还没有构建 sidecar，GUI 会回退到本机 Python；安装版会优先使用内置 sidecar。

### Windows 安装包

当前 GUI 版本为 `0.3.0`；旧版 `0.1.0` 不包含“增量收件”，`0.2.0` 不含 Notion 双向链接解析。安装包使用 NSIS `setup.exe`，暂不做代码签名、自动更新或 Microsoft Store 发布。未签名安装包可能触发 Windows SmartScreen 提示。

打包前置条件：

```bat
pip install -e .[dev,gui]
cd gui
cmd /c npm install
cmd /c npm run sidecar
cmd /c npm run tauri:build:nsis
```

构建产物会出现在 `gui/src-tauri/target/release/bundle/nsis/`。安装包不会包含真实 `raw/`、`store/`、`monthly/`、`llm_chunks/`、`reports/` 或 `.env`。

## 目录和输出

```text
raw/          你放进去的 Flomo 原始导出
store/        Stage 1-2 输出：raw JSONL、图片副本、图片增强结果；另存 link_map.json（Notion 链接映射）
monthly/      Stage 3 输出：按月合并后的 memo 记录
llm_chunks/   Stage 4 输出：给外部 LLM 读取的 chunk JSON
reports/      Stage 5 输出：可选的本地月度报告
flomo-inbox/  Syncthing 可共享的 ZIP 收件目录
flomo-context/  完整发布快照；Mac Agent 从 latest.json 进入
gui/          开发版 Tauri 桌面 GUI
scripts/      命令行入口
src/          Python 源码
tests/        测试
```

最重要的输出是：

```text
llm_chunks/YYYY-MM/*.json
```

如果你准备用 OpenRouter、ChatGPT、Claude 或其他外部模型做最终总结，通常只需要把这个目录交给外部模型。

## 每个 Stage 做什么

| Stage | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| Stage 1 extract | `raw/` | `store/memo.raw.jsonl`, `store/image.raw.jsonl`, `store/images/` | 提取 memo 和图片引用 |
| Stage 2 enrich | `store/image.raw.jsonl` | `store/image.enriched.jsonl` | 读取静态图片，写入 OCR 和画面描述 |
| Stage 3 merge monthly | `memo.raw.jsonl`, `image.enriched.jsonl` | `monthly/YYYY-MM.enriched.jsonl` | 按月把 memo 和图片增强结果合并 |
| Stage 4 chunk | `monthly/YYYY-MM.enriched.jsonl` | `llm_chunks/YYYY-MM/*.json` | 生成 LLM 可读的分块上下文 |
| Stage 5 report | `llm_chunks/YYYY-MM/*.json` | `reports/YYYY-MM.report.md`, `reports/YYYY-MM.report.json` | 可选：生成本地月度报告 |

Stage 1-4 是推荐主流程。Stage 5 是可选功能；如果你要用外部模型生成最终报告，可以只用 Stage 1-4。

## 高级用法和排错

### LM Studio 配置

`lmstudio` 读取这些环境变量：

- `FLOMO_VLM_BASE_URL`：例如 `http://127.0.0.1:1234/v1`
- `FLOMO_VLM_MODEL`：本地视觉模型名
- `FLOMO_VLM_RETRY_MODEL`：可选，失败图片重试专用模型；不设置时沿用 `FLOMO_VLM_MODEL`
- `FLOMO_VLM_API_KEY`：可选
- `FLOMO_VLM_TIMEOUT_SECONDS`：可选，默认 `60`
- `FLOMO_VLM_MAX_TOKENS`：可选，默认 `4096`
- `FLOMO_VLM_SLICE_LONG_IMAGES`：可选，设为 `true` 时，长图整图识别失败后自动切片重试
- `FLOMO_VLM_FORCE_SLICE_LONG_IMAGES`：可选，设为 `true` 时，高度超过切片阈值的图片直接切片识别
- `FLOMO_VLM_SLICE_HEIGHT`：可选，默认 `500`
- `FLOMO_VLM_SLICE_OVERLAP`：可选，默认 `60`
- `FLOMO_VLM_SLICE_UPSCALE`：可选，默认 `2`

如果探测返回 `connection refused` 或 `WinError 10061`，表示脚本没有连上 LM Studio 服务。检查：

- LM Studio 的 OpenAI-compatible server 已经启动。
- `FLOMO_VLM_BASE_URL` 的 host/port 和 LM Studio 显示的一致。
- 视觉模型已在 LM Studio 中加载，`FLOMO_VLM_MODEL` 与模型名一致。

`FLOMO_VLM_RETRY_MODEL` 适合配置成更大、更强但更慢的视觉模型。retry 成功后，`store/image.enriched.jsonl` 的 `model_name` 会记录实际使用的 retry 模型名。

### 单阶段命令

一般用户优先用 `python scripts/guide.py`。下面这些命令适合排错或只重跑某个阶段。

生成 raw 数据层：

```bash
python scripts/extract_raw.py --raw-root raw --store-root store
python scripts/validate_store.py --raw-root raw --store-root store --summary
```

读取图片：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12
python scripts/validate_enriched_images.py --store-root store --summary
```

生成 chunks：

```bash
python scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-12
python scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-12 --summary
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --overwrite
python scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --summary
```

双向链接解析（详见「双向链接解析（Notion 数据库）」一节）：

```bash
python scripts/import_notion_links.py --notion-url "https://app.notion.com/p/<数据库页面ID>" --store-root store
python scripts/validate_link_map.py --store-root store --summary
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --link-map store/link_map.json --overwrite
```

### 平台脚本

这些脚本仍然保留，适合已经熟悉流程的人使用。

macOS / Linux：

```bash
scripts/00_probe_lmstudio_image.sh store/images/2025/2025-12/example.png
scripts/10_stage2_enrich_lmstudio.sh 2025-12
scripts/20_stage3_4_build_context.sh 2025-12
```

Windows：

```bat
scripts\00_probe_lmstudio_image.bat store\images\2025\2025-12\example.png
scripts\10_stage2_enrich_lmstudio.bat 2025-12
scripts\20_stage3_4_build_context.bat 2025-12
scripts\30_stage2_4_prepare_context.bat 2025-12
scripts\40_retry_failed_images_lmstudio.bat 2025-12
```

### 长图和截图

如果长截图、窄截图或压缩严重的截图整图识别失败，可以打开切片 fallback：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --slice-long-images
```

默认每段高度 `500px`，相邻段重叠 `60px`，每段提交模型前放大 `2x`。需要调整时：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --slice-long-images --slice-height 500 --slice-overlap 60 --slice-upscale 2
```

如果确认某批长图整图识别一定效果差，可以直接跳过整图识别：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --force-slice-long-images
```

如果本地模型服务允许并发，可以加 `--workers`：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --workers 4
```

### 图片增强说明

当前只处理静态图片：

- `.png`
- `.jpg`
- `.jpeg`

当前会明确跳过：

- `.mov`
- `.mp4`
- `.m4a`
- 其他非静态图片类型

图片描述会覆盖照片、物体、场景、图表、界面布局、diagram 和 screenshot 等可见非文字内容。密集截图或拍照笔记会保留关键文字，不会追求完整逐字 OCR。

图片增强失败不会中断整个流程。每张图片完成后都会立刻保存；仍失败的图片会保留 `status=failed` 和失败原因。再次运行会跳过已成功记录，继续处理失败或未完成记录。

Windows 上如果 `store/image.enriched.jsonl` 正被其他程序占用，保存时会短暂重试。仍失败时，关闭正在查看或编辑这个文件的程序后重跑；最新一次尝试写入的内容会保留在 `store/image.enriched.jsonl.tmp`。

需要重跑成功项时加：

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --overwrite
```

### 手动写回外部识别结果

如果你用外部模型或人工方式修复失败图片，只改 `store/image.enriched.jsonl` 里对应 `image_id` 的增强字段，不改 `store/image.raw.jsonl`。

| 内容 | 字段 |
| --- | --- |
| 图片里的文字 | `ocr_text` |
| 图片画面说明 | `visual_description` |
| 外部模型名称 | `model_name` |
| 人工补录标记 | `prompt_version`, `run_id` |
| 成功状态 | `status: "success"` |
| 失败原因 | `error_message: null` |

写回后重新校验并生成下游文件：

```bash
python scripts/validate_enriched_images.py --store-root store
python scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-04
python scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-04
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-04 --overwrite
python scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-04
```

### 可选：生成本地 report

默认 mock report：

```bash
python scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider mock
python scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports
```

用 LM Studio 文本模型生成 report：

```bash
python scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider lmstudio --month 2025-12 --overwrite
python scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports --month 2025-12 --summary
```

如果你使用 OpenRouter 或其他外部模型做最终报告，可以跳过这一节。

## Stage 4 chunk 说明

chunk 是给 LLM 读取的最终上下文文件。

每个 chunk 至少包含：

- `chunk_id`
- `month`
- `source_memo_ids`
- `created_at_range`
- `token_estimate`
- `text`
- `source_items`
- `resolved_links`（无 link map 时为空数组）

其中：

- `text` 是给模型直接读的文本。
- `source_items` 保留来源 memo 和图片增强记录，方便追溯。
- memo 是最小单位，默认不会把一条 memo 拆成多个 chunk。
- `failed` / `skipped` 图片不会伪造成文字，但会在结构化字段里保留。

默认策略是按时间顺序装箱，目标大小约 `1200` tokens。估算方法是稳定启发式，不追求和某个模型 tokenizer 完全一致。

## 双向链接解析（Notion 数据库）

flomo 导出里 memo 之间的内部链接是形如 `https://v.flomoapp.com/mine/?memo_id=XXX` 的裸 URL，XXX 是 base64 编码的内部 ID，导出文件本身**不包含 ID 到内容的映射**，LLM 读不到你在 flomo 里手动建立的关联关系。

用同步到 Notion 的 flomo 数据库可以补齐这份映射。**最省事的方式：直接把 Notion 数据库的分享链接交给导入脚本**，脚本直接读本机 Notion 桌面端的离线镜像（`%APPDATA%/Notion/notion.db`），无需导出、无需 token、无网络请求：

```bash
# 1. 直接读 Notion 离线镜像并构建映射（把链接换成你自己的 flomo 数据库链接）：
python scripts/import_notion_links.py --notion-url "https://app.notion.com/p/<数据库页面ID>" --store-root store

# 2. 校验映射：
python scripts/validate_link_map.py --store-root store --summary

# 3. 重建 chunks，把链接替换成 LLM 可读的引用：
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks \
    --link-map store/link_map.json --overwrite
```

也可以离线解析 Notion 导出的文件（.zip / .csv / .md / 目录）：

```bash
python scripts/import_notion_links.py --input 导出.zip --store-root store
```

替换效果（chunk 的 `text` 字段内）：

- 原文：`...这是有用的https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg`
- 替换后：`...这是有用的〔关联 MEMO 2023-04-15「心法就是用心看世界的方法」〕`
- 反向链接：被关联的 memo 块会追加 `[RELATED]` 小节，列出 `linked_from` 来源 memo。
- 结构化字段：chunk 新增 `resolved_links` 数组，每条含 `from_memo_id`、`to_internal_id`、`to_memo_id`、`to_created_at`、`to_snippet`。

数据兼容性说明（flomo → Notion 同步的固有限制，解析器已适配）：

- 同步把 memo 内容作为页面标题，**截断到 50 字符**：作为引用摘要足够，匹配 pipeline memo 时用「精确 → 唯一前缀 → 前缀+日期」逐级匹配。
- 「关联自」URL 的 base64 ID 有时被截断：用已知 ID 集合做唯一前缀恢复。
- Notion 数据库若只同步了部分 memo，解析不了的链接会原样保留并计数。

规则：

- `source_items` 里的原始 `memo_text` 保持不变，只有渲染后的 `text` 被替换 —— Stage 1 事实层不受影响。
- 映射解析不了的链接**原样保留**，不静默丢弃；构建统计里会分别报告 resolved / unresolved 数量。
- `store/link_map.json` 是本地缓存，Notion 数据更新后重跑 `import_notion_links.py --overwrite` 即可。
- 不带 `--link-map` 时行为与之前完全一致。

## 开发者：项目结构和测试

源码结构：

```text
src/flomo_pipeline/
├── common/
├── extract/
├── enrich/
├── merge/
├── chunk/
├── sync/                 # ZIP 安全收件、导入状态与完整快照发布
└── report/
```

说明：项目的公开名称是 `flomo-transcriber`。内部 Python import 包仍叫 `flomo_pipeline`，这是为了保持现有脚本和测试兼容。

`common/` 放共享的文件读写和校验报告工具。各 stage 仍保留自己的 runner、validator 和数据模型。

常用命令：

```bash
python -m pytest
python -m mypy src
python scripts/check_open_source_readiness.py
```

GUI 前端检查：

```bat
cd gui
cmd /c npm run build
```

GUI 打包检查：

```bat
pip install -e .[gui]
cd gui
cmd /c npm run sidecar
cmd /c npm run tauri:build:nsis
```

Makefile 也提供同等入口：

```bash
make extract
make validate
make enrich
make enrich-lmstudio
make validate-enrich
make merge-monthly
make validate-monthly
make build-chunks
make validate-chunks
make build-reports
make validate-reports
make import-notion-links INPUT=<notion导出.zip>
make validate-link-map
make test
```

代码原则：

- 每个 stage 只读上游文件、写自己的派生产物。
- Stage 1 的 raw JSONL 是事实层，不被下游改写。
- 下游输出必须可以重新生成。
- 所有路径字段保持相对路径。
- 所有关键输出都有 validator。

## Agent：边界和契约

Agent 接手时先读这些位置：

1. `AGENTS.md`
2. `README.md` 或 `README.en.md`
3. `pyproject.toml`
4. `tests/`

不要默认重构旧阶段。已有边界如下：

- Stage 1：`raw -> store/*.raw.jsonl`
- Stage 2：`store/image.raw.jsonl -> store/image.enriched.jsonl`
- Stage 3：`store/*.jsonl -> monthly/YYYY-MM.enriched.jsonl`
- Stage 4：`monthly/YYYY-MM.enriched.jsonl -> llm_chunks/YYYY-MM/*.json`
- Stage 5：`llm_chunks/YYYY-MM/*.json -> reports/YYYY-MM.report.*`
- Notion 链接解析：`Notion 数据库/导出 -> store/link_map.json -> Stage 4 链接替换`

新增能力时要遵守：

- 不把真实用户数据提交进 Git。
- 不把 `monthly`、`chunk`、`report` 当成新的 truth layer。
- 不静默丢弃 `failed` / `skipped` 图片。
- 不在 Stage 4 做 LLM 调用。
- 不在 Stage 2 处理视频或音频，除非明确新增对应 stage 设计。
- 改了用户可见行为就更新 README。

最小交付检查：

```bash
python -m pytest
python scripts/check_open_source_readiness.py
```

## Schema 速查

### `store/memo.raw.jsonl`

- `memo_id`
- `created_at`
- `body_md`
- `image_count`
- `source_relpath`
- `batch_label`
- `ordinal`

### `store/image.raw.jsonl`

- `image_id`
- `memo_id`
- `image_relpath`
- `source_relpath`
- `ordinal`

### `store/image.enriched.jsonl`

- `image_id`
- `memo_id`
- `created_at`
- `month`
- `relative_path`
- `source_relpath`
- `media_type`
- `ocr_text`
- `visual_description`
- `model_name`
- `prompt_version`
- `run_id`
- `status`
- `error_message`

### `monthly/YYYY-MM.enriched.jsonl`

- `memo_id`
- `created_at`
- `month`
- `memo_text`
- `source_relpath`
- `batch_label`
- `ordinal`
- `image_count_raw`
- `images`

`images` 保留 Stage 2 的关键字段，包括 `image_id`、路径、OCR、画面描述、模型信息、`status` 和 `error_message`。

### `llm_chunks/YYYY-MM/<chunk-id>.json`

- `chunk_id`
- `month`
- `chunk_index`
- `source_memo_ids`
- `source_count`
- `created_at_range`
- `token_estimate`
- `text`
- `source_items`
- `resolved_links`
- `build_version`
- `strategy`
- `status`

### `store/link_map.json`

- `schema_version`（`link-map-v1`）
- `entries`：以 flomo 内部 ID 为键，每条含 `internal_id`、`memo_url`、`content`、`created_at`、`pipeline_memo_id`（可空）、`backlink_ids`

### `reports/YYYY-MM.report.json`

- `report_id`
- `month`
- `source_chunk_ids`
- `source_count`
- `provider_name`
- `model_name`
- `prompt_version`
- `build_version`
- `status`
- `error_message`
- `report_md`
- `sections`

## Open Source Safety

真实 Flomo 导出和所有派生结果不应进入公开仓库。发布前运行：

```bash
python scripts/check_open_source_readiness.py
```

这个检查会确认没有把这些目录里的真实数据加入 Git：

- `raw/`
- `store/`
- `monthly/`
- `llm_chunks/`
- `reports/`
- `flomo-inbox/`
- `flomo-context/`
- 本地遗留的 `preview/`，如果存在

当前 private 工作仓库的旧 Git history 不适合直接公开。公开发布应使用 clean orphan branch 或全新的 public repo。
