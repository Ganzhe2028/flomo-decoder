# flomo-transcriber

[中文](README.md) | [Update Log](UpdateLog.md)

Turn your Flomo memory archive into files that LLMs can actually read.

> [!NOTE]
> Tested my own Flomo export package: reduced to approximately **0.059%** of the original size, i.e. a reduction of about **99.94%**.

Many people use Flomo as a long-term memory system. After years of notes, the export can contain thousands of memos and many images, but it is not easy to hand that export to an LLM: text is scattered, images are unread, months are not split cleanly, and source tracking is fragile. `flomo-transcriber` turns that local export into clean, inspectable, reproducible files.

It keeps your original memo text, can use a local LM Studio vision model to convert image text and visible details into text, and produces chunk files that external LLMs can read directly:

```text
llm_chunks/YYYY-MM/*.json
```

This is not a web app and does not require a database. Everything is local files.

## Start Here

- If you only want to prepare Flomo data for an LLM, read [First Use](#first-use) and [Normal Use](#normal-use).
- If you want a graphical interface, read [Desktop GUI](#desktop-gui).
- If you need troubleshooting, long screenshot handling, or single-stage commands, read [Advanced Usage and Troubleshooting](#advanced-usage-and-troubleshooting).
- If you want to change code or maintain the project, read [Developer: Structure and Tests](#developer-structure-and-tests).

## First Use

### 1. Install

```bash
pip install -e .[dev]
```

### 2. Prepare Configuration

Windows:

```bat
copy .env.example .env
```

macOS / Linux:

```bash
cp .env.example .env
```

Open `.env` and at least set your own vision model name:

```text
FLOMO_VLM_BASE_URL=http://127.0.0.1:1234/v1
FLOMO_VLM_MODEL=<your-vision-model-name>
# Optional stronger vision model for failed-image retry.
# FLOMO_VLM_RETRY_MODEL=<your-retry-vision-model-name>
FLOMO_VLM_TIMEOUT_SECONDS=180
FLOMO_VLM_MAX_TOKENS=4096
```

The scripts do not choose a model automatically. They only read the model name from `.env` or the current environment.
If `FLOMO_VLM_RETRY_MODEL` is set, failed-image retry uses that model. If it is not set, retry keeps using `FLOMO_VLM_MODEL` and prints a warning. The two model names cannot be identical.

If you only want to test the flow without connecting to LM Studio, choose `mock` in the guide.

### 3. Put Your Flomo Export Into `raw/`

Place your Flomo HTML export under:

```text
raw/
```

Both the regular layout `raw/YYYY/flomo@User-YYYYMMDD/*.html` and the duplicate wrapper layout `raw/YYYY/flomo@User-YYYYMMDD/flomo@User-YYYYMMDD/*.html` are supported.

This repository does not include real Flomo data. `raw/`, `store/`, `monthly/`, `llm_chunks/`, and `reports/` are ignored by Git by default so private data is not accidentally committed.

### 4. Run the Guide

```bash
python scripts/guide.py
```

For the first run, choose:

```text
1. First run: build LLM chunks from raw/
```

Then choose the month and image provider:

- `lmstudio`: read real image content with LM Studio.
- `mock`: test the flow without model calls.

When it finishes, the files for external LLMs are here:

```text
llm_chunks/YYYY-MM/*.json
```

## Normal Use

After configuration, the daily entry point is still:

```bash
python scripts/guide.py
```

Common choices:

| Choice | Use When | Result |
| --- | --- | --- |
| `1. First run` | You are building chunks from `raw/` for the first time | Creates `llm_chunks/YYYY-MM/*.json` |
| `2. Daily update` | You changed `raw/` and want fresh chunks | Skips successful images and fills new content |
| `3. Probe one image` | You are checking whether LM Studio can read images | Tests one image |
| `4. Retry failed image records` | Some image records failed | Retries failed records only |
| `5. Import Flomo ZIP` | You want to process a new Flomo ZIP directly | Safely extracts, deduplicates, enriches, and publishes a complete snapshot |

To process one month, enter a month like `2025-12`; press Enter to process all months.

You can also skip the menu:

```bash
python scripts/guide.py --action first --provider lmstudio --month 2025-12
python scripts/guide.py --action daily --provider lmstudio --month 2025-12
python scripts/guide.py --action retry --provider lmstudio --month 2025-12
python scripts/guide.py --action probe --image store/images/2025/2025-12/example.png
python scripts/guide.py --action import --zip "Downloads/flomo@User-20260817.zip" --publish-root "flomo-context" --provider lmstudio
```

## Incremental Inbox and Mac Delivery

The Windows GUI can receive a Flomo ZIP directly, so you no longer need to unpack, rename, and move every export into `raw/`.

The export start date is always the date of the latest successfully published memo, **without adding one day**. If the latest imported memo is `2026-08-17 18:51:37`, the next export must still start on `2026-08-17`. Earlier records from that day are deduplicated, while memos written later that day remain included.

Choose Incremental Inbox in the GUI, or run:

```bash
python scripts/guide.py --action import --zip "Downloads/flomo@User-20260817.zip" --publish-root "flomo-context" --provider lmstudio
```

A successful run publishes an immutable snapshot:

```text
flomo-context/
├── latest.json
└── snapshots/<release-id>/
    ├── manifest.json
    └── llm_chunks/YYYY-MM/*.json
```

`latest.json` is updated only after import, deduplication, image enrichment, chunk generation, and validation finish. Final image failures and their reasons are reported in both the manifest and GUI, but do not block every newer memo.

The first incremental import rebuilds historical months once to migrate overlaps from older batches. Later imports rebuild only the months affected by that ZIP.

ZIP content identifies duplicate imports. When the same ZIP has already been published, the workflow reuses its memo and image-enrichment results, so no new Gemma progress appears. Video and audio attachments such as `.mov`, `.mp4`, and `.m4a` remain explicitly marked as skipped.

For automatic Windows-to-Mac delivery, install Syncthing on both devices and create two shared folders:

| Folder | Windows | Mac | Purpose |
| --- | --- | --- | --- |
| `flomo-inbox` | Send & Receive | Send & Receive | Accept exports saved from either device |
| `flomo-context` | Send Only | Receive Only | Publish complete snapshots from Windows to Mac |

Select those local folders in GUI settings and enable automatic inbox processing. While the GUI is open, it watches the inbox and can also scan Windows Downloads. Incomplete ZIPs are ignored; imports wait when LM Studio is unavailable.

When Downloads scanning is enabled, the GUI processes every correctly named Flomo ZIP there that is not yet in the import history. Disable Downloads scanning, or move old ZIPs elsewhere, if only the Syncthing inbox should be processed.

Hermes/OpenClaw should read `latest.json`, follow its snapshot manifest, and only use files after their hashes match. See [Syncthing Security Principles](https://docs.syncthing.net/v1.0.0/users/security.html) for transport and device-security details.

## Desktop GUI

The repository includes a development Tauri desktop GUI here:

```text
gui/
```

The GUI wraps the five common user actions:

| Action | Command |
| --- | --- |
| First run | `python scripts/guide.py --action first` |
| Daily update | `python scripts/guide.py --action daily` |
| Probe one image | `python scripts/guide.py --action probe` |
| Retry failed images | `python scripts/guide.py --action retry` |
| Incremental inbox | `python scripts/guide.py --action import` |

The GUI reads and writes `.env`. You can set the LM Studio base URL, vision model, retry model, timeout, and max tokens in the interface, plus the inbox, publish folder, Downloads scanning, and automatic import. Folder paths are saved to `.flomo-gui-settings.json`, so the next launch keeps the last selected locations. Both `.env` and `.flomo-gui-settings.json` are ignored by Git.

Development startup:

```bat
cd gui
cmd /c npm install
cmd /c npm run tauri dev
```

On Windows, Tauri requires Rust/Cargo, Microsoft C++ Build Tools, and WebView2. In development mode, the GUI falls back to local Python if the sidecar has not been built yet; installed builds prefer the bundled sidecar.

### Windows Installer

The current GUI version is `0.2.0`; the old `0.1.0` build does not include Incremental Inbox. The installer is an NSIS `setup.exe`. Code signing, automatic updates, and Microsoft Store publishing are not included. Unsigned installers may trigger a Windows SmartScreen warning.

Build prerequisites:

```bat
pip install -e .[dev,gui]
cd gui
cmd /c npm install
cmd /c npm run sidecar
cmd /c npm run tauri:build:nsis
```

The installer is written under `gui/src-tauri/target/release/bundle/nsis/`. It must not include real `raw/`, `store/`, `monthly/`, `llm_chunks/`, `reports/`, or `.env` data.

## Folders and Outputs

```text
raw/          Your original Flomo export
store/        Stage 1-2 outputs: raw JSONL, copied images, image enrichment;
              also holds link_map.json (Notion link resolution map)
monthly/      Stage 3 output: monthly merged memo records
llm_chunks/   Stage 4 output: chunk JSON files for external LLMs
reports/      Stage 5 output: optional local monthly reports
flomo-inbox/  Syncthing-shareable ZIP inbox
flomo-context/  Complete published snapshots; Mac agents enter through latest.json
gui/          Development Tauri desktop GUI
scripts/      CLI entry points
src/          Python source code
tests/        Tests
```

The most important output is:

```text
llm_chunks/YYYY-MM/*.json
```

If you plan to use OpenRouter, ChatGPT, Claude, or another external model for final summarization, this is usually the only directory your external model needs to read.

## What Each Stage Does

| Stage | Input | Output | Purpose |
| --- | --- | --- | --- |
| Stage 1 extract | `raw/` | `store/memo.raw.jsonl`, `store/image.raw.jsonl`, `store/images/` | Extract memos and image references |
| Stage 2 enrich | `store/image.raw.jsonl` | `store/image.enriched.jsonl` | Read static images and write OCR / visual descriptions |
| Stage 3 merge monthly | `memo.raw.jsonl`, `image.enriched.jsonl` | `monthly/YYYY-MM.enriched.jsonl` | Merge memo text and image enrichment by month |
| Stage 4 chunk | `monthly/YYYY-MM.enriched.jsonl` | `llm_chunks/YYYY-MM/*.json` | Build LLM-readable context chunks |
| Stage 5 report | `llm_chunks/YYYY-MM/*.json` | `reports/YYYY-MM.report.md`, `reports/YYYY-MM.report.json` | Optional local monthly report generation |

Stage 1-4 are the recommended main path. Stage 5 is optional. If you use an external model for the final report, you can stop after Stage 4.

## Advanced Usage and Troubleshooting

### LM Studio Configuration

`lmstudio` reads:

- `FLOMO_VLM_BASE_URL`: for example `http://127.0.0.1:1234/v1`
- `FLOMO_VLM_MODEL`: local vision model name
- `FLOMO_VLM_RETRY_MODEL`: optional failed-image retry model; falls back to `FLOMO_VLM_MODEL` when unset
- `FLOMO_VLM_API_KEY`: optional
- `FLOMO_VLM_TIMEOUT_SECONDS`: optional, default `60`
- `FLOMO_VLM_MAX_TOKENS`: optional, default `4096`
- `FLOMO_VLM_SLICE_LONG_IMAGES`: optional, set to `true` to retry failed tall images as vertical clips
- `FLOMO_VLM_FORCE_SLICE_LONG_IMAGES`: optional, set to `true` to skip whole-image recognition for images taller than the slice height
- `FLOMO_VLM_SLICE_HEIGHT`: optional, default `500`
- `FLOMO_VLM_SLICE_OVERLAP`: optional, default `60`
- `FLOMO_VLM_SLICE_UPSCALE`: optional, default `2`

If the probe returns `connection refused` or `WinError 10061`, the script could not reach LM Studio. Check:

- LM Studio's OpenAI-compatible server is running.
- `FLOMO_VLM_BASE_URL` matches the host and port shown by LM Studio.
- The vision model is loaded in LM Studio, and `FLOMO_VLM_MODEL` matches the model name.

`FLOMO_VLM_RETRY_MODEL` is intended for a larger, stronger, slower vision model. When retry succeeds, `model_name` in `store/image.enriched.jsonl` records the actual retry model.

### Single-Stage Commands

Most users should start with `python scripts/guide.py`. These commands are useful for troubleshooting or rerunning one stage.

Build the raw data layer:

```bash
python scripts/extract_raw.py --raw-root raw --store-root store
python scripts/validate_store.py --raw-root raw --store-root store --summary
```

Read images:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12
python scripts/validate_enriched_images.py --store-root store --summary
```

Build chunks:

```bash
python scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-12
python scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-12 --summary
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --overwrite
python scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-12 --summary
```

### Platform Scripts

These scripts remain available for users who already know the flow.

macOS / Linux:

```bash
scripts/00_probe_lmstudio_image.sh store/images/2025/2025-12/example.png
scripts/10_stage2_enrich_lmstudio.sh 2025-12
scripts/20_stage3_4_build_context.sh 2025-12
```

Windows:

```bat
scripts\00_probe_lmstudio_image.bat store\images\2025\2025-12\example.png
scripts\10_stage2_enrich_lmstudio.bat 2025-12
scripts\20_stage3_4_build_context.bat 2025-12
scripts\30_stage2_4_prepare_context.bat 2025-12
scripts\40_retry_failed_images_lmstudio.bat 2025-12
```

### Long Images and Screenshots

If a long screenshot, narrow screenshot, or heavily compressed screenshot fails as a whole image, enable sliced fallback:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --slice-long-images
```

Defaults are `500px` clip height, `60px` overlap, and `2x` upscale before sending each clip to the model. To tune them:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --slice-long-images --slice-height 500 --slice-overlap 60 --slice-upscale 2
```

If you already know a batch of tall images performs poorly as whole images, skip whole-image recognition:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --force-slice-long-images
```

If your local model server allows concurrent predictions, add `--workers`:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --month 2025-12 --workers 4
```

### Image Enrichment Notes

Currently supported static image types:

- `.png`
- `.jpg`
- `.jpeg`

Explicitly skipped:

- `.mov`
- `.mp4`
- `.m4a`
- other non-static image types

Visual descriptions cover visible non-text content such as photos, objects, scenes, charts, UI layout, diagrams, and screenshots. Dense screenshots or photographed notes keep the most important text instead of attempting full verbatim OCR.

Image enrichment failures do not stop the whole run. Each completed image is saved immediately. Records that still fail keep `status=failed` and the final error message. The next run skips successful records and continues with failed or unfinished records.

On Windows, if another app is using `store/image.enriched.jsonl`, saving briefly retries before failing. If it still fails, close the app that is viewing or editing that file and rerun; the latest attempted output is kept at `store/image.enriched.jsonl.tmp`.

To rerun successful records:

```bash
python scripts/enrich_images.py --store-root store --provider lmstudio --overwrite
```

### Manually Write Back External Recognition

If you fix failed images with an external model or manual recognition, only edit the enrichment fields for the matching `image_id` in `store/image.enriched.jsonl`. Do not edit `store/image.raw.jsonl`.

| Content | Field |
| --- | --- |
| Text in the image | `ocr_text` |
| Visual description | `visual_description` |
| External model name | `model_name` |
| Manual backfill marker | `prompt_version`, `run_id` |
| Success state | `status: "success"` |
| Cleared failure | `error_message: null` |

After writing back, validate and regenerate downstream files:

```bash
python scripts/validate_enriched_images.py --store-root store
python scripts/merge_monthly.py --store-root store --monthly-root monthly --month 2025-04
python scripts/validate_monthly.py --store-root store --monthly-root monthly --month 2025-04
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-04 --overwrite
python scripts/validate_chunks.py --monthly-root monthly --chunks-root llm_chunks --month 2025-04
```

### Optional: Build Local Reports

Mock report:

```bash
python scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider mock
python scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports
```

LM Studio text model report:

```bash
python scripts/build_reports.py --chunks-root llm_chunks --reports-root reports --provider lmstudio --month 2025-12 --overwrite
python scripts/validate_reports.py --chunks-root llm_chunks --reports-root reports --month 2025-12 --summary
```

If you use OpenRouter or another external model for final reporting, you can skip this section.

## Stage 4 Chunks

Chunks are the final context files for LLMs.

Each chunk includes at least:

- `chunk_id`
- `month`
- `source_memo_ids`
- `created_at_range`
- `token_estimate`
- `text`
- `source_items`
- `resolved_links` (empty array when no link map is used)

Notes:

- `text` is the text field for the model to read directly.
- `source_items` keeps source memos and image enrichment records for traceability.
- A memo is the atomic unit; v1 does not split one memo across multiple chunks.
- `failed` and `skipped` images are not fabricated into text, but they remain traceable in structured fields.

The current strategy packs memos sequentially by time. The default target size is about `1200` estimated tokens. Token estimation is deterministic and heuristic; it is not meant to exactly match a specific model tokenizer.

## Bi-directional Link Resolution (Notion Database)

Internal links between memos inside a Flomo export are bare URLs like
`https://v.flomoapp.com/mine/?memo_id=XXX`, where `XXX` is a base64-encoded
internal id. The export itself contains **no id-to-content mapping**, so an
LLM cannot see the relations you built manually in Flomo.

The Notion flomo database fills that gap. The easiest path: hand the
`import` script the shared database link and it reads the local Notion
desktop offline mirror (`%APPDATA%/Notion/notion.db`) directly - no export,
no token, no network:

```bash
# 1. Read the Notion offline mirror and build the map (use your own db link):
python scripts/import_notion_links.py --notion-url "https://app.notion.com/p/<database-page-id>" --store-root store

# 2. Validate the map:
python scripts/validate_link_map.py --store-root store --summary

# 3. Rebuild chunks so links become LLM-readable references:
python scripts/build_chunks.py --monthly-root monthly --chunks-root llm_chunks \
    --link-map store/link_map.json --overwrite
```

Parsing Notion export files (.zip / .csv / .md / directory) offline also works:

```bash
python scripts/import_notion_links.py --input export.zip --store-root store
```

Replacement effect (inside a chunk's `text`):

- Before: `...usefulhttps://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg`
- After: `...useful〔关联 MEMO 2023-04-15「心法就是用心看世界的方法」〕`
- Backlinks: a linked memo's block gains a `[RELATED]` section listing its `linked_from` sources.
- Structured field: chunks gain a `resolved_links` array with `from_memo_id`, `to_internal_id`, `to_memo_id`, `to_created_at`, `to_snippet`.

Flomo-to-Notion sync quirks the parser handles:

- Memo content is stored as the page title, **truncated to 50 chars** - fine
  as a reference snippet; matching pipeline memos falls back from exact to
  unique-prefix to prefix+date.
- `关联自` URLs sometimes carry truncated base64 ids - recovered via unique
  prefix match against the known id set.
- If the Notion database only synced some memos, unresolved links stay verbatim and are counted.

Rules:

- Original `memo_text` in `source_items` stays untouched; only the rendered
  `text` is rewritten - the Stage 1 fact layer is unaffected.
- Links the map cannot resolve are **kept verbatim**, never silently dropped;
  build stats report resolved / unresolved counts separately.
- `store/link_map.json` is a local cache; re-run
  `import_notion_links.py --overwrite` after the Notion data changes.
- Without `--link-map` the behavior is exactly as before.

## Developer: Structure and Tests

Source layout:

```text
src/flomo_pipeline/
├── common/
├── extract/
├── enrich/
├── merge/
├── chunk/
├── sync/                 # Safe ZIP inbox, import state, and complete snapshot publishing
└── report/
```

The public project name is `flomo-transcriber`. The internal Python import package remains `flomo_pipeline` for compatibility with existing scripts and tests.

`common/` contains shared file I/O and validation report helpers. Each stage still keeps its own runner, validator, and data models.

Common commands:

```bash
python -m pytest
python -m mypy src
python scripts/check_open_source_readiness.py
```

GUI frontend check:

```bat
cd gui
cmd /c npm run build
```

GUI packaging check:

```bat
pip install -e .[gui]
cd gui
cmd /c npm run sidecar
cmd /c npm run tauri:build:nsis
```

Makefile shortcuts:

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
make import-notion-links INPUT=<notion-export.zip>
make validate-link-map
make test
```

Code principles:

- Each stage reads upstream files and writes its own derived artifact.
- Stage 1 raw JSONL is the truth layer and must not be rewritten by downstream stages.
- Derived outputs must be regenerable.
- Path fields must stay relative.
- Important outputs must have validators.

## Agent: Boundaries and Contracts

If you are an AI agent taking over this repo, read these first:

1. `AGENTS.md`
2. `README.md` or `README.en.md`
3. `pyproject.toml`
4. `tests/`

Do not default to refactoring existing stages. Current boundaries:

- Stage 1: `raw -> store/*.raw.jsonl`
- Stage 2: `store/image.raw.jsonl -> store/image.enriched.jsonl`
- Stage 3: `store/*.jsonl -> monthly/YYYY-MM.enriched.jsonl`
- Stage 4: `monthly/YYYY-MM.enriched.jsonl -> llm_chunks/YYYY-MM/*.json`
- Stage 5: `llm_chunks/YYYY-MM/*.json -> reports/YYYY-MM.report.*`
- Notion link resolution: `Notion database/export -> store/link_map.json -> Stage 4 link replacement`

When adding features:

- Do not commit real user data.
- Do not treat `monthly`, `chunk`, or `report` as a new truth layer.
- Do not silently drop `failed` or `skipped` images.
- Do not call LLMs from Stage 4.
- Do not add video or audio understanding to Stage 2 unless a new stage design is explicitly approved.
- Update docs when user-visible behavior changes.

Minimum delivery checks:

```bash
python -m pytest
python scripts/check_open_source_readiness.py
```

## Schema Quick Reference

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

`images` preserves the key Stage 2 fields, including `image_id`, paths, OCR, visual description, model metadata, `status`, and `error_message`.

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

- `schema_version` (`link-map-v1`)
- `entries`: keyed by flomo internal id; each entry has `internal_id`,
  `memo_url`, `content`, `created_at`, `pipeline_memo_id` (nullable),
  `backlink_ids`

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

Real Flomo exports and derived outputs should not be committed to a public repository. Before publishing, run:

```bash
python scripts/check_open_source_readiness.py
```

The check confirms that real data from these directories is not tracked by Git:

- `raw/`
- `store/`
- `monthly/`
- `llm_chunks/`
- `reports/`
- `flomo-inbox/`
- `flomo-context/`
- local legacy `preview/`, if present

The old Git history of the private working repository is not suitable for direct public release. Publish from a clean orphan branch or a new public repository.
