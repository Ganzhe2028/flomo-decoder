# Security Policy

## Supported Versions

This project is pre-1.0. Security fixes are made on the default branch.

## Reporting a Vulnerability

Do not open a public issue for secrets, private data exposure, or other
sensitive reports.

If you find a vulnerability, contact the repository owner privately through
GitHub.

## Data Safety Notes

This project is designed to process personal Flomo exports locally. Do not
commit real exports or generated private outputs.

The following directories are intentionally ignored except for tracked placeholders:
- `raw/`
- `store/`
- `monthly/`
- `llm_chunks/`
- `reports/`
- `flomo-inbox/`
- `flomo-context/`
- local `preview/` if present

Published snapshots contain personal memo text and image-derived descriptions. Syncthing encrypts transport, but files remain readable on both devices; protect both endpoints with account access controls and disk encryption.

Archive inputs are never extracted blindly: both the Flomo ZIP inbox
(`sync`) and Notion export parsing (`links`) go through
`common/archive.py:safe_extract_zip()`, which rejects path traversal
(`..`, absolute paths, drive-letter colons), symlinks, oversized archives
and members, and verifies CRC integrity before extraction.

Before publishing or sharing a fork, run:

```bash
python scripts/check_open_source_readiness.py
```
