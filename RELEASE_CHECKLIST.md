# Open Source Release Checklist

Use this checklist before publishing a public release.

## Current Tree

- [ ] `git status --short --ignored` shows no tracked private data.
- [ ] `git ls-files` contains only code, tests, docs, config, and `.gitkeep`.
- [ ] `raw/`, `store/`, `monthly/`, `llm_chunks/`, `reports/`, `flomo-inbox/`,
      `flomo-context/`, and local
      `preview/` if present contain no tracked real data.
- [ ] `.env` and `.env.*` files are ignored.
- [ ] `.env.example` contains placeholders only.

## Validation

- [ ] `python -m pytest`
- [ ] `python scripts/check_open_source_readiness.py`
- [ ] GUI version agrees across `package.json`, `package-lock.json`, `Cargo.toml`, and `tauri.conf.json`.
- [ ] The PyInstaller sidecar and NSIS installer were rebuilt after Python or GUI changes.

## History

- [ ] Public release is created from a clean orphan branch or clean public repo.
- [ ] Old private history is not made public.
- [ ] Remote visibility is not changed until the clean release branch is ready.

## Manual Review

- [ ] README examples do not contain private paths or real user data.
- [ ] Test fixtures are synthetic.
- [ ] No screenshots, exports, or generated private outputs are included.
