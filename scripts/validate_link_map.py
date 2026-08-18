#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flomo_pipeline.links import LinkMapValidator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate store/link_map.json (flomo internal link resolution map)"
    )
    parser.add_argument(
        "--store-root",
        type=Path,
        default=Path("store"),
        help="Path to the store root",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only the summary line",
    )
    args = parser.parse_args()

    report = LinkMapValidator(store_root=args.store_root.resolve()).validate()
    print(report.format_summary())
    if not report.ok and not args.summary:
        print(report.format_detail())
    if not report.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
