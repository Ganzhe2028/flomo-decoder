# scripts/ — CLI Entry Points & Automation

## OVERVIEW
All user-facing and developer entry points. Three tiers: primary (guide.py), sidecar (flomo_sidecar.py), single-stage/debug (all others).

## STRUCTURE
```
scripts/
├── guide.py                         # ★ PRIMARY: interactive menu + --action CLI
├── flomo_sidecar.py                 # Tauri sidecar source (PyInstaller → binary)
├── run_pipeline.py                  # Legacy batch pipeline (subprocess-based)
├── extract_raw.py                   # Stage 1: raw/ → store/*.raw.jsonl
├── enrich_images.py                 # Stage 2: image enrichment (+ slicing, workers)
├── merge_monthly.py                 # Stage 3: monthly merge
├── build_chunks.py                  # Stage 4: chunk builder
├── build_reports.py                 # Stage 5: LLM report generator
├── validate_store.py                # Stage 1 validator
├── validate_enriched_images.py      # Stage 2 validator
├── validate_monthly.py              # Stage 3 validator
├── validate_chunks.py               # Stage 4 validator
├── validate_reports.py              # Stage 5 validator
├── probe_lmstudio_vlm.py            # Single-image VLM connectivity test
├── retry_failed_images.py           # Retry Stage 2 failed images
├── build_gui_sidecar.py             # PyInstaller sidecar builder (Tauri packaging)
├── check_open_source_readiness.py   # Pre-release safety audit
├── 00_probe_lmstudio_image.bat/sh   # Platform wrappers (legacy)
├── 10_stage2_enrich_lmstudio.bat/sh
├── 20_stage3_4_build_context.bat/sh
├── 30_stage2_4_prepare_context.bat  # Windows only
└── 40_retry_failed_images_lmstudio.bat
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| User-facing workflow | `guide.py` | Interactive menu + 5 actions, including ZIP import, via `workflow.run_action()` |
| Sidecar packaging | `build_gui_sidecar.py` + `flomo_sidecar.py` | PyInstaller `--onefile --noconsole` |
| Debug a single stage | `extract_raw.py`, `enrich_images.py`, etc. | All accept `--store-root`, `--month`, etc. |
| Validate output integrity | `validate_*.py` | Use `--summary` for counts, omit for full detail |

## CONVENTIONS
- Normal users: `python scripts/guide.py`. Stage scripts are for debugging/advanced use.
- All scripts inject `src/` into `sys.path` to import `flomo_pipeline`.
- Sidecar (`flomo_sidecar.py`) is identical to guide.py but pure argparse (no stdin prompts).
- Import requires `--zip` and `--publish-root`; LM Studio unavailability returns exit code 75 for GUI queueing.
- `.bat`/`.sh` scripts are legacy convenience wrappers — superseded by `guide.py`.

## ANTI-PATTERNS
- **NEVER add new stage scripts** that bypass `workflow.py` validation gates
- **NEVER run `run_pipeline.py`** without understanding it's subprocess-based (different from workflow.py)
