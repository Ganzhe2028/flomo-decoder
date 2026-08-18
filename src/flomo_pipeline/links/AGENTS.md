# links/ — Notion Flomo 双向链接解析

## OVERVIEW
Resolves flomo internal memo links (`https://v.flomoapp.com/mine/?memo_id=<base64>`) so
LLMs can read the relations between memos. Builds `store/link_map.json` from either the
local Notion desktop offline mirror (`notion.db`) or a Notion export file, then Stage 4
(chunk runner) consumes the map to rewrite links in rendered chunk text. Pure local;
no Notion API, no token, no network.

## STRUCTURE
```
links/
├── models.py         # NotionMemoRow, LinkMapEntry, LinkMap, ResolvedLink, TextResolution
├── notion_offline.py # parse_notion_db(): SQLite snapshot of %APPDATA%/Notion/notion.db;
│                     #   page id -> collection, title/own-link/关联自 parsing, truncated-id recovery
├── notion_parser.py  # parse_notion_input(): Notion export .csv/.md/.zip (safe_extract_zip)
├── resolver.py       # decode_internal_id, resolve_text(), render_related_block(),
│                     #   normalize_for_match(), build_link_map() (exact -> prefix -> prefix+date)
└── validator.py      # LinkMapValidator: L1-L6 rules for store/link_map.json
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Change offline mirror reading | `notion_offline.py` | Snapshot via SQLite backup API; property ids `nc@X`(link) `title` `;RVb`(date) are fixed by flomo's sync schema |
| Change export parsing | `notion_parser.py` | Column sniffing by name hints + URL coverage; 关联自/AI洞察 split; ZIP goes through `common.archive.safe_extract_zip` |
| Change link replacement format | `resolver.py:render_reference()` | `〔关联 MEMO <date>「<snippet>」〕` |
| Change matching strategy | `resolver.py:build_link_map()` | Notion titles are truncated at 50 chars: exact → unique prefix → prefix+date; first-claim-wins for sync-conflict duplicates |
| Add link map validation | `validator.py` | Backlink to unknown id is WARNING, duplicate pipeline_memo_id claim is ERROR |

## CONVENTIONS
- flomo internal ids are decimal strings; the base64 `memo_id=` param decodes to them.
- 关联自 (backlink) ids may be truncated; recover via unique prefix match against the known id set.
- `pipeline_memo_id` is a best-effort annotation; link resolution works without it.
- Unresolved links are kept verbatim and counted — never silently dropped.
- `store/link_map.json` is a local cache; rebuilt with `import_notion_links.py --overwrite`.

## ANTI-PATTERNS
- **NEVER call the Notion API** — this module reads local data only.
- **NEVER extract a Notion ZIP without `safe_extract_zip()`** (zip-slip).
- **NEVER rewrite Stage 1 JSONL** — link replacement happens in Stage 4 rendered text only.
