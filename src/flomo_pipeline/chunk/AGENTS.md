# chunk/ — Stage 4: LLM Context Chunk Builder

## OVERVIEW
Reads `monthly/YYYY-MM.enriched.jsonl`, packs memos into time-ordered chunks (~1200 tokens each), writes `llm_chunks/YYYY-MM/*.json`. Optionally resolves flomo internal memo links via `store/link_map.json` (built by `links/` from the Notion database) — inline references in rendered `text` plus `resolved_links` structured data. **No LLM calls happen here** — this is pure text assembly.

## STRUCTURE
```
chunk/
├── runner.py          # ChunkBuildRunner: bin-packing by created_at, render text blocks,
│                      #   link resolution + [RELATED] backlink blocks (consumes LinkMap)
├── token_estimator.py # estimate_tokens(): heuristic ceil(words × 1.3)
├── validator.py       # ChunkValidator: validates chunk JSON files (C1-C11)
└── models.py          # ChunkRecord, ChunkBuildStats, ChunkSourceItem, ChunkResolvedLink
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Change chunking strategy | `runner.py` | Time-ordered assembly |
| Change token estimation | `token_estimator.py` | Heuristic, NOT tokenizer-exact |
| Change chunk output schema | `models.py:ChunkRecord` | `text` is LLM-readable; `source_items` retains traceability; `resolved_links` lists resolved flomo links |
| Change link resolution behavior | `runner.py` + `../links/resolver.py` | Replace flomo URLs in rendered text only; `source_items` stay verbatim |
| Add Stage 4 validation | `validator.py` | Cross-references chunks against monthly JSONL |

## CONVENTIONS
- Memo is the smallest unit — a single memo is never split across chunks
- Default target: ~1200 tokens per chunk (heuristic)
- Token estimation: `ceil(word_count × 1.3)`, stable across platforms
- `failed` / `skipped` images kept in `source_items` (structured), NOT fabricated into `text`
- `build_version` is `chunk-v2` (adds `resolved_links`; the field is always present, empty without a link map)
- Link resolution rewrites the rendered `text` only; `source_items[].memo_text` stays the Stage 1 fact-layer text. Unresolved URLs stay verbatim (no silent drops)
- Chunks are regenerable
- Validation only treats `YYYY-MM` directories as month outputs; hidden/tool directories are ignored.

## ANTI-PATTERNS
- **NEVER call any LLM/VLM** in Stage 4 — this is read-only assembly
- **NEVER split a single memo** across multiple chunks
- **NEVER fabricate text** for failed/skipped images in the `text` field
