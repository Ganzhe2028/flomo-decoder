# extract/ — Stage 1: Flomo HTML → Raw JSONL

## OVERVIEW
Parses Flomo HTML exports (`raw/YYYY/flomo@User-YYYYMMDD/*.html`) into three JSONL files and copies referenced images into `store/images/`.

## STRUCTURE
```
extract/
├── parser.py        # FlomoParser: parse_all(), parse_batch(), _html_to_markdown()
├── writer.py        # StoreWriter: raw JSONL, copied images, enriched-result ID migration
└── validator.py     # StoreValidator: 16 rules (R1-R5, C1-C11)
```

## WHERE TO LOOK
| Task | File | Notes |
|------|------|-------|
| Fix HTML parsing | `parser.py:_html_to_markdown()` | Handles `<p>`, `<br>`, `<strong>`, `<a>`, `<img>`, `<ul>/<ol>`, nested `<div>` |
| Change JSONL output schema | `parser.py:parse_batch()` → `MemoRecord` fields + `common/models.py` | Schema change = downstream impact |
| Add Stage 1 validation | `validator.py:validate()` | Returns `ValidationReport` |
| Debug missing images | `parser.py:parse_batch()` lines 212-253 | Checks `source_abs.exists()` |

## CONVENTIONS
- `body_md` is markdown converted from BeautifulSoup Tag children
- `source_relpath` uses POSIX paths (forward slashes) relative to `raw_root`
- `image_relpath` follows pattern: `store/images/YYYY/YYYY-MM/{image_id}.ext`
- Raw JSONL is the **immutable truth layer** — downstream must never rewrite it
- Exact overlap dedupe applies only across export batches and includes user, timestamp, body, image count, and within-batch occurrence; same-batch duplicates remain.
- The earliest memo/image ID stays canonical. `StoreWriter` backs up and remaps prior enrichment results, preferring successful results.
- Same timestamp with different body is retained and counted as a possible revision; deletion propagation is intentionally out of scope.

## ANTI-PATTERNS
- **NEVER rewrite `memo.raw.jsonl` / `image.raw.jsonl` after initial extraction**
- **NEVER fabricate content for failed/missing images** — use `MissingImageRecord`
- **NEVER change `body_md` content** — it's the user's original text
