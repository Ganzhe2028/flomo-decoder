from __future__ import annotations

import base64
import binascii
import re
from typing import TYPE_CHECKING

from flomo_pipeline.links.models import (
    LINK_MAP_SCHEMA_VERSION,
    LinkMap,
    LinkMapEntry,
    ResolvedLink,
    TextResolution,
)

if TYPE_CHECKING:
    from flomo_pipeline.links.models import NotionMemoRow

# URL as pasted into memo bodies. Trailing CJK/ASCII punctuation is trimmed
# because flomo appends link URLs directly to prose.
_LINK_URL_RE = re.compile(r"https?://v\.flomoapp\.com/[^\s]*?memo_id=[A-Za-z0-9+/=]+")
_TRAILING_PUNCT = ".,;:!?)]}」』）】〕》〉、。，；：！？\"'"
_MEMO_ID_RE = re.compile(r"memo_id=([A-Za-z0-9+/=]+)")
_DIGITS_RE = re.compile(r"^\d+$")

SNIPPET_LIMIT = 40


def decode_internal_id(encoded: str) -> str | None:
    """Decode the base64 ``memo_id=`` param into the decimal flomo id."""
    padding = "=" * (-len(encoded) % 4)
    try:
        raw = base64.b64decode(encoded + padding, validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return text if _DIGITS_RE.match(text) else None


def internal_id_from_url(url: str) -> str | None:
    match = _MEMO_ID_RE.search(url)
    if match is None:
        return None
    return decode_internal_id(match.group(1))


def find_link_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _LINK_URL_RE.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCT)
        if url and internal_id_from_url(url) is not None:
            urls.append(url)
    return urls


def make_snippet(content: str, limit: int = SNIPPET_LIMIT) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def render_reference(entry: LinkMapEntry) -> str:
    head_parts = ["关联 MEMO"]
    if entry.created_at is not None:
        head_parts.append(entry.created_at[:10])
    snippet = make_snippet(entry.content)
    if snippet:
        return "〔" + " ".join(head_parts) + f"「{snippet}」〕"
    return "〔" + " ".join(head_parts) + "〕"


def resolve_text(text: str, link_map: LinkMap, *, from_memo_id: str) -> TextResolution:
    resolved_text = text
    links: list[ResolvedLink] = []
    unresolved: list[str] = []
    for url in find_link_urls(text):
        internal_id = internal_id_from_url(url)
        entry = link_map.get(internal_id) if internal_id is not None else None
        if entry is None:
            unresolved.append(url)
            continue
        resolved_text = resolved_text.replace(url, render_reference(entry))
        links.append(
            ResolvedLink(
                from_memo_id=from_memo_id,
                to_internal_id=entry.internal_id,
                to_memo_id=entry.pipeline_memo_id,
                to_created_at=entry.created_at,
                to_snippet=make_snippet(entry.content),
            )
        )
    return TextResolution(text=resolved_text, links=links, unresolved_urls=unresolved)


def render_related_block(entry: LinkMapEntry, link_map: LinkMap) -> str | None:
    """Render the inbound (关联自) backlinks of ``entry`` for the chunk text."""
    sources: list[LinkMapEntry | str] = []
    for source_id in link_map.inbound_ids(entry.internal_id):
        source_entry = link_map.get(source_id)
        if source_entry is not None:
            sources.append(source_entry)
        else:
            sources.append(source_id)
    if not sources:
        return None

    def _sort_key(item: LinkMapEntry | str) -> tuple[str, str, str]:
        if isinstance(item, str):
            return ("", "", item)
        return (
            item.created_at or "",
            make_snippet(item.content),
            item.internal_id,
        )

    sources.sort(key=_sort_key)
    lines = ["[RELATED]"]
    for source_item in sources:
        if isinstance(source_item, str):
            lines.append(f"linked_from: (未收录 memo {source_item})")
            continue
        parts: list[str] = []
        if source_item.pipeline_memo_id is not None:
            parts.append(source_item.pipeline_memo_id)
        if source_item.created_at is not None:
            parts.append(source_item.created_at[:10])
        snippet = make_snippet(source_item.content)
        line = "linked_from: " + " ".join(parts)
        if snippet:
            line += f"「{snippet}」"
        lines.append(line)
    return "\n".join(lines)


def normalize_for_match(text: str) -> str:
    """Loose content normalization to pair Notion rows with pipeline memos.

    Removes flomo hashtags (``#tag``), URLs, and markdown punctuation before
    collapsing whitespace, so that the Notion content column (which may not
    carry tags) can match the exported memo body.
    """
    no_urls = re.sub(r"https?://\S+", " ", text)
    no_tags = re.sub(r"#\S+", " ", no_urls)
    no_markdown = re.sub(r"[*_`>~|\-]", " ", no_tags)
    return " ".join(no_markdown.lower().split())


MIN_PREFIX_MATCH_LENGTH = 4


def build_link_map(
    rows: list[NotionMemoRow],
    pipeline_memos: list[dict[str, object]],
    *,
    schema_version: str = LINK_MAP_SCHEMA_VERSION,
) -> LinkMap:
    """Build the link map and pair Notion rows with pipeline memos.

    flomo's Notion sync stores the memo text as the page title truncated to
    50 chars, so matching is exact-normalized first and falls back to a
    unique-prefix match (optionally disambiguated by creation date).
    """
    normalized_index: dict[str, set[str]] = {}
    norm_memos: list[tuple[str, str, str]] = []
    for memo in pipeline_memos:
        norm = normalize_for_match(str(memo.get("body_md", "")))
        if not norm:
            continue
        memo_id = str(memo["memo_id"])
        normalized_index.setdefault(norm, set()).add(memo_id)
        norm_memos.append((norm, memo_id, str(memo.get("created_at", ""))[:10]))

    entries: dict[str, LinkMapEntry] = {}
    claimed_memo_ids: set[str] = set()
    for row in sorted(rows, key=lambda item: item.internal_id):
        matched_memo_id: str | None = None
        norm = normalize_for_match(row.content)
        if norm:
            matched_memo_id = _match_pipeline_memo(
                norm=norm,
                normalized_index=normalized_index,
                norm_memos=norm_memos,
                created_date=(row.created_at or "")[:10],
            )
        if matched_memo_id is not None and matched_memo_id in claimed_memo_ids:
            # Duplicate sync rows (flomo conflict copies) may carry different
            # internal ids for the same memo; only the first row claims it.
            matched_memo_id = None
        if matched_memo_id is not None:
            claimed_memo_ids.add(matched_memo_id)
        entries[row.internal_id] = LinkMapEntry(
            internal_id=row.internal_id,
            memo_url=row.memo_url,
            content=row.content,
            created_at=row.created_at,
            pipeline_memo_id=matched_memo_id,
            backlink_ids=sorted(set(row.backlink_ids)),
        )
    return LinkMap(schema_version=schema_version, entries=entries)


def _match_pipeline_memo(
    *,
    norm: str,
    normalized_index: dict[str, set[str]],
    norm_memos: list[tuple[str, str, str]],
    created_date: str,
) -> str | None:
    exact = normalized_index.get(norm, set())
    if len(exact) == 1:
        return next(iter(exact))
    if len(exact) > 1 and created_date:
        same_date = {
            memo_id for n, memo_id, date in norm_memos if n == norm and date == created_date
        }
        if len(same_date) == 1:
            return next(iter(same_date))
        return None

    if len(norm) < MIN_PREFIX_MATCH_LENGTH:
        return None
    prefix_candidates = {
        memo_id for n, memo_id, _ in norm_memos if n.startswith(norm)
    }
    if len(prefix_candidates) == 1:
        return next(iter(prefix_candidates))
    if len(prefix_candidates) > 1 and created_date:
        same_date = {
            memo_id
            for n, memo_id, date in norm_memos
            if n.startswith(norm) and date == created_date
        }
        if len(same_date) == 1:
            return next(iter(same_date))
    return None
