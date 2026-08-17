from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


@dataclass(frozen=True)
class PublishResult:
    release_id: str
    snapshot_dir: Path
    manifest_path: Path
    latest_path: Path
    next_export_start_date: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    _write_json(temporary, payload)
    temporary.replace(path)


def publish_chunks_snapshot(
    *,
    chunks_root: Path,
    publish_root: Path,
    memo_created_at: list[str],
    zip_sha256: str,
    affected_months: list[str],
    deduplicated_memos: int = 0,
    failed_images: int = 0,
    image_failures: list[dict[str, str]] | None = None,
) -> PublishResult:
    valid_times = sorted(value for value in memo_created_at if len(value) >= 10)
    if not valid_times:
        raise ValueError("Cannot publish a snapshot without memo timestamps")
    earliest, latest = valid_times[0], valid_times[-1]
    next_export_start_date = latest[:10]

    chunks_root = chunks_root.resolve()
    publish_root = publish_root.resolve()
    snapshots_root = publish_root / "snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    release_id_base = f"{timestamp}-{zip_sha256[:12]}"
    release_id = release_id_base
    snapshot_dir = snapshots_root / release_id
    suffix = 1
    while snapshot_dir.exists():
        suffix += 1
        release_id = f"{release_id_base}-{suffix}"
        snapshot_dir = snapshots_root / release_id

    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=snapshots_root) as temp_name:
        temporary = Path(temp_name)
        copied_files: list[dict[str, object]] = []
        for month_dir in sorted(chunks_root.iterdir() if chunks_root.is_dir() else []):
            if not month_dir.is_dir() or MONTH_PATTERN.fullmatch(month_dir.name) is None:
                continue
            destination_month = temporary / "llm_chunks" / month_dir.name
            destination_month.mkdir(parents=True, exist_ok=True)
            for source in sorted(month_dir.glob("*.json")):
                if not source.is_file():
                    continue
                destination = destination_month / source.name
                shutil.copy2(source, destination)
                copied_files.append(
                    {
                        "path": destination.relative_to(temporary).as_posix(),
                        "sha256": _sha256(destination),
                        "size_bytes": destination.stat().st_size,
                    }
                )
        if not copied_files:
            raise ValueError(f"No chunk JSON files found under: {chunks_root}")

        manifest = {
            "version": 2,
            "release_id": release_id,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_zip_sha256": zip_sha256,
            "memo_created_at_range": {"earliest": earliest, "latest": latest},
            "affected_months": sorted(set(affected_months)),
            "deduplicated_memos": deduplicated_memos,
            "failed_images": failed_images,
            "image_failures": image_failures or [],
            "next_export_start_date": next_export_start_date,
            "files": copied_files,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(snapshot_dir)

    manifest_path = snapshot_dir / "manifest.json"
    latest_path = publish_root / "latest.json"
    _write_json_atomic(
        latest_path,
        {
            "version": 1,
            "release_id": release_id,
            "snapshot_relpath": snapshot_dir.relative_to(publish_root).as_posix(),
            "manifest_sha256": _sha256(manifest_path),
            "next_export_start_date": next_export_start_date,
        },
    )
    return PublishResult(
        release_id=release_id,
        snapshot_dir=snapshot_dir,
        manifest_path=manifest_path,
        latest_path=latest_path,
        next_export_start_date=next_export_start_date,
    )
