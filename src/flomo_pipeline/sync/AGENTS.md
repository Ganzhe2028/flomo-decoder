# sync/ — Incremental ZIP Import and Snapshot Publishing

## OVERVIEW
Receives a Flomo ZIP, validates and archives it, records import state, then publishes a complete immutable chunk snapshot. This module does not call LM Studio; workflow orchestration remains in `workflow.py`.

## STRUCTURE
```
sync/
├── importer.py     # ZIP hashing, archive/import naming, import manifest;
│                   #   safe extraction lives in common/archive.py
└── publisher.py    # Snapshot copy, file hashes, manifest.json, atomic latest.json
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Change ZIP acceptance or safety limits | `common/archive.py:safe_extract_zip()` | Shared with links/Notion parsing; traversal, symlink, size, CRC checks |
| Change import state | `importer.py:ImportManifestStore` | `raw/.import-manifest.json`, keyed by ZIP SHA-256 |
| Change snapshot format | `publisher.py` | Full `llm_chunks/` copy and release manifest |
| Change import workflow order | `../workflow.py:import_and_publish()` | Queue, build, validate, publish, final status |

## CONVENTIONS
- Identical ZIP content is imported once; filename alone is not identity.
- Same-name/different-content exports receive a hash suffix.
- Extract into a temporary directory and validate before moving under `raw/YYYY/`.
- `latest.json` is written atomically after the snapshot and its manifest are complete.
- Next export start date is the date of the latest successfully published memo, inclusive; never add one day.
- Snapshots contain chunks and manifests only, never raw exports, copied images, model settings, or workspace files.

## ANTI-PATTERNS
- **NEVER trust ZIP member paths or extract before safety checks.**
- **NEVER update `latest.json` before all validators pass.**
- **NEVER delete old snapshots automatically in v1.**
- **NEVER treat a matching filename as proof that ZIP content is identical.**
