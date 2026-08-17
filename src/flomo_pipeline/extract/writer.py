from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

from flomo_pipeline.common.io import read_jsonl, write_jsonl

if TYPE_CHECKING:
    from pathlib import Path

    from flomo_pipeline.common.models import ImageRecord, MemoRecord, ParseResult


class StoreWriter:
    def __init__(self, store_root: Path) -> None:
        self.store_root = store_root
        self.memo_path = store_root / "memo.raw.jsonl"
        self.image_path = store_root / "image.raw.jsonl"
        self.missing_image_path = store_root / "missing_image.raw.jsonl"
        self.images_dir = store_root / "images"

    def write(self, result: ParseResult, raw_root: Path) -> None:
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        write_jsonl(self.memo_path, result.memos)
        write_jsonl(self.image_path, result.images)
        write_jsonl(self.missing_image_path, result.missing_images)
        self._copy_images(result.images, raw_root)
        self._migrate_enriched_images(result)

    def _copy_images(self, images: list[ImageRecord], raw_root: Path) -> None:
        for image in images:
            source = raw_root / image.source_relpath
            dest = self.store_root.parent / image.image_relpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copy2(source, dest)

    def _migrate_enriched_images(self, result: ParseResult) -> None:
        enriched_path = self.store_root / "image.enriched.jsonl"
        if not enriched_path.exists() or not result.image_id_aliases:
            return

        existing_records = read_jsonl(enriched_path)
        if not any(
            str(record.get("image_id", "")) in result.image_id_aliases
            for record in existing_records
        ):
            return

        images_by_id = {image.image_id: image for image in result.images}
        memos_by_id = {memo.memo_id: memo for memo in result.memos}
        migrated_by_id: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

        for record in existing_records:
            old_image_id = str(record.get("image_id", ""))
            canonical_image_id = result.image_id_aliases.get(old_image_id, old_image_id)
            image = images_by_id.get(canonical_image_id)
            if image is None:
                migrated = dict(record)
                output_image_id = old_image_id
            else:
                migrated = self._remap_enriched_record(
                    record=record,
                    image=image,
                    memo=memos_by_id.get(image.memo_id),
                )
                output_image_id = canonical_image_id

            score = (
                self._enrichment_status_rank(str(record.get("status", ""))),
                int(old_image_id == canonical_image_id),
            )
            current = migrated_by_id.get(output_image_id)
            if current is None or score > current[0]:
                migrated_by_id[output_image_id] = (score, migrated)

        backup_path = self._next_backup_path(enriched_path)
        shutil.copy2(enriched_path, backup_path)
        write_jsonl(
            enriched_path,
            (
                payload
                for _, payload in sorted(
                    migrated_by_id.values(),
                    key=lambda item: str(item[1].get("image_id", "")),
                )
            ),
            atomic=True,
        )

    @staticmethod
    def _remap_enriched_record(
        *,
        record: dict[str, Any],
        image: ImageRecord,
        memo: MemoRecord | None,
    ) -> dict[str, Any]:
        migrated = dict(record)
        migrated.update(
            {
                "image_id": image.image_id,
                "memo_id": image.memo_id,
                "relative_path": image.image_relpath,
                "source_relpath": image.source_relpath,
            }
        )
        if memo is not None:
            migrated["created_at"] = memo.created_at
            migrated["month"] = memo.created_at[:7]
        return migrated

    @staticmethod
    def _enrichment_status_rank(status: str) -> int:
        return {"failed": 0, "skipped": 1, "success": 2}.get(status, -1)

    @staticmethod
    def _next_backup_path(enriched_path: Path) -> Path:
        base = enriched_path.with_name(f"{enriched_path.name}.pre-dedup.bak")
        if not base.exists():
            return base
        index = 1
        while True:
            candidate = base.with_name(f"{base.name}.{index}")
            if not candidate.exists():
                return candidate
            index += 1
