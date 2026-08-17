from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class MemoRecord:
    memo_id: str
    created_at: str
    body_md: str
    image_count: int
    source_relpath: str
    batch_label: str
    ordinal: int

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ImageRecord:
    image_id: str
    memo_id: str
    image_relpath: str
    source_relpath: str
    ordinal: int

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class MissingImageRecord:
    image_id: str
    memo_id: str
    source_relpath: str
    ordinal: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ParseResult:
    memos: list[MemoRecord]
    images: list[ImageRecord]
    missing_images: list[MissingImageRecord]
    deduplicated_count: int = 0
    possible_revision_count: int = 0
    image_id_aliases: dict[str, str] = dataclasses.field(default_factory=dict)
