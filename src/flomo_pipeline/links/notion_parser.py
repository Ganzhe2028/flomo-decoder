from __future__ import annotations

import csv
import re
import tempfile
from pathlib import Path

from flomo_pipeline.common.archive import safe_extract_zip
from flomo_pipeline.links.models import NotionMemoRow
from flomo_pipeline.links.resolver import find_link_urls, internal_id_from_url

_CONTENT_COLUMN_HINTS = ("内容", "正文", "笔记", "content", "memo")
_TIME_COLUMN_HINTS = ("创建时间", "时间", "日期", "created", "date")
_BACKLINK_COLUMN_HINTS = ("关联", "相关", "related", "backlink", "被链接")
_AI_COLUMN_HINTS = ("洞察", "insight", "ai")
_URL_COLUMN_HINTS = ("链接", "link", "url", "source")

_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?")


def _normalize_timestamp(value: str) -> str | None:
    match = _TIMESTAMP_RE.match(value.strip())
    if match is None:
        return None
    date, time_part = match.groups()
    if time_part is None:
        return f"{date}T00:00:00"
    if len(time_part) == 5:
        time_part += ":00"
    return f"{date}T{time_part}"


def parse_notion_input(input_path: Path) -> tuple[list[NotionMemoRow], list[str]]:
    """Parse a Notion flomo database export.

    Accepts a .csv file, a .md file, a directory containing them, or a .zip
    archive (the standard Notion "导出" package). Returns parsed rows plus
    non-fatal warnings.
    """
    if input_path.is_dir():
        return _parse_directory(input_path)
    suffix = input_path.suffix.lower()
    if suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="notion-links-") as tmp_dir:
            safe_extract_zip(input_path, Path(tmp_dir))
            return _parse_directory(Path(tmp_dir))
    if suffix == ".csv":
        return _parse_csv(input_path)
    if suffix in (".md", ".markdown"):
        return _parse_markdown_files([input_path])
    raise ValueError(
        f"Unsupported Notion input: {input_path} (expected .csv, .md, directory, or .zip)"
    )


def _parse_directory(directory: Path) -> tuple[list[NotionMemoRow], list[str]]:
    warnings: list[str] = []
    csv_rows: list[NotionMemoRow] = []
    md_rows: list[NotionMemoRow] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            rows, row_warnings = _parse_csv(path)
            csv_rows.extend(rows)
            warnings.extend(row_warnings)
        elif suffix in (".md", ".markdown"):
            rows, row_warnings = _parse_markdown_files([path])
            md_rows.extend(rows)
            warnings.extend(row_warnings)
    return _merge_rows(csv_rows, md_rows), warnings


def _merge_rows(
    csv_rows: list[NotionMemoRow], md_rows: list[NotionMemoRow]
) -> list[NotionMemoRow]:
    """Merge CSV table rows with per-page Markdown files by internal id.

    CSV wins for content/created_at (the table is the authoritative memo
    content); Markdown wins for the AI insight and contributes extra
    backlink ids parsed from the page body.
    """
    by_id: dict[str, NotionMemoRow] = {}
    for row in csv_rows:
        by_id[row.internal_id] = row
    for row in md_rows:
        existing = by_id.get(row.internal_id)
        if existing is None:
            by_id[row.internal_id] = row
            continue
        by_id[row.internal_id] = NotionMemoRow(
            internal_id=existing.internal_id,
            memo_url=existing.memo_url,
            content=existing.content or row.content,
            created_at=existing.created_at or row.created_at,
            backlink_ids=sorted(set(existing.backlink_ids) | set(row.backlink_ids)),
            ai_insight=row.ai_insight or existing.ai_insight,
            source=f"{existing.source}, {row.source}",
        )
    return sorted(by_id.values(), key=lambda row: row.internal_id)


def _sniff_own_link_column(
    fieldnames: list[str], rows: list[dict[str, str]]
) -> str | None:
    """Pick the column holding each row's own flomo memo link.

    Scores columns by URL coverage plus a name-hint bonus so that content
    columns (which may also embed flomo links inside prose) never win over
    an explicitly named link column.
    """
    scored: list[tuple[str, float, int]] = []
    for name in fieldnames:
        cells = [str(row.get(name) or "") for row in rows]
        url_cells = [
            cell
            for cell in cells
            if "v.flomoapp.com" in cell and "memo_id=" in cell
        ]
        fraction = len(url_cells) / len(cells) if cells else 0.0
        name_bonus = 2.0 if any(hint in name.lower() for hint in _URL_COLUMN_HINTS) else 0.0
        scored.append((name, fraction + name_bonus, len(url_cells)))
    if not scored:
        return None
    best_name, _, best_count = max(scored, key=lambda item: (item[1], item[2]))
    return best_name if best_count > 0 else None


def _sniff_csv_columns(
    fieldnames: list[str], rows: list[dict[str, str]]
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Detect own-link / content / time / backlink / ai-insight columns."""
    own_link_col = _sniff_own_link_column(fieldnames, rows)

    def _hint(name: str, hints: tuple[str, ...]) -> bool:
        lowered = name.lower()
        return any(hint in lowered for hint in hints)

    time_col = next(
        (name for name in fieldnames if name != own_link_col and _hint(name, _TIME_COLUMN_HINTS)),
        None,
    )
    backlink_col = next(
        (
            name
            for name in fieldnames
            if name != own_link_col and name != time_col and _hint(name, _BACKLINK_COLUMN_HINTS)
        ),
        None,
    )
    ai_col = next(
        (
            name
            for name in fieldnames
            if name != own_link_col and name != time_col and _hint(name, _AI_COLUMN_HINTS)
        ),
        None,
    )

    content_col = next(
        (
            name
            for name in fieldnames
            if name
            not in (own_link_col, time_col, backlink_col, ai_col)
            and _hint(name, _CONTENT_COLUMN_HINTS)
        ),
        None,
    )
    if content_col is None:
        fallback_columns = [
            name
            for name in fieldnames
            if name not in (own_link_col, time_col, backlink_col, ai_col)
        ]
        if fallback_columns:
            content_col = max(
                fallback_columns,
                key=lambda name: sum(len(str(row.get(name) or "")) for row in rows),
            )
    return own_link_col, content_col, time_col, backlink_col, ai_col


def _parse_csv(path: Path) -> tuple[list[NotionMemoRow], list[str]]:
    warnings: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [str(name) for name in (reader.fieldnames or [])]
        rows = [{key: (value or "") for key, value in row.items()} for row in reader]

    own_link_col, content_col, time_col, backlink_col, ai_col = _sniff_csv_columns(
        fieldnames, rows
    )
    if own_link_col is None:
        return [], [f"{path.name}: no column containing flomo memo links was found"]

    parsed: list[NotionMemoRow] = []
    skipped = 0
    for row in rows:
        own_urls = find_link_urls(str(row.get(own_link_col) or ""))
        internal_id = internal_id_from_url(own_urls[0]) if own_urls else None
        if internal_id is None:
            skipped += 1
            continue

        backlink_ids: list[str] = []
        if backlink_col is not None:
            for url in find_link_urls(str(row.get(backlink_col) or "")):
                backlink_id = internal_id_from_url(url)
                if backlink_id is not None and backlink_id != internal_id:
                    backlink_ids.append(backlink_id)

        created_at = (
            _normalize_timestamp(str(row.get(time_col) or "")) if time_col is not None else None
        )
        ai_insight = (str(row.get(ai_col) or "")).strip() or None
        parsed.append(
            NotionMemoRow(
                internal_id=internal_id,
                memo_url=own_urls[0],
                content=str(row.get(content_col) or "").strip(),
                created_at=created_at,
                backlink_ids=backlink_ids,
                ai_insight=ai_insight,
                source=f"csv:{path.name}",
            )
        )
    if skipped:
        warnings.append(f"{path.name}: {skipped} row(s) without a resolvable flomo link skipped")
    return parsed, warnings


def _section_title(line: str) -> str | None:
    stripped = line.strip()
    markdown_header = re.match(r"^#{1,6}\s+(.+)$", stripped)
    if markdown_header is not None:
        return markdown_header.group(1).strip()
    bold_header = re.match(r"^\*\*(.+?)\*\*$", stripped)
    if bold_header is not None:
        return bold_header.group(1).strip()
    return None


def _parse_markdown_files(paths: list[Path]) -> tuple[list[NotionMemoRow], list[str]]:
    warnings: list[str] = []
    parsed: list[NotionMemoRow] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        sections: dict[str, list[str]] = {"body": [], "related": [], "ai": []}
        current = "body"
        for line in text.splitlines():
            title = _section_title(line)
            if title is not None:
                lowered = title.lower()
                if any(hint in lowered for hint in ("关联", "相关", "related")):
                    current = "related"
                elif any(hint in lowered for hint in ("洞察", "insight", "ai")):
                    current = "ai"
                else:
                    current = "body"
                continue
            sections[current].append(line)

        backlink_ids: list[str] = []
        for line in sections["related"]:
            for url in find_link_urls(line):
                backlink_id = internal_id_from_url(url)
                if backlink_id is not None and backlink_id not in backlink_ids:
                    backlink_ids.append(backlink_id)

        body_text = "\n".join(sections["body"]).strip()
        own_id: str | None = None
        own_url: str | None = None
        for line in sections["body"]:
            for url in find_link_urls(line):
                candidate = internal_id_from_url(url)
                if candidate is not None and candidate not in backlink_ids:
                    own_id = candidate
                    own_url = url
                    break
            if own_id is not None:
                break
        if own_id is None:
            for url in find_link_urls(text):
                candidate = internal_id_from_url(url)
                if candidate is not None and candidate not in backlink_ids:
                    own_id = candidate
                    own_url = url
                    break
        if own_id is None or own_url is None:
            warnings.append(f"{path.name}: no flomo memo link found outside 关联自, skipped")
            continue

        ai_insight = "\n".join(
            line.strip() for line in sections["ai"] if line.strip()
        ).strip() or None
        parsed.append(
            NotionMemoRow(
                internal_id=own_id,
                memo_url=own_url,
                content=body_text,
                created_at=None,
                backlink_ids=backlink_ids,
                ai_insight=ai_insight,
                source=f"md:{path.name}",
            )
        )
    return parsed, warnings
