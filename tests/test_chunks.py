from __future__ import annotations

import json
from typing import TYPE_CHECKING

from flomo_pipeline.chunk import ChunkBuildRunner, ChunkValidator
from tests.conftest import write_jsonl

if TYPE_CHECKING:
    from pathlib import Path


def _setup_chunk_monthly(tmp_path: Path) -> tuple[Path, Path]:
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    monthly_root.mkdir(parents=True, exist_ok=True)
    chunks_root.mkdir(parents=True, exist_ok=True)

    write_jsonl(
        monthly_root / "2025-12.enriched.jsonl",
        [
            {
                "memo_id": "memo-1",
                "created_at": "2025-12-01T09:00:00",
                "month": "2025-12",
                "memo_text": "short memo one",
                "source_relpath": "2025/flomo@Example-20251201/2512.html",
                "batch_label": "20251201",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            },
            {
                "memo_id": "memo-2",
                "created_at": "2025-12-01T10:00:00",
                "month": "2025-12",
                "memo_text": "short memo two",
                "source_relpath": "2025/flomo@Example-20251201/2512.html",
                "batch_label": "20251201",
                "ordinal": 2,
                "image_count_raw": 2,
                "images": [
                    {
                        "image_id": "image-2-1",
                        "memo_id": "memo-2",
                        "relative_path": "store/images/2025/2025-12/image-2-1.jpg",
                        "source_relpath": (
                            "2025/flomo@Example-20251201/file/2025-12-01/a/image-2-1.jpg"
                        ),
                        "media_type": "image/jpeg",
                        "ocr_text": "OCR text",
                        "visual_description": "visual description",
                        "model_name": "mock-vlm",
                        "prompt_version": "mock-v1",
                        "run_id": "run-1",
                        "status": "success",
                        "error_message": None,
                    },
                    {
                        "image_id": "image-2-2",
                        "memo_id": "memo-2",
                        "relative_path": "store/images/2025/2025-12/image-2-2.mov",
                        "source_relpath": (
                            "2025/flomo@Example-20251201/file/2025-12-01/a/image-2-2.mov"
                        ),
                        "media_type": "video/quicktime",
                        "ocr_text": "",
                        "visual_description": "",
                        "model_name": "mock-vlm",
                        "prompt_version": "mock-v1",
                        "run_id": "run-1",
                        "status": "skipped",
                        "error_message": None,
                    },
                ],
            },
            {
                "memo_id": "memo-3",
                "created_at": "2025-12-01T11:00:00",
                "month": "2025-12",
                "memo_text": " ".join(["large"] * 120),
                "source_relpath": "2025/flomo@Example-20251201/2512.html",
                "batch_label": "20251201",
                "ordinal": 3,
                "image_count_raw": 1,
                "images": [
                    {
                        "image_id": "image-3-1",
                        "memo_id": "memo-3",
                        "relative_path": "store/images/2025/2025-12/image-3-1.jpg",
                        "source_relpath": (
                            "2025/flomo@Example-20251201/file/2025-12-01/a/image-3-1.jpg"
                        ),
                        "media_type": "image/jpeg",
                        "ocr_text": "",
                        "visual_description": "",
                        "model_name": "mock-vlm",
                        "prompt_version": "mock-v1",
                        "run_id": "run-1",
                        "status": "failed",
                        "error_message": "missing",
                    },
                ],
            },
        ],
    )

    write_jsonl(
        monthly_root / "2026-01.enriched.jsonl",
        [
            {
                "memo_id": "memo-4",
                "created_at": "2026-01-05T12:00:00",
                "month": "2026-01",
                "memo_text": "january memo",
                "source_relpath": "2026/flomo@Example-20260105/2601.html",
                "batch_label": "20260105",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            }
        ],
    )
    return monthly_root, chunks_root


def test_chunk_builder_packs_multiple_memos_and_preserves_traceability(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)

    grouped_chunks, stats = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=120,
        hard_max_tokens=160,
        overwrite=True,
    ).run()

    assert stats.months_built == 2
    assert stats.chunk_count == 3
    december_chunks = grouped_chunks["2025-12"]
    assert [chunk.chunk_id for chunk in december_chunks] == ["2025-12-0001", "2025-12-0002"]
    assert december_chunks[0].source_memo_ids == ["memo-1", "memo-2"]
    assert december_chunks[1].source_memo_ids == ["memo-3"]
    assert december_chunks[0].text
    assert december_chunks[1].text
    assert "[IMAGE]" in december_chunks[0].text
    assert "image-2-2" not in december_chunks[0].text
    assert any(image.status == "skipped" for image in december_chunks[0].source_items[1].images)


def test_oversized_memo_becomes_single_chunk(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)

    grouped_chunks, _ = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=60,
        hard_max_tokens=80,
        overwrite=True,
    ).run()

    december_chunks = grouped_chunks["2025-12"]
    assert december_chunks[-1].source_memo_ids == ["memo-3"]
    assert december_chunks[-1].token_estimate > 0


def test_chunk_builder_skips_existing_month_without_overwrite(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)

    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=True,
    ).run()
    first_payload = json.loads(
        (chunks_root / "2025-12" / "2025-12-0001.json").read_text(encoding="utf-8")
    )

    _, stats = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=False,
    ).run()
    second_payload = json.loads(
        (chunks_root / "2025-12" / "2025-12-0001.json").read_text(encoding="utf-8")
    )

    assert stats.months_skipped == 2
    assert first_payload == second_payload


def test_chunk_builder_handles_empty_monthly_input(tmp_path: Path) -> None:
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    monthly_root.mkdir(parents=True, exist_ok=True)
    chunks_root.mkdir(parents=True, exist_ok=True)

    grouped_chunks, stats = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=True,
    ).run()

    assert grouped_chunks == {}
    assert stats.months_built == 0
    assert stats.chunk_count == 0
    assert list(chunks_root.rglob("*.json")) == []


def test_chunk_validator_passes_generated_output(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)

    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=120,
        overwrite=True,
    ).run()

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()
    assert report.ok, report.format_detail()


def test_chunk_validator_ignores_non_month_directories(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)
    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=120,
        overwrite=True,
    ).run()
    (chunks_root / ".opencode").mkdir()
    (chunks_root / "notes").mkdir()

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()

    assert report.ok, report.format_detail()


def test_chunk_validator_catches_duplicate_chunk_id_and_missing_memo(tmp_path: Path) -> None:
    monthly_root, chunks_root = _setup_chunk_monthly(tmp_path)

    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=120,
        overwrite=True,
    ).run()

    bad_chunk = json.loads(
        (chunks_root / "2026-01" / "2026-01-0001.json").read_text(encoding="utf-8")
    )
    bad_chunk["chunk_id"] = "2025-12-0001"
    bad_chunk["source_memo_ids"] = ["missing-memo"]
    bad_chunk["source_count"] = 1
    bad_chunk["source_items"][0]["memo_id"] = "missing-memo"
    (chunks_root / "2026-01" / "2026-01-0001.json").write_text(
        json.dumps(bad_chunk, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()
    assert not report.ok
    detail = report.format_detail()
    assert "Duplicate chunk_id" in detail
    assert "source_memo_id not found in monthly source" in detail


def test_chunk_validator_catches_invalid_monthly_input(tmp_path: Path) -> None:
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    monthly_root.mkdir(parents=True, exist_ok=True)
    chunks_root.mkdir(parents=True, exist_ok=True)

    (monthly_root / "2025-12.enriched.jsonl").write_text("{bad json}\n", encoding="utf-8")

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()
    assert not report.ok
    assert "JSON parse error" in report.format_detail()
