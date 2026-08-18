# chunk/ — Stage 4: LLM Context Chunk Builder

## OVERVIEW
Reads `monthly/YYYY-MM.enriched.jsonl`, packs memos into time-ordered chunks (~1200 tokens each), writes `llm_chunks/YYYY-MM/*.json`. **No LLM calls happen here** — this is pure text assembly.

## STRUCTURE
```
chunk/
├── runner.py          # ChunkBuildRunner: bin-packing by created_at, render text blocks
├── token_estimator.py # estimate_tokens(): heuristic ceil(words × 1.3)
├── validator.py       # ChunkValidator: validates chunk JSON files
└── models.py          # ChunkRecord, ChunkBuildStats, ChunkSourceItem
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Change chunking strategy | `runner.py` | `_build_chunks_for_month()` — time-ordered assembly |
| Change token estimation | `token_estimator.py` | Heuristic, NOT tokenizer-exact |
| Change chunk output schema | `models.py:ChunkRecord` | `text` is LLM-readable; `source_items` retains traceability |
| Add Stage 4 validation | `validator.py` | Cross-references chunks against monthly JSONL |

## CONVENTIONS
- Memo is the smallest unit — a single memo is never split across chunks
- Default target: ~1200 tokens per chunk (heuristic)
- Token estimation: `ceil(word_count × 1.3)`, stable across platforms
- `failed` / `skipped` images kept in `source_items` (structured), NOT fabricated into `text`
- Chunks are regenerable
- Validation only treats `YYYY-MM` directories as month outputs; hidden/tool directories are ignored.

## ANTI-PATTERNS
- **NEVER call any LLM/VLM** in Stage 4 — this is read-only assembly
- **NEVER split a single memo** across multiple chunks
- **NEVER fabricate text** for failed/skipped images in the `text` field
