#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flomo_pipeline.workflow import (  # noqa: E402
    WorkflowOptions,
    WorkflowPaths,
    _normalize_month,
    display_path,
    load_env_file,
    project_path,
    python_executable,
    require_vlm_config,
    run_action,
)


def _project_path(path: Path) -> Path:
    return project_path(PROJECT_ROOT, path)


def _display_path(path: Path) -> str:
    return display_path(PROJECT_ROOT, path)


def _python_executable() -> str:
    return python_executable()


def _load_env_file(path: Path) -> list[str]:
    return load_env_file(path)


def _with_month(command: list[str], month: str | None) -> list[str]:
    if not month:
        return command
    return [*command, "--month", month]


def _require_vlm_config(*, include_retry: bool = False) -> None:
    require_vlm_config(include_retry=include_retry)


def _prompt_action() -> str | None:
    print("flomo-transcriber guide")
    print("1. First run: build LLM chunks from raw/")
    print("2. Daily update: refresh LLM chunks after raw/ changes")
    print("3. Probe one image with LM Studio")
    print("4. Retry failed image records")
    print("5. Import a Flomo ZIP and publish a sync snapshot")
    print("q. Quit")
    choice = input("Choose: ").strip().lower()
    actions = {
        "1": "first",
        "2": "daily",
        "3": "probe",
        "4": "retry",
        "5": "import",
        "q": None,
        "quit": None,
        "exit": None,
    }
    if choice not in actions:
        print("Unknown choice.", file=sys.stderr)
        raise SystemExit(2)
    return actions[choice]


def _prompt_month() -> str | None:
    month = input("Month YYYY-MM, or empty for all months: ").strip()
    return _normalize_month(month)


def _prompt_provider() -> str:
    provider = input("Image provider [lmstudio/mock] (default lmstudio): ").strip().lower()
    if not provider:
        return "lmstudio"
    if provider not in {"lmstudio", "mock"}:
        print("Provider must be lmstudio or mock.", file=sys.stderr)
        raise SystemExit(2)
    return provider


def _prompt_image() -> Path:
    image = input("Image path: ").strip()
    if not image:
        print("Image path is required.", file=sys.stderr)
        raise SystemExit(2)
    return Path(image)


def _prompt_zip() -> Path:
    zip_path = input("Flomo ZIP path: ").strip()
    if not zip_path:
        print("Flomo ZIP path is required.", file=sys.stderr)
        raise SystemExit(2)
    return Path(zip_path)


def _prompt_publish_root() -> Path:
    publish_root = input("Published context folder (default flomo-context): ").strip()
    return Path(publish_root or "flomo-context")


def _build_chunks_from_raw(
    *,
    raw_root: Path,
    store_root: Path,
    monthly_root: Path,
    chunks_root: Path,
    provider: str,
    month: str | None,
    workers: int,
) -> None:
    paths = WorkflowPaths(
        project_root=PROJECT_ROOT,
        raw_root=raw_root,
        store_root=store_root,
        monthly_root=monthly_root,
        chunks_root=chunks_root,
    )
    run_action(
        "first",
        paths,
        WorkflowOptions(provider=provider, month=month, workers=workers),
    )


def _probe_image(image: Path) -> None:
    paths = WorkflowPaths(
        project_root=PROJECT_ROOT,
        raw_root=PROJECT_ROOT / "raw",
        store_root=PROJECT_ROOT / "store",
        monthly_root=PROJECT_ROOT / "monthly",
        chunks_root=PROJECT_ROOT / "llm_chunks",
    )
    run_action("probe", paths, WorkflowOptions(image=image))


def _retry_failed_images(
    *,
    store_root: Path,
    provider: str,
    month: str | None,
    rounds: int,
    workers: int,
) -> None:
    paths = WorkflowPaths(
        project_root=PROJECT_ROOT,
        raw_root=PROJECT_ROOT / "raw",
        store_root=store_root,
        monthly_root=PROJECT_ROOT / "monthly",
        chunks_root=PROJECT_ROOT / "llm_chunks",
    )
    run_action(
        "retry",
        paths,
        WorkflowOptions(provider=provider, month=month, rounds=rounds, workers=workers),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Guided flomo-transcriber workflow")
    parser.add_argument(
        "--action",
        choices=["first", "daily", "probe", "retry", "import"],
        default=None,
        help="Skip the menu and run one guide action",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--raw-root", type=Path, default=Path("raw"))
    parser.add_argument("--store-root", type=Path, default=Path("store"))
    parser.add_argument("--monthly-root", type=Path, default=Path("monthly"))
    parser.add_argument("--chunks-root", type=Path, default=Path("llm_chunks"))
    parser.add_argument("--publish-root", type=Path, default=None)
    parser.add_argument("--month", default=None, help="Run one month, e.g. 2025-12")
    parser.add_argument("--provider", choices=["lmstudio", "mock"], default=None)
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--zip", dest="zip_path", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if args.rounds <= 0:
        print("--rounds must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)
    if args.workers <= 0:
        print("--workers must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)

    args_month = _normalize_month(args.month)

    env_file = _project_path(args.env_file)
    loaded = _load_env_file(env_file)
    if loaded:
        print(f"Loaded configuration: {_display_path(env_file)}")

    interactive = args.action is None
    action = args.action or _prompt_action()
    if action is None:
        return

    month = _prompt_month() if interactive and action in {"first", "daily", "retry"} else args_month
    provider = args.provider
    if action in {"first", "daily", "retry", "import"}:
        provider = provider or (_prompt_provider() if interactive else "lmstudio")

    raw_root = _project_path(args.raw_root)
    store_root = _project_path(args.store_root)
    monthly_root = _project_path(args.monthly_root)
    chunks_root = _project_path(args.chunks_root)
    if args.publish_root is not None:
        publish_root = _project_path(args.publish_root)
    elif interactive and action == "import":
        publish_root = _project_path(_prompt_publish_root())
    else:
        publish_root = None
    paths = WorkflowPaths(
        project_root=PROJECT_ROOT,
        raw_root=raw_root,
        store_root=store_root,
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        publish_root=publish_root,
    )

    if action in {"first", "daily"}:
        run_action(
            action,
            paths,
            WorkflowOptions(provider=provider or "lmstudio", month=month, workers=args.workers),
        )
        return

    if action == "probe":
        image = args.image or (_prompt_image() if interactive else None)
        if image is None:
            print("--image is required for probe.", file=sys.stderr)
            raise SystemExit(2)
        run_action("probe", paths, WorkflowOptions(image=image))
        return

    if action == "retry":
        run_action(
            "retry",
            paths,
            WorkflowOptions(
                provider=provider or "lmstudio",
                month=month,
                rounds=args.rounds,
                workers=args.workers,
            ),
        )
        return

    if action == "import":
        zip_path = args.zip_path or (_prompt_zip() if interactive else None)
        if zip_path is None:
            print("--zip is required for import.", file=sys.stderr)
            raise SystemExit(2)
        if publish_root is None:
            print("--publish-root is required for import.", file=sys.stderr)
            raise SystemExit(2)
        run_action(
            "import",
            paths,
            WorkflowOptions(
                provider=provider or "lmstudio",
                workers=args.workers,
                zip_path=zip_path,
            ),
        )
        return

    raise AssertionError(f"Unhandled action: {action}")


if __name__ == "__main__":
    main()
