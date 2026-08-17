from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from flomo_pipeline.sync import UnsafeArchiveError, import_flomo_zip, publish_chunks_snapshot
from tests.conftest import SAMPLE_HTML


def _build_flomo_zip(
    root: Path,
    *,
    name: str = "flomo@ExampleUser-20260817.zip",
    html: str = SAMPLE_HTML,
) -> Path:
    source = root / "source"
    batch = source / name.removesuffix(".zip")
    batch.mkdir(parents=True)
    (batch / "ExampleUser的笔记.html").write_text(html, encoding="utf-8")
    image_one = batch / "file" / "2026-03-02" / "abc123"
    image_one.mkdir(parents=True)
    (image_one / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    image_two = batch / "file" / "2026-03-03" / "ghi789"
    image_two.mkdir(parents=True)
    (image_two / "audio_cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    zip_path = root / name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(batch.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return zip_path


def test_import_flomo_zip_is_safe_and_idempotent(tmp_path: Path) -> None:
    zip_path = _build_flomo_zip(tmp_path)
    raw_root = tmp_path / "raw"

    first = import_flomo_zip(zip_path, raw_root)
    second = import_flomo_zip(zip_path, raw_root)

    assert first.duplicate is False
    assert second.duplicate is True
    assert first.import_dir == second.import_dir
    assert (first.import_dir / "ExampleUser的笔记.html").is_file()
    manifest = json.loads((raw_root / ".import-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["imports"]) == 1
    assert manifest["imports"][0]["status"] == "received"


def test_import_flomo_zip_keeps_same_name_with_different_content(tmp_path: Path) -> None:
    first_zip = _build_flomo_zip(tmp_path / "one")
    second_zip = _build_flomo_zip(
        tmp_path / "two",
        html=SAMPLE_HTML.replace("First memo", "Changed first memo"),
    )
    raw_root = tmp_path / "raw"

    first = import_flomo_zip(first_zip, raw_root)
    second = import_flomo_zip(second_zip, raw_root)

    assert first.zip_sha256 != second.zip_sha256
    assert first.import_dir != second.import_dir
    assert second.import_dir.name.endswith(f"__{second.zip_sha256[:12]}")
    manifest = json.loads((raw_root / ".import-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["imports"]) == 2


def test_import_flomo_zip_rejects_parent_path(tmp_path: Path) -> None:
    zip_path = tmp_path / "flomo@ExampleUser-20260817.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with pytest.raises(UnsafeArchiveError, match="Unsafe ZIP path"):
        import_flomo_zip(zip_path, tmp_path / "raw")
    assert not (tmp_path / "outside.txt").exists()


def test_publish_chunks_snapshot_writes_latest_last_and_keeps_same_day(tmp_path: Path) -> None:
    chunks_root = tmp_path / "llm_chunks"
    month_root = chunks_root / "2026-08"
    month_root.mkdir(parents=True)
    chunk_path = month_root / "2026-08-0001.json"
    chunk_path.write_text('{"chunk_id":"2026-08-0001"}\n', encoding="utf-8")
    (chunks_root / ".opencode").mkdir()
    (chunks_root / ".opencode" / "private.json").write_text("{}", encoding="utf-8")

    result = publish_chunks_snapshot(
        chunks_root=chunks_root,
        publish_root=tmp_path / "publish",
        memo_created_at=["2026-08-17T00:01:00", "2026-08-17T18:51:37"],
        zip_sha256="a" * 64,
        affected_months=["2026-08"],
        deduplicated_memos=4,
        failed_images=2,
        image_failures=[
            {
                "image_id": "image-1",
                "month": "2026-08",
                "error_message": "model response was truncated",
            }
        ],
    )

    latest = json.loads(result.latest_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert latest["release_id"] == result.release_id
    assert latest["next_export_start_date"] == "2026-08-17"
    assert manifest["memo_created_at_range"]["latest"] == "2026-08-17T18:51:37"
    assert manifest["next_export_start_date"] == "2026-08-17"
    assert manifest["deduplicated_memos"] == 4
    assert manifest["failed_images"] == 2
    assert manifest["image_failures"][0]["error_message"] == "model response was truncated"
    assert [item["path"] for item in manifest["files"]] == [
        "llm_chunks/2026-08/2026-08-0001.json"
    ]
    copied = result.snapshot_dir / str(manifest["files"][0]["path"])
    assert manifest["files"][0]["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()


def test_guide_import_builds_and_publishes_with_mock_provider(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zip_path = _build_flomo_zip(tmp_path)
    raw_root = tmp_path / "raw"
    publish_root = tmp_path / "flomo-context"
    command = [
        sys.executable,
        str(repo_root / "scripts" / "guide.py"),
        "--action",
        "import",
        "--zip",
        str(zip_path),
        "--publish-root",
        str(publish_root),
        "--provider",
        "mock",
        "--raw-root",
        str(raw_root),
        "--store-root",
        str(tmp_path / "store"),
        "--monthly-root",
        str(tmp_path / "monthly"),
        "--chunks-root",
        str(tmp_path / "chunks"),
    ]

    first = subprocess.run(command, capture_output=True, text=True, check=False, cwd=repo_root)
    second = subprocess.run(command, capture_output=True, text=True, check=False, cwd=repo_root)

    assert first.returncode == 0, first.stdout + first.stderr
    assert "Next export start date: 2026-03-03" in first.stdout
    assert (publish_root / "latest.json").is_file()
    import_manifest = json.loads(
        (raw_root / ".import-manifest.json").read_text(encoding="utf-8")
    )
    assert import_manifest["imports"][0]["dedupe_schema_version"] == 1
    assert import_manifest["imports"][0]["publication_schema_version"] == 2
    assert second.returncode == 0, second.stdout + second.stderr
    assert "Already published" in second.stdout
    assert len(list((publish_root / "snapshots").iterdir())) == 1


def test_guide_import_rejects_export_without_memos(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zip_path = _build_flomo_zip(
        tmp_path,
        html=(
            "<!DOCTYPE html><html><body><div class='name'>@ExampleUser</div>"
            "</body></html>"
        ),
    )
    raw_root = tmp_path / "raw"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "import",
            "--zip",
            str(zip_path),
            "--publish-root",
            str(tmp_path / "publish"),
            "--provider",
            "mock",
            "--raw-root",
            str(raw_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    assert result.returncode == 1
    assert "contains no memos" in result.stderr
    manifest = json.loads((raw_root / ".import-manifest.json").read_text(encoding="utf-8"))
    assert manifest["imports"][0]["status"] == "failed"
    assert not (tmp_path / "publish" / "latest.json").exists()


def test_guide_import_uses_temporary_failure_exit_for_lmstudio_queue(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zip_path = _build_flomo_zip(tmp_path)
    raw_root = tmp_path / "raw"
    env = os.environ.copy()
    env.pop("FLOMO_VLM_BASE_URL", None)
    env.pop("FLOMO_VLM_MODEL", None)
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "import",
            "--zip",
            str(zip_path),
            "--publish-root",
            str(tmp_path / "publish"),
            "--provider",
            "lmstudio",
            "--env-file",
            str(tmp_path / "missing.env"),
            "--raw-root",
            str(raw_root),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 75
    assert "Queued:" in result.stdout
    manifest = json.loads((raw_root / ".import-manifest.json").read_text(encoding="utf-8"))
    assert manifest["imports"][0]["status"] == "queued"
    assert not (tmp_path / "publish" / "latest.json").exists()


def test_same_day_overlapping_export_adds_only_later_memo(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    first_zip = _build_flomo_zip(tmp_path / "first")
    later_memo = """
<div class="memo">
  <div class="time">2026-03-03 20:00:00</div>
  <div class="content"><p>Written after the first export</p></div>
</div>
"""
    second_html = SAMPLE_HTML.replace("</body>", f"{later_memo}</body>")
    second_zip = _build_flomo_zip(tmp_path / "second", html=second_html)
    raw_root = tmp_path / "raw"
    store_root = tmp_path / "store"
    publish_root = tmp_path / "publish"

    def run_import(zip_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "guide.py"),
                "--action",
                "import",
                "--zip",
                str(zip_path),
                "--publish-root",
                str(publish_root),
                "--provider",
                "mock",
                "--raw-root",
                str(raw_root),
                "--store-root",
                str(store_root),
                "--monthly-root",
                str(tmp_path / "monthly"),
                "--chunks-root",
                str(tmp_path / "chunks"),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
        )

    first = run_import(first_zip)
    second = run_import(second_zip)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    memo_records = [
        json.loads(line)
        for line in (store_root / "memo.raw.jsonl").read_text(encoding="utf-8").split("\n")
        if line
    ]
    assert len(memo_records) == 4
    later_memos = [
        record for record in memo_records if record["body_md"] == "Written after the first export"
    ]
    assert len(later_memos) == 1
    latest = json.loads((publish_root / "latest.json").read_text(encoding="utf-8"))
    assert latest["next_export_start_date"] == "2026-03-03"
    second_manifest = json.loads(
        (publish_root / latest["snapshot_relpath"] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert second_manifest["deduplicated_memos"] == 3


def test_sidecar_import_action_publishes_snapshot(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    zip_path = _build_flomo_zip(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "flomo_sidecar.py"),
            "--action",
            "import",
            "--project-root",
            str(tmp_path),
            "--zip",
            str(zip_path),
            "--publish-root",
            "flomo-context",
            "--provider",
            "mock",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Published snapshot:" in result.stdout
    assert (tmp_path / "flomo-context" / "latest.json").is_file()
