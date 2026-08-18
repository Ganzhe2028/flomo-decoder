from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from flomo_pipeline.links.models import NotionMemoRow
from flomo_pipeline.links.resolver import internal_id_from_url

_HEX_ID_RE = re.compile(r"[0-9a-f]{32}", re.IGNORECASE)
_MEMO_ID_IN_URL_RE = re.compile(r"memo_id=([A-Za-z0-9+/=]+)")
_BACKLINK_MARKERS = ("关联自：", "关联自:", "关联自")

# The flomo Notion sync puts the memo's own link in a url property and the
# content in the title. These column ids are fixed by flomo's sync schema.
_LINK_PROPERTY_ID = "nc@X"
_TITLE_PROPERTY_ID = "title"
_CREATED_AT_PROPERTY_ID = ";RVb"


def notion_db_path_candidates() -> list[Path]:
    """Default locations of the Notion desktop app's offline mirror."""
    candidates: list[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Notion" / "notion.db")
    else:
        candidates.append(Path.home() / ".config" / "Notion" / "notion.db")
        candidates.append(
            Path.home() / "Library" / "Application Support" / "Notion" / "notion.db"
        )
    return candidates


def find_notion_db() -> Path | None:
    for candidate in notion_db_path_candidates():
        if candidate.is_file():
            return candidate
    return None


def open_notion_db(db_path: Path) -> sqlite3.Connection:
    """Open the Notion mirror as an in-memory snapshot.

    Uses SQLite's online backup so a running Notion desktop app (which may be
    writing to the file) does not corrupt the read. Falls back to a plain
    file copy if the live file cannot be opened read-only.
    """
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        live = sqlite3.connect(uri, uri=True)
        try:
            snapshot = sqlite3.connect(":memory:")
            live.backup(snapshot)
            return snapshot
        finally:
            live.close()
    except sqlite3.Error:
        snapshot_dir = Path(tempfile.mkdtemp(prefix="notion-db-"))
        snapshot_path = snapshot_dir / "notion.db"
        shutil.copyfile(db_path, snapshot_path)
        copied = sqlite3.connect(f"file:{snapshot_path.as_posix()}?mode=ro", uri=True)
        snapshot = sqlite3.connect(":memory:")
        copied.backup(snapshot)
        copied.close()
        return snapshot


def _normalized_id(uid: str) -> str:
    return uid.replace("-", "").lower()


def resolve_collection_ids(conn: sqlite3.Connection, page_id: str | None) -> list[str]:
    """Resolve the flomo collection id from a Notion URL id (or find all
    collections named like flomo when no id is given)."""
    if page_id is not None:
        normalized = _normalized_id(page_id)
        row = conn.execute(
            "select parent_id, parent_table from block where replace(id, '-', '') = ?",
            (normalized,),
        ).fetchone()
        if row is not None and row[1] == "collection":
            return [str(row[0])]
        collection = conn.execute(
            "select id from collection where replace(id, '-', '') = ?",
            (normalized,),
        ).fetchone()
        if collection is not None:
            return [str(collection[0])]
        view = conn.execute(
            "select parent_id from collection_view where replace(id, '-', '') = ?",
            (normalized,),
        ).fetchone()
        if view is not None:
            parent = str(view[0])
            collection = conn.execute(
                "select id from collection where replace(id, '-', '') = ?",
                (_normalized_id(parent),),
            ).fetchone()
            if collection is not None:
                return [str(collection[0])]
            row = conn.execute(
                "select parent_id, parent_table from block where replace(id, '-', '') = ?",
                (_normalized_id(parent),),
            ).fetchone()
            if row is not None and row[1] == "collection":
                return [str(row[0])]
        return []

    collection_ids: list[str] = []
    for collection_id, name in conn.execute("select id, name from collection"):
        if not _collection_named_flomo(name):
            continue
        if collection_id not in collection_ids:
            collection_ids.append(str(collection_id))
    return collection_ids


def _collection_named_flomo(name: str | None) -> bool:
    if not name:
        return False
    try:
        groups = json.loads(name)
    except (json.JSONDecodeError, TypeError):
        return "flomo" in str(name).lower()
    flat = " ".join(
        str(part) for group in groups if isinstance(group, list) for part in group
    )
    return "flomo" in flat.lower()


def _collect_known_ids(conn: sqlite3.Connection, collection_id: str) -> set[str]:
    known: set[str] = set()
    for (properties,) in conn.execute(
        "select properties from block where parent_id = ? and alive = 1",
        (collection_id,),
    ):
        if not properties:
            continue
        internal_id = _own_internal_id(properties)
        if internal_id is not None:
            known.add(internal_id)
    return known


def _own_internal_id(properties: str) -> str | None:
    try:
        payload = json.loads(properties)
    except (json.JSONDecodeError, TypeError):
        return None
    link_parts = payload.get(_LINK_PROPERTY_ID) or []
    for part in link_parts:
        if not isinstance(part, list) or not part:
            continue
        text = part[0]
        if isinstance(text, str) and "v.flomoapp.com" in text:
            return internal_id_from_url(text)
    return None


def _title_text(properties: str) -> str:
    try:
        payload = json.loads(properties)
    except (json.JSONDecodeError, TypeError):
        return ""
    parts: list[str] = []
    for part in payload.get(_TITLE_PROPERTY_ID) or []:
        if isinstance(part, list) and part and isinstance(part[0], str):
            parts.append(part[0])
    return "".join(parts)


def _created_at(properties: str) -> str | None:
    try:
        payload = json.loads(properties)
    except (json.JSONDecodeError, TypeError):
        return None
    date_parts = payload.get(_CREATED_AT_PROPERTY_ID) or []
    try:
        return str(date_parts[0][1][0][1]["start_date"])
    except (IndexError, KeyError, TypeError):
        return None


def _split_backlinks(title: str, known_ids: set[str]) -> tuple[str, list[str]]:
    """Split memo content from trailing 关联自 sections.

    flomo's Notion sync appends ``关联自：<url>`` notes to the memo text (or
    the memo is only that note). URLs inside the note are inbound links;
    their base64 ids are sometimes truncated, in which case a unique prefix
    match against the known internal ids recovers the full id.
    """
    marker_positions = [
        position
        for marker in _BACKLINK_MARKERS
        for position in _find_all(title, marker)
    ]
    if not marker_positions:
        return title.strip(), []
    content = title[: min(marker_positions)].strip()
    backlink_ids: list[str] = []
    for match in _MEMO_ID_IN_URL_RE.finditer(title):
        if content and match.start() < min(marker_positions):
            continue
        encoded = match.group(1)
        internal_id = _decode_encoded_id(encoded)
        if internal_id not in known_ids:
            internal_id = _recover_truncated_id(encoded, known_ids)
        if internal_id is not None and internal_id not in backlink_ids:
            backlink_ids.append(internal_id)
    return content, backlink_ids


def _find_all(text: str, needle: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index == -1:
            return positions
        positions.append(index)
        start = index + 1


def _decode_encoded_id(encoded: str) -> str | None:
    padding = "=" * (-len(encoded) % 4)
    try:
        raw = base64.b64decode(encoded + padding, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return text if text.isdigit() else None


def _recover_truncated_id(encoded: str, known_ids: set[str]) -> str | None:
    """Resolve a possibly truncated base64 memo id.

    Tries exact decoding first, then prefix matching from longest to
    shortest prefix. A truncated encoding sometimes decodes cleanly into a
    shorter digit string (leftover bits happen to be zero); treating that
    string as a prefix against the known ids recovers the full id as long
    as exactly one known id starts with it. A cleanly decoded id with no
    prefix match is returned unchanged: it is a complete id of a memo
    outside this database.
    """
    exact = _decode_encoded_id(encoded)
    if exact is not None and exact in known_ids:
        return exact

    candidates: list[str] = []
    if exact is not None:
        candidates.append(exact)
    drop = len(encoded) % 4
    clean = encoded[:-drop] if drop else encoded
    if clean and clean != encoded:
        try:
            raw = base64.b64decode(clean, validate=False)
        except binascii.Error:
            raw = b""
        prefix = "".join(
            char for char in raw.decode("ascii", errors="ignore") if char.isdigit()
        )
        if prefix and prefix not in candidates:
            candidates.append(prefix)

    for candidate in candidates:
        matches = [known for known in known_ids if known.startswith(candidate)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return exact


def parse_notion_db(
    db_path: Path, *, page_id: str | None = None
) -> tuple[list[NotionMemoRow], list[str]]:
    """Read flomo memo rows from the Notion desktop offline mirror."""
    conn = open_notion_db(db_path)
    try:
        collection_ids = resolve_collection_ids(conn, page_id)
        if not collection_ids:
            hint = (
                "the page id does not resolve to a flomo database in this mirror"
                if page_id is not None
                else "no collection named like flomo was found"
            )
            return [], [f"notion.db: {hint}"]
        warnings: list[str] = []
        merged: dict[str, NotionMemoRow] = {}
        for collection_id in collection_ids:
            known_ids = _collect_known_ids(conn, collection_id)
            for block_id, properties in conn.execute(
                "select id, properties from block where parent_id = ? and alive = 1",
                (collection_id,),
            ):
                if not properties:
                    continue
                internal_id = _own_internal_id(properties)
                if internal_id is None:
                    warnings.append(
                        f"notion.db: row {block_id[:8]} has no resolvable flomo link, skipped"
                    )
                    continue
                title = _title_text(properties)
                content, backlink_ids = _split_backlinks(title, known_ids)
                created_at = _created_at(properties)
                row = NotionMemoRow(
                    internal_id=internal_id,
                    memo_url=(
                        "https://v.flomoapp.com/mine/?memo_id="
                        + _encode_internal_id(internal_id)
                    ),
                    content=content,
                    created_at=created_at,
                    backlink_ids=backlink_ids,
                    ai_insight=None,
                    source=f"notion.db:{block_id[:8]}",
                )
                existing = merged.get(internal_id)
                if existing is None:
                    merged[internal_id] = row
                    continue
                # Duplicate syncs of the same memo: keep the richest content,
                # union the backlinks.
                merged[internal_id] = NotionMemoRow(
                    internal_id=internal_id,
                    memo_url=existing.memo_url,
                    content=existing.content if existing.content else row.content,
                    created_at=existing.created_at or row.created_at,
                    backlink_ids=sorted(set(existing.backlink_ids) | set(row.backlink_ids)),
                    ai_insight=None,
                    source=f"{existing.source}, {row.source}",
                )
        rows = sorted(merged.values(), key=lambda row: row.internal_id)
        if page_id is not None:
            warnings.append(
                f"notion.db: read {len(rows)} memo rows from {len(collection_ids)} collection(s)"
            )
        return rows, warnings
    finally:
        conn.close()


def _encode_internal_id(internal_id: str) -> str:
    return base64.b64encode(internal_id.encode("ascii")).decode("ascii").rstrip("=")
