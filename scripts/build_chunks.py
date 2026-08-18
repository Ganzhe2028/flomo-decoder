#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flomo_pipeline.chunk import ChunkBuildRunner
from flomo_pipeline.links import LinkMap


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build llm chunk files from monthly/YYYY-MM.enriched.jsonl"
    )
    parser.add_argument(
        "--monthly-root",
        type=Path,
        default=Path("monthly"),
        help="Path to the monthly input root",
    )
    parser.add_argument(
        "--chunks-root",
        type=Path,
        default=Path("llm_chunks"),
        help="Path to the chunk output root",
    )
    parser.add_argument("--month", default=None, help="Build only one month, e.g. 2025-12")
    parser.add_argument(
        "--link-map",
        type=Path,
        default=None,
        help="Optional store/link_map.json to resolve flomo internal memo links",
    )
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=1200,
        help="Soft target tokens per chunk",
    )
    parser.add_argument(
        "--hard-max-tokens",
        type=int,
        default=1600,
        help="Reserved hard ceiling for future use",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing chunk files for target months",
    )
    args = parser.parse_args()

    link_map: LinkMap | None = None
    if args.link_map is not None:
        link_map_path = args.link_map.resolve()
        if not link_map_path.exists():
            parser.error(f"link map not found: {link_map_path}")
        link_map = LinkMap.load(link_map_path)

    _, stats = ChunkBuildRunner(
        monthly_root=args.monthly_root.resolve(),
        chunks_root=args.chunks_root.resolve(),
        month=args.month,
        target_tokens=args.target_tokens,
        hard_max_tokens=args.hard_max_tokens,
        overwrite=args.overwrite,
        link_map=link_map,
    ).run()

    print(stats.format_summary())
    print(f"Output dir: {args.chunks_root.resolve()}")


if __name__ == "__main__":
    main()
