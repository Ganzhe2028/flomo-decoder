from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ChunkCreatedAtRange:
    start: str
    end: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ChunkSourceImage:
    image_id: str
    status: str
    media_type: str
    relative_path: str
    source_relpath: str
    ocr_text: str
    visual_description: str
    error_message: str | None

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ChunkSourceItem:
    memo_id: str
    created_at: str
    memo_text: str
    source_relpath: str
    image_count_raw: int
    images: list[ChunkSourceImage]

    def to_dict(self) -> dict[str, object]:
        return {
            "memo_id": self.memo_id,
            "created_at": self.created_at,
            "memo_text": self.memo_text,
            "source_relpath": self.source_relpath,
            "image_count_raw": self.image_count_raw,
            "images": [image.to_dict() for image in self.images],
        }


@dataclasses.dataclass(frozen=True)
class ChunkResolvedLink:
    """One flomo internal link inside a chunk source memo, resolved via link map."""

    from_memo_id: str
    to_internal_id: str
    to_memo_id: str | None
    to_created_at: str | None
    to_snippet: str

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    month: str
    chunk_index: int
    source_memo_ids: list[str]
    source_count: int
    created_at_range: ChunkCreatedAtRange
    token_estimate: int
    text: str
    source_items: list[ChunkSourceItem]
    resolved_links: list[ChunkResolvedLink]
    build_version: str
    strategy: str
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "month": self.month,
            "chunk_index": self.chunk_index,
            "source_memo_ids": self.source_memo_ids,
            "source_count": self.source_count,
            "created_at_range": self.created_at_range.to_dict(),
            "token_estimate": self.token_estimate,
            "text": self.text,
            "source_items": [item.to_dict() for item in self.source_items],
            "resolved_links": [link.to_dict() for link in self.resolved_links],
            "build_version": self.build_version,
            "strategy": self.strategy,
            "status": self.status,
        }


@dataclasses.dataclass
class ChunkBuildStats:
    months_built: int = 0
    months_skipped: int = 0
    chunk_count: int = 0
    memo_count: int = 0
    resolved_links: int = 0
    unresolved_links: int = 0

    def format_summary(self) -> str:
        return (
            f"Months built: {self.months_built}\n"
            f"Months skipped: {self.months_skipped}\n"
            f"Chunks written: {self.chunk_count}\n"
            f"Memos packed: {self.memo_count}\n"
            f"Links resolved: {self.resolved_links}\n"
            f"Links unresolved: {self.unresolved_links}"
        )
