from __future__ import annotations

import json
from typing import TYPE_CHECKING

from flomo_pipeline.extract import FlomoParser, StoreValidator, StoreWriter
from flomo_pipeline.extract.validator import Rule
from tests.conftest import write_jsonl

if TYPE_CHECKING:
    from pathlib import Path


def test_validator_passes_generated_store(sample_raw_root: Path, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    report = StoreValidator(store_root=store_root, raw_root=sample_raw_root).validate()
    assert report.ok, report.format_detail()


def test_validator_catches_image_count_mismatch(sample_raw_root: Path, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    memo_path = store_root / "memo.raw.jsonl"
    records = [
        json.loads(line)
        for line in memo_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records[1]["image_count"] = 99
    write_jsonl(memo_path, records)

    report = StoreValidator(store_root=store_root, raw_root=sample_raw_root).validate()
    assert not report.ok
    assert any(violation.rule == Rule.C3_IMAGE_COUNT_CONSISTENT for violation in report.errors)


def test_validator_catches_existing_missing_source(sample_raw_root: Path, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    missing_path = store_root / "missing_image.raw.jsonl"
    records = [
        json.loads(line)
        for line in missing_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    existing_source = "2026/flomo@ExampleUser-20260304/file/2026-03-02/abc123/photo.png"
    records[0]["source_relpath"] = existing_source
    write_jsonl(missing_path, records)

    report = StoreValidator(store_root=store_root, raw_root=sample_raw_root).validate()
    assert not report.ok
    assert any(violation.rule == Rule.C9_SOURCE_FILE_EXPECTATION for violation in report.errors)


def test_validator_accepts_image_only_memo(sample_raw_root: Path, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    memo_path = store_root / "memo.raw.jsonl"
    records = [
        json.loads(line)
        for line in memo_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records[1]["body_md"] = ""
    write_jsonl(memo_path, records)

    report = StoreValidator(store_root=store_root, raw_root=sample_raw_root).validate()
    assert report.ok, report.format_detail()


def test_validator_rejects_memo_without_text_or_images(
    sample_raw_root: Path,
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    memo_path = store_root / "memo.raw.jsonl"
    records = [
        json.loads(line)
        for line in memo_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records[0]["body_md"] = ""
    write_jsonl(memo_path, records)

    report = StoreValidator(store_root=store_root, raw_root=sample_raw_root).validate()
    assert not report.ok
    assert any(violation.rule == Rule.C12_MEMO_HAS_CONTENT for violation in report.errors)
