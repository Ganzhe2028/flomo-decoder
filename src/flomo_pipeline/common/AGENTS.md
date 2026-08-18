# common/ — Shared Cross-Stage Utilities

## OVERVIEW
Shared file I/O, validation reporting, and frozen dataclass models used by all pipeline stages. No stage-specific business logic.

## STRUCTURE
```
common/
├── models.py        # MemoRecord, ImageRecord, MissingImageRecord, ParseResult + dedupe metadata
├── io.py            # write_jsonl/read_jsonl (with atomic mode), write_json, to_plain_dict,
│                    #   _sanitize_jsonl_value (escapes \u2028/\u2029 for safe JSONL)
├── validation.py    # Severity(ERROR|WARNING), Violation(frozen), ValidationReport
│                    #   load_jsonl_for_validation, load_json_for_validation
└── archive.py       # safe_extract_zip() + UnsafeArchiveError + size/count limits:
                     #   rejects ../, absolute paths, drive colons, symlinks; CRC via testzip()
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Add a new shared model | `models.py` | Keep frozen, use `to_dict()` for serialization |
| Change JSONL I/O | `io.py` | `write_jsonl` escapes Unicode line separators; `read_jsonl` splits on `\n` only |
| Add validation rules | `validation.py` | `Violation` has rule, severity, message, table, line, record_id |
| Extract a ZIP safely | `archive.py:safe_extract_zip()` | Shared by sync (Flomo ZIP) and links (Notion export) |
| Debug JSONL parsing | `validation.py:load_jsonl_for_validation` | Uses `split("\n")` NOT `splitlines()` — see below |

## CONVENTIONS
- `to_plain_dict()` is the single serialization path: dataclass → dict → `json.dumps(ensure_ascii=False)`
- `_sanitize_jsonl_value()` replaces raw `\u2028`/`\u2029` with escape sequences BEFORE writing
- `read_jsonl()` and `load_jsonl_for_validation()` use `split("\n")` + `rstrip("\r")` — NOT `splitlines()` — because Unicode line separators (`\u2028`, `\u2029`) can legitimately appear inside JSON string values but `splitlines()` splits on them
- `ParseResult` carries deduplicated/revision counts and image ID aliases; the extract layer owns the rules that populate them.

## ANTI-PATTERNS
- **NEVER put stage-specific business rules here.** This is shared infrastructure only.
- **NEVER use `str.splitlines()` for JSONL reading.** See `\u2028` bug fix (2026-06-24).
- **NEVER call `ZipFile.extractall()` directly** in any stage — always go through `safe_extract_zip()`.
