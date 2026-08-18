#!/usr/bin/env python3

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BLOCKED_TRACKED_PREFIXES = (
    "raw/",
    "store/",
    "monthly/",
    "llm_chunks/",
    "reports/",
    "preview/",
    "flomo-inbox/",
    "flomo-context/",
)
ALLOWED_TRACKED_PRIVATE_PLACEHOLDERS = {
    "raw/.gitkeep",
    "store/.gitkeep",
    "monthly/.gitkeep",
    "llm_chunks/.gitkeep",
    "reports/.gitkeep",
    "preview/.gitkeep",
}
SECRET_KEY_RE = re.compile(
    r"(OPENAI_API_KEY|ANTHROPIC_API_KEY|OPENROUTER_API_KEY|"
    r"FLOMO_(VLM|LLM)_API_KEY)\s*=\s*(.+)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|password\s*=|secret\s*=)",
    re.IGNORECASE,
)
PRIVATE_TEXT_RE = re.compile(
    r"(/Users/[^\\s)]+|"
    r"C:\\\\Users\\\\[^\\s)]+|"
    r"flomo@Isaac|"
    r"IsaacBao|"
    r"IsaacsAir|"
    r"baolecheng)",
    re.IGNORECASE,
)


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _release_files() -> list[str]:
    output = _run(["git", "ls-files", "--cached", "--others", "--exclude-standard"])
    return [line for line in output.splitlines() if line.strip()]


def _scan_tracked_files(paths: list[str]) -> list[str]:
    findings: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if raw_path in ALLOWED_TRACKED_PRIVATE_PLACEHOLDERS:
            continue
        if raw_path.startswith(BLOCKED_TRACKED_PREFIXES):
            findings.append(f"tracked private output path: {raw_path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except FileNotFoundError:
            continue

        if _has_secret(text):
            findings.append(f"possible secret in tracked file: {raw_path}")
        if raw_path != "scripts/check_open_source_readiness.py" and PRIVATE_TEXT_RE.search(text):
            findings.append(f"private identifier/path in tracked file: {raw_path}")
    return findings


def _has_secret(text: str) -> bool:
    for line in text.splitlines():
        if SECRET_VALUE_RE.search(line):
            return True

        match = SECRET_KEY_RE.search(line)
        if match is None:
            continue
        value = match.group(3).strip().strip('"').strip("'")
        if not value or value in {"<key>", "<your-key>", "your-key"}:
            continue
        if value.startswith("your-") or value.startswith("<your-"):
            continue
        return True

    return False


def _ignored_private_outputs() -> list[str]:
    warnings: list[str] = []
    for directory in BLOCKED_TRACKED_PREFIXES:
        root = Path(directory)
        if not root.exists():
            continue
        real_files = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != ".gitkeep"
        ]
        if real_files:
            warnings.append(
                f"{directory} has ignored local data ({len(real_files)} file(s)); "
                "do not zip or manually upload the working tree"
            )
    return warnings


def main() -> None:
    try:
        tracked = _release_files()
    except RuntimeError as exc:
        print(f"readiness check failed: {exc}", file=sys.stderr)
        sys.exit(2)

    findings = _scan_tracked_files(tracked)
    warnings = _ignored_private_outputs()

    for warning in warnings:
        print(f"WARNING: {warning}")

    if findings:
        for finding in findings:
            print(f"ERROR: {finding}")
        sys.exit(1)

    print("Open-source readiness check passed for tracked and untracked release files.")


if __name__ == "__main__":
    main()
