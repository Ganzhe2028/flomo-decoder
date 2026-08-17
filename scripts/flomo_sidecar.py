#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.exists():
    sys.path.insert(0, str(SRC_ROOT))

from flomo_pipeline.workflow import (  # noqa: E402
    WorkflowOptions,
    WorkflowPaths,
    _normalize_month,
    load_env_file,
    project_path,
    run_action,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="flomo-transcriber desktop sidecar")
    parser.add_argument(
        "--action", choices=["first", "daily", "probe", "retry", "import"], required=True
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--raw-root", type=Path, default=Path("raw"))
    parser.add_argument("--store-root", type=Path, default=Path("store"))
    parser.add_argument("--monthly-root", type=Path, default=Path("monthly"))
    parser.add_argument("--chunks-root", type=Path, default=Path("llm_chunks"))
    parser.add_argument("--publish-root", type=Path, default=None)
    parser.add_argument("--month", default=None)
    parser.add_argument("--provider", choices=["lmstudio", "mock"], default="lmstudio")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--zip", dest="zip_path", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    env_file = project_path(project_root, args.env_file)
    loaded = load_env_file(env_file)
    if loaded:
        print(f"Loaded configuration: {env_file}")

    paths = WorkflowPaths(
        project_root=project_root,
        raw_root=project_path(project_root, args.raw_root),
        store_root=project_path(project_root, args.store_root),
        monthly_root=project_path(project_root, args.monthly_root),
        chunks_root=project_path(project_root, args.chunks_root),
        publish_root=(
            project_path(project_root, args.publish_root)
            if args.publish_root is not None
            else None
        ),
    )
    options = WorkflowOptions(
        provider=args.provider,
        month=_normalize_month(args.month),
        image=args.image,
        rounds=args.rounds,
        workers=args.workers,
        zip_path=args.zip_path,
    )
    run_action(args.action, paths, options)


if __name__ == "__main__":
    main()
