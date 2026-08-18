#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flomo_pipeline.common.archive import UnsafeArchiveError
from flomo_pipeline.common.io import read_jsonl
from flomo_pipeline.links import LINK_MAP_FILENAME, build_link_map, parse_notion_input
from flomo_pipeline.links.notion_offline import find_notion_db, parse_notion_db

if TYPE_CHECKING:
    from flomo_pipeline.links.models import NotionMemoRow

_HEX_ID_RE = re.compile(r"([0-9a-f]{32})", re.IGNORECASE)
_NOTION_URL_PAGE_ID_RE = re.compile(r"/p/[^/?]*?([0-9a-f]{32})[^0-9a-f]", re.IGNORECASE)


def _extract_notion_url_id(url: str) -> str | None:
    """Extract the 32-hex page/database id from an app.notion.com URL."""
    for pattern in (_NOTION_URL_PAGE_ID_RE, _HEX_ID_RE):
        match = pattern.search(url)
        if match is not None:
            return match.group(1)
    return None


def _fetch_rows(args: argparse.Namespace) -> tuple[list[NotionMemoRow], list[str]]:
    if args.notion_url:
        db_path = args.notion_db
        if db_path is None:
            db_path = find_notion_db()
        if db_path is None or not db_path.is_file():
            raise SystemExit(
                "Notion desktop offline mirror (notion.db) not found. "
                "Install and open the Notion desktop app, or pass --notion-db."
            )
        page_id = _extract_notion_url_id(args.notion_url)
        if page_id is None:
            raise SystemExit(f"Could not extract a page id from: {args.notion_url}")
        print(f"Reading Notion offline mirror: {db_path}")
        rows, warnings = parse_notion_db(db_path, page_id=page_id)
        return rows, warnings

    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"Notion input not found: {input_path}")
    if input_path.suffix.lower() in (".db", ".sqlite"):
        print(f"Reading Notion offline mirror: {input_path}")
        return parse_notion_db(input_path, page_id=None)
    return parse_notion_input(input_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a Notion flomo database and build store/link_map.json "
            "to resolve flomo internal memo links inside chunks"
        )
    )
    parser.add_argument(
        "--notion-url",
        default=None,
        help=(
            "app.notion.com URL of the flomo database. Reads the local Notion "
            "desktop offline mirror directly - no export or token needed"
        ),
    )
    parser.add_argument(
        "--notion-db",
        type=Path,
        default=None,
        help="Override the path to the Notion offline mirror (notion.db)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Notion export (.csv, .md, directory, .zip) or a notion.db mirror file",
    )
    parser.add_argument(
        "--store-root",
        type=Path,
        default=Path("store"),
        help="Pipeline store root (memo.raw.jsonl lives here)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output path (default: <store-root>/{LINK_MAP_FILENAME})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing link map",
    )
    args = parser.parse_args()

    if args.notion_url is None and args.input is None:
        parser.error("provide either --notion-url or --input")
    if args.notion_url is not None and args.input is not None:
        parser.error("--notion-url and --input are mutually exclusive")

    rows: list[NotionMemoRow]
    warnings: list[str]
    try:
        rows, warnings = _fetch_rows(args)
    except (UnsafeArchiveError, zipfile.BadZipFile) as exc:
        print(f"Failed to read Notion input: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"[warning] {warning}")
    if not rows:
        print("No memo rows with flomo links were parsed. Nothing to import.", file=sys.stderr)
        return 1

    store_root = args.store_root.resolve()
    pipeline_memos = read_jsonl(store_root / "memo.raw.jsonl")
    link_map = build_link_map(rows, pipeline_memos)

    output_path = (args.output or (store_root / LINK_MAP_FILENAME)).resolve()
    if output_path.exists() and not args.overwrite:
        print(f"{output_path} already exists. Use --overwrite to rebuild it.")
        return 0

    link_map.save(output_path)

    matched = sum(1 for entry in link_map.entries.values() if entry.pipeline_memo_id is not None)
    backlink_edges = sum(len(entry.backlink_ids) for entry in link_map.entries.values())
    ai_insights = sum(1 for row in rows if row.ai_insight)
    print(
        f"Notion rows imported: {len(link_map.entries)}\n"
        f"Matched to pipeline memos: {matched}/{len(link_map.entries)}\n"
        f"Backlink (关联自) edges: {backlink_edges}\n"
        f"AI insight rows: {ai_insights}"
    )
    print(f"Link map written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
