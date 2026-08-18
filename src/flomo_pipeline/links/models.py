from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

LINK_MAP_SCHEMA_VERSION = "link-map-v1"
LINK_MAP_FILENAME = "link_map.json"


@dataclasses.dataclass(frozen=True)
class NotionMemoRow:
    """One memo row parsed from a Notion flomo database export."""

    internal_id: str
    memo_url: str
    content: str
    created_at: str | None
    backlink_ids: list[str]
    ai_insight: str | None
    source: str


@dataclasses.dataclass(frozen=True)
class LinkMapEntry:
    """Resolution target for one flomo internal memo id."""

    internal_id: str
    memo_url: str
    content: str
    created_at: str | None
    pipeline_memo_id: str | None
    backlink_ids: list[str]

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LinkMapEntry:
        created_at = payload["created_at"]
        if created_at is not None and not isinstance(created_at, str):
            raise ValueError("created_at must be a string or null")
        pipeline_memo_id = payload["pipeline_memo_id"]
        if pipeline_memo_id is not None and not isinstance(pipeline_memo_id, str):
            raise ValueError("pipeline_memo_id must be a string or null")
        backlink_raw = payload["backlink_ids"]
        if not isinstance(backlink_raw, list):
            raise ValueError("backlink_ids must be an array")
        return cls(
            internal_id=str(payload["internal_id"]),
            memo_url=str(payload["memo_url"]),
            content=str(payload["content"]),
            created_at=created_at,
            pipeline_memo_id=pipeline_memo_id,
            backlink_ids=[str(item) for item in backlink_raw],
        )


@dataclasses.dataclass(frozen=True)
class LinkMap:
    """ID -> entry mapping built from the Notion export.

    ``entries`` is keyed by the decimal flomo internal memo id so that a link
    URL inside a memo body can be resolved by decoding its ``memo_id=`` param.
    """

    schema_version: str
    entries: dict[str, LinkMapEntry]

    def get(self, internal_id: str) -> LinkMapEntry | None:
        return self.entries.get(internal_id)

    def memo_id_to_internal(self) -> dict[str, str]:
        """Pipeline memo_id -> flomo internal id (only matched entries)."""
        return {
            entry.pipeline_memo_id: internal_id
            for internal_id, entry in self.entries.items()
            if entry.pipeline_memo_id is not None
        }

    def inbound_ids(self, internal_id: str) -> list[str]:
        """Internal ids of memos that link to ``internal_id``.

        The Notion 关联自 column of a memo already lists its inbound
        sources, so inbound edges are the row's own backlink ids.
        """
        entry = self.entries.get(internal_id)
        if entry is None:
            return []
        return list(entry.backlink_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": {
                internal_id: entry.to_dict() for internal_id, entry in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LinkMap:
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, dict):
            raise ValueError("link map payload missing 'entries' object")
        entries = {
            str(internal_id): LinkMapEntry.from_dict(entry)
            for internal_id, entry in raw_entries.items()
            if isinstance(entry, dict)
        }
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            entries=entries,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: Path) -> LinkMap:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclasses.dataclass(frozen=True)
class ResolvedLink:
    """One flomo internal link that was successfully resolved."""

    from_memo_id: str
    to_internal_id: str
    to_memo_id: str | None
    to_created_at: str | None
    to_snippet: str


@dataclasses.dataclass(frozen=True)
class TextResolution:
    """Result of resolving links inside one memo text."""

    text: str
    links: list[ResolvedLink]
    unresolved_urls: list[str]
