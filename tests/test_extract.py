from __future__ import annotations

import json
from typing import TYPE_CHECKING

from conftest import SAMPLE_HTML

from flomo_pipeline.extract import FlomoParser, StoreWriter

if TYPE_CHECKING:
    from pathlib import Path


def _write_export(
    raw_root: Path,
    *,
    batch_label: str,
    memos: list[tuple[str, str, str | None]],
    existing_images: set[str] | None = None,
) -> None:
    batch_dir = raw_root / "2026" / f"flomo@ExampleUser-{batch_label}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    memo_html: list[str] = []
    for created_at, body, image_src in memos:
        image_html = f'<div class="files"><img src="{image_src}"></div>' if image_src else ""
        memo_html.append(
            '<div class="memo">'
            f'<div class="time">{created_at}</div>'
            f'<div class="content"><p>{body}</p></div>'
            f"{image_html}</div>"
        )
    html = (
        '<html><body><div class="name">@ExampleUser</div>'
        + "".join(memo_html)
        + "</body></html>"
    )
    (batch_dir / "ExampleUser的笔记.html").write_text(html, encoding="utf-8")
    for image_src in existing_images or set():
        image_path = batch_dir / image_src
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n")


def test_parse_all_returns_stage1_records(sample_raw_root: Path, tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()

    assert len(result.memos) == 3
    assert len(result.images) == 2
    assert len(result.missing_images) == 1

    first_memo = result.memos[0]
    assert first_memo.memo_id == "flomo-exampleuser-20260304--0001"
    assert first_memo.source_relpath == "2026/flomo@ExampleUser-20260304/ExampleUser的笔记.html"
    assert first_memo.batch_label == "20260304"
    assert first_memo.ordinal == 1

    second_image = result.images[1]
    assert second_image.memo_id == "flomo-exampleuser-20260304--0003"
    assert second_image.ordinal == 2
    assert second_image.image_relpath.startswith("store/images/2026/2026-03/")

    missing_image = result.missing_images[0]
    assert missing_image.image_id == "flomo-exampleuser-20260304--0003--01"
    assert missing_image.reason == "source_file_missing"


def test_parse_all_accepts_nested_flomo_export_wrapper(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    batch_dir = (
        raw_root
        / "2026"
        / "flomo@ExampleUser-20260304"
        / "flomo@ExampleUser-20260304"
    )
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "ExampleUser的笔记.html").write_text(SAMPLE_HTML, encoding="utf-8")

    image_dir = batch_dir / "file" / "2026-03-02" / "abc123"
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    image_dir_2 = batch_dir / "file" / "2026-03-03" / "ghi789"
    image_dir_2.mkdir(parents=True, exist_ok=True)
    (image_dir_2 / "audio_cover.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=raw_root, store_root=store_root).parse_all()

    assert len(result.memos) == 3
    assert len(result.images) == 2
    assert len(result.missing_images) == 1
    assert (
        result.memos[0].source_relpath
        == "2026/flomo@ExampleUser-20260304/flomo@ExampleUser-20260304/ExampleUser的笔记.html"
    )


def test_writer_writes_stage1_filenames_and_copies_images(
    sample_raw_root: Path,
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "store"
    result = FlomoParser(raw_root=sample_raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(result, raw_root=sample_raw_root)

    assert (store_root / "memo.raw.jsonl").exists()
    assert (store_root / "image.raw.jsonl").exists()
    assert (store_root / "missing_image.raw.jsonl").exists()

    memo_lines = (store_root / "memo.raw.jsonl").read_text(encoding="utf-8").strip().splitlines()
    image_lines = (store_root / "image.raw.jsonl").read_text(encoding="utf-8").strip().splitlines()
    missing_lines = (
        store_root / "missing_image.raw.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()

    assert len(memo_lines) == 3
    assert len(image_lines) == 2
    assert len(missing_lines) == 1

    image_record = json.loads(image_lines[0])
    copied_image_path = tmp_path / image_record["image_relpath"]
    assert copied_image_path.exists()


def test_parse_all_deduplicates_overlapping_exports_without_losing_same_day_memos(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    image_src = "file/2026-08-17/image/photo.png"
    first_export = [
        ("2026-08-17 10:00:00", "same text", None),
        ("2026-08-17 10:00:00", "same text", None),
        ("2026-08-17 18:51:37", "", image_src),
    ]
    _write_export(raw_root, batch_label="20260817", memos=first_export)
    _write_export(
        raw_root,
        batch_label="20260817__a1b2c3d4",
        memos=[
            *first_export,
            ("2026-08-17 20:05:00", "written after the first export", None),
            ("2026-08-17 10:00:00", "edited text", None),
        ],
        existing_images={image_src},
    )

    result = FlomoParser(raw_root=raw_root, store_root=tmp_path / "store").parse_all()

    assert len(result.memos) == 5
    assert result.deduplicated_count == 3
    assert result.possible_revision_count == 1
    assert sum(memo.body_md == "same text" for memo in result.memos) == 2
    assert any(memo.body_md == "written after the first export" for memo in result.memos)
    assert any(memo.body_md == "edited text" for memo in result.memos)

    canonical_image_id = "flomo-exampleuser-20260817--0003--01"
    duplicate_image_id = "flomo-exampleuser-20260817__a1b2c3d4--0003--01"
    assert result.image_id_aliases[duplicate_image_id] == canonical_image_id
    assert [image.image_id for image in result.images] == [canonical_image_id]
    assert result.images[0].memo_id == "flomo-exampleuser-20260817--0003"
    assert result.images[0].source_relpath.startswith(
        "2026/flomo@ExampleUser-20260817__a1b2c3d4/"
    )
    assert result.missing_images == []
    new_memo = next(
        memo for memo in result.memos if memo.body_md == "written after the first export"
    )
    assert new_memo.memo_id == "flomo-exampleuser-20260817__a1b2c3d4--0004"
    assert new_memo.batch_label == "20260817__a1b2c3d4"


def test_writer_migrates_successful_enrichment_to_canonical_image_id(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    store_root = tmp_path / "store"
    image_src = "file/2026-08-17/image/photo.png"
    memo = [("2026-08-17 18:51:37", "image memo", image_src)]
    _write_export(raw_root, batch_label="20260817", memos=memo, existing_images={image_src})
    _write_export(
        raw_root,
        batch_label="20260817__duplicate",
        memos=memo,
        existing_images={image_src},
    )
    result = FlomoParser(raw_root=raw_root, store_root=store_root).parse_all()
    canonical_id = "flomo-exampleuser-20260817--0001--01"
    duplicate_id = "flomo-exampleuser-20260817__duplicate--0001--01"

    store_root.mkdir(parents=True, exist_ok=True)
    enriched_records = [
        {
            "image_id": canonical_id,
            "memo_id": "flomo-exampleuser-20260817--0001",
            "created_at": "2026-08-17T18:51:37",
            "month": "2026-08",
            "relative_path": f"store/images/2026/2026-08/{canonical_id}.png",
            "source_relpath": image_src,
            "media_type": "image/png",
            "ocr_text": "",
            "visual_description": "",
            "model_name": "model",
            "prompt_version": "v1",
            "run_id": "old",
            "status": "failed",
            "error_message": "old failure",
        },
        {
            "image_id": duplicate_id,
            "memo_id": "flomo-exampleuser-20260817__duplicate--0001",
            "created_at": "2026-08-17T18:51:37",
            "month": "2026-08",
            "relative_path": f"store/images/2026/2026-08/{duplicate_id}.png",
            "source_relpath": image_src,
            "media_type": "image/png",
            "ocr_text": "recognized text",
            "visual_description": "recognized image",
            "model_name": "model",
            "prompt_version": "v1",
            "run_id": "new",
            "status": "success",
            "error_message": None,
        },
    ]
    (store_root / "image.enriched.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in enriched_records),
        encoding="utf-8",
    )

    StoreWriter(store_root=store_root).write(result, raw_root=raw_root)

    migrated = [
        json.loads(line)
        for line in (store_root / "image.enriched.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(migrated) == 1
    assert migrated[0]["image_id"] == canonical_id
    assert migrated[0]["memo_id"] == "flomo-exampleuser-20260817--0001"
    assert migrated[0]["status"] == "success"
    assert migrated[0]["ocr_text"] == "recognized text"
    assert (store_root / "image.enriched.jsonl.pre-dedup.bak").exists()
