# Contributing

This repository keeps flomo-transcriber local-file based and stage oriented.

## Development

Install development dependencies:

```bash
pip install -e .[dev]
```

Run tests:

```bash
python -m pytest
```

## Data Rules

Do not commit real Flomo exports, copied images, generated JSONL, generated
chunks, reports, screenshots, logs, or local `.env` files.

Use `.env.example` for configuration examples.

## Pull Requests

Keep changes scoped to one pipeline layer when possible:

- Stage 1: extract and raw validation
- Stage 2: image enrichment
- Stage 3: monthly merge
- Stage 4: chunk building
- Stage 5: report building
- Import and delivery: ZIP safety, overlap deduplication, import state, and snapshot publishing

Update README or other docs when user-visible behavior changes.
