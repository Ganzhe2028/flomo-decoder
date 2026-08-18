# flomo-pipeline-ops 排错手册

## 图片类

### enrich 时 JSON 截断报 `Unterminated string`

长图 JSON 被截断（LM Studio 响应异常）。重试时加 `--slice-long-images`：

```bash
cmd.exe /c "set FLOMO_VLM_BASE_URL=...&& .venv\Scripts\python.exe scripts\enrich_images.py --store-root store --provider lmstudio --month 2025-12 --workers 2 --slice-long-images"
```

确认长图整图识别效果差时，直接强制切片：`--force-slice-long-images`。

### 大量图片被标 failed，error 是 Missing env

WSL 里 `export FLOMO_VLM_*` 不会传给 Windows 进程。必须用 cmd.exe 批处理注入（见 SKILL.md 第 3 节），或 PowerShell 里先 `$env:FLOMO_VLM_...` 再 `Start-Process`。

### workers=4 触发 LM Studio HTTP 500

workers 上限 2。这是本机 LM Studio 实测出来的稳定值。

### 只重试失败图片

按月份重跑即可（provider 自带跳过成功记录的逻辑），或看 `store/image.enriched.jsonl` 里 `status: "failed"` 的记录分布再决定重跑哪个月。

### 图片 failed / skipped 记录的处理

下游**不静默丢弃**：这些记录保留在 `image.enriched.jsonl` 里，带 `status` + `error_message`。不要手动删行——校验器与月度合并都依赖完整记录。

## 数据一致性类

### 重新 extract 后旧 enriched 记录变孤儿

extract 重建 `store/*.raw.jsonl` 后，若导出被替换（memo 数变化导致 image_id 漂移），`image.enriched.jsonl` 里旧月份记录会变孤儿。处理步骤：

1. 先备份 `image.enriched.jsonl`
2. 删除其中 `month == YYYY-MM` 的旧记录
3. `--month YYYY-MM` 重跑 enrich

### raw JSONL 是事实层，下游不得改写

任何「修复数据」的操作都必须在 extract 或更上游做，或通过重跑下游 stage 完成。直接改 raw JSONL 会让校验器与后续合并结果失真。

### 下游产物必须可重新生成

`monthly/`、`llm_chunks/`、`reports/` 都是派生层。验证一致性最省事的方法：删掉怀疑的月份产物，用 `--overwrite` 重跑对应 stage，对比结果。

## 环境类

### WSL 里 `curl 127.0.0.1:1234` 不通

正常。WSL 网络与 Windows 不同栈，用 PowerShell `Invoke-WebRequest http://127.0.0.1:1234/v1/models` 验证 LM Studio 存活。

### bash 后台任务「跑着跑着就没了」

`nohup python ... &` 启动的 Windows 进程会随 bash 命令退出被杀。长任务一律 PowerShell：

```powershell
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "scripts\enrich_images.py","--store-root","store","--provider","lmstudio","--month","2025-12","--workers","2" -RedirectStandardOutput "enrich-2025-12.log" -NoNewWindow
```

看进度用 `Get-Content enrich-2025-12.log -Wait`。

### PowerShell 里直接跑 `.venv\Scripts\python.exe` 而不是激活 venv

`.venv\Scripts\Activate.ps1` 只是给交互 shell 用的；脚本和扩展调用直接用 exe 绝对路径即可，不受执行策略限制。

## 通用排查顺序

1. `flomo_status` 工具或 validator 脚本看哪个 stage 断在哪
2. 对应 stage 测试：`tests/test_<stage>.py`
3. 翻本手册对应条目
4. 仍无解时读 `src/flomo_pipeline/<stage>/AGENTS.md` 与该 stage 的 runner 代码，不要动无关 stage
