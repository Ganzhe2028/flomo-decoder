from __future__ import annotations

import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from flomo_pipeline.chunk import ChunkBuildRunner
from flomo_pipeline.common.archive import UnsafeArchiveError
from flomo_pipeline.links import (
    LINK_MAP_SCHEMA_VERSION,
    LinkMap,
    LinkMapEntry,
    LinkMapValidator,
    build_link_map,
    decode_internal_id,
    find_link_urls,
    internal_id_from_url,
    parse_notion_db,
    parse_notion_input,
    resolve_text,
)
from tests.conftest import write_jsonl

if TYPE_CHECKING:
    from pathlib import Path


def _csv_content() -> str:
    rows = [
        {
            "内容": "心法就是用心看世界的方法",
            "创建时间": "2023-04-15 12:13:22",
            "链接": "https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg",
            "关联自": "",
            "AI洞察": "",
        },
        {
            "内容": "顺其自然，不是躺平",
            "创建时间": "2023-04-16 08:00:00",
            "链接": "https://v.flomoapp.com/mine/?memo_id=MjIy",
            "关联自": "https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg",
            "AI洞察": "这条笔记在讲顺其自然",
        },
        {
            "内容": "没有链接的行",
            "创建时间": "2023-04-17 08:00:00",
            "链接": "",
            "关联自": "",
            "AI洞察": "",
        },
    ]
    header = ["内容", "创建时间", "链接", "关联自", "AI洞察"]
    buffer = [",".join(header)]
    for row in rows:
        buffer.append(",".join(row[column] for column in header))
    return "\n".join(buffer) + "\n"


def test_decode_internal_id() -> None:
    assert decode_internal_id("NjM3NjIxNzg") == "63762178"
    assert decode_internal_id("MjIy") == "222"
    assert decode_internal_id("not-base64!") is None
    assert decode_internal_id("YWJj") is None  # decodes to non-digits


def test_find_link_urls_trims_trailing_punctuation() -> None:
    text = "想法https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg。以及下一句"
    urls = find_link_urls(text)
    assert urls == ["https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg"]
    assert internal_id_from_url(urls[0]) == "63762178"


def test_parse_csv_detects_columns_and_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "flomo.csv"
    csv_path.write_text(_csv_content(), encoding="utf-8-sig")

    rows, warnings = parse_notion_input(csv_path)

    assert len(rows) == 2
    assert len(warnings) == 1
    first = rows[0]
    assert first.internal_id == "63762178"
    assert first.created_at == "2023-04-15T12:13:22"
    assert first.content == "心法就是用心看世界的方法"
    assert first.backlink_ids == []
    assert first.ai_insight is None

    second = rows[1]
    assert second.internal_id == "222"
    assert second.backlink_ids == ["63762178"]
    assert second.ai_insight == "这条笔记在讲顺其自然"


def test_parse_markdown_extracts_backlinks_and_insight(tmp_path: Path) -> None:
    md_path = tmp_path / "memo page.md"
    md_path.write_text(
        "https://v.flomoapp.com/mine/?memo_id=MjIy\n"
        "顺其自然，不是躺平\n"
        "**关联自**\n"
        "https://v.flomoapp.com/mine/?memo_id=NjM3NjIxNzg\n"
        "**AI洞察**\n"
        "这条笔记在讲顺其自然\n",
        encoding="utf-8",
    )

    rows, warnings = parse_notion_input(md_path)

    assert warnings == []
    assert len(rows) == 1
    row = rows[0]
    assert row.internal_id == "222"
    assert row.backlink_ids == ["63762178"]
    assert row.ai_insight == "这条笔记在讲顺其自然"
    assert "顺其自然" in row.content


def test_parse_zip_package(tmp_path: Path) -> None:
    zip_path = tmp_path / "notion-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("flomo-数据库.csv", _csv_content())

    rows, warnings = parse_notion_input(zip_path)

    assert len(rows) == 2
    assert warnings
    assert {row.internal_id for row in rows} == {"63762178", "222"}


def test_parse_notion_zip_rejects_parent_path(tmp_path: Path) -> None:
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../outside.csv", "内容,链接\n")

    with pytest.raises(UnsafeArchiveError, match="Unsafe ZIP path"):
        parse_notion_input(zip_path)


def test_parse_notion_zip_rejects_absolute_path(tmp_path: Path) -> None:
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("/tmp/outside.csv", "x")

    with pytest.raises(UnsafeArchiveError, match="Unsafe ZIP path"):
        parse_notion_input(zip_path)


def test_parse_notion_zip_rejects_drive_colon(tmp_path: Path) -> None:
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("C:outside.csv", "x")

    with pytest.raises(UnsafeArchiveError, match="Unsafe ZIP path"):
        parse_notion_input(zip_path)


def test_parse_notion_zip_rejects_symlink(tmp_path: Path) -> None:
    import stat

    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "x")

    with pytest.raises(UnsafeArchiveError, match="symlinks"):
        parse_notion_input(zip_path)


def test_build_link_map_matches_pipeline_memos(tmp_path: Path) -> None:
    csv_path = tmp_path / "flomo.csv"
    csv_path.write_text(_csv_content(), encoding="utf-8-sig")
    rows, _ = parse_notion_input(csv_path)

    link_map = build_link_map(rows, [
        {
            "memo_id": "memo-42",
            "body_md": "#心法\n\n心法就是用心看世界的方法",
        },
        {
            "memo_id": "memo-43",
            "body_md": "顺其自然，不是躺平",
        },
        {
            "memo_id": "memo-dup-1",
            "body_md": "重复内容",
        },
        {
            "memo_id": "memo-dup-2",
            "body_md": "重复内容",
        },
    ])

    assert link_map.schema_version == LINK_MAP_SCHEMA_VERSION
    assert link_map.get("63762178").pipeline_memo_id == "memo-42"
    assert link_map.get("222").pipeline_memo_id == "memo-43"
    assert link_map.get("222").backlink_ids == ["63762178"]
    assert link_map.memo_id_to_internal() == {
        "memo-42": "63762178",
        "memo-43": "222",
    }
    assert link_map.inbound_ids("222") == ["63762178"]


def _link_map() -> LinkMap:
    return LinkMap(
        schema_version=LINK_MAP_SCHEMA_VERSION,
        entries={
            "111": LinkMapEntry(
                internal_id="111",
                memo_url="https://v.flomoapp.com/mine/?memo_id=MTEx",
                content="目标 memo 内容",
                created_at="2023-04-15T12:00:00",
                pipeline_memo_id=None,
                backlink_ids=[],
            ),
            "222": LinkMapEntry(
                internal_id="222",
                memo_url="https://v.flomoapp.com/mine/?memo_id=MjIy",
                content="我是一条被回链的 memo",
                created_at="2023-04-16T08:00:00",
                pipeline_memo_id="memo-2",
                backlink_ids=["111"],
            ),
        },
    )


def test_resolve_text_replaces_known_and_keeps_unknown() -> None:
    link_map = _link_map()
    text = "想法 https://v.flomoapp.com/mine/?memo_id=MTEx 结束，以及 https://v.flomoapp.com/mine/?memo_id=OTk5"

    resolution = resolve_text(text, link_map, from_memo_id="memo-1")

    assert "〔关联 MEMO 2023-04-15「目标 memo 内容」〕" in resolution.text
    assert "https://v.flomoapp.com/mine/?memo_id=OTk5" in resolution.text
    assert len(resolution.links) == 1
    assert resolution.links[0].to_internal_id == "111"
    assert resolution.unresolved_urls == ["https://v.flomoapp.com/mine/?memo_id=OTk5"]


def test_link_map_save_load_roundtrip(tmp_path: Path) -> None:
    link_map = _link_map()
    path = tmp_path / "store" / "link_map.json"

    link_map.save(path)
    loaded = LinkMap.load(path)

    assert loaded == link_map


def test_link_map_validator_passes_good_map(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    _link_map().save(store_root / "link_map.json")

    report = LinkMapValidator(store_root=store_root).validate()

    assert report.ok, report.format_detail()


def test_link_map_validator_catches_bad_map(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    store_root.mkdir(parents=True)
    payload = {
        "schema_version": LINK_MAP_SCHEMA_VERSION,
        "entries": {
            "111": {
                "internal_id": "111",
                "memo_url": "https://v.flomoapp.com/mine/?memo_id=MjIy",
                "content": "内容",
                "created_at": None,
                "pipeline_memo_id": "memo-1",
                "backlink_ids": ["999"],
            },
            "222": {
                "internal_id": "222",
                "memo_url": "https://v.flomoapp.com/mine/?memo_id=MjIy",
                "content": "内容",
                "created_at": None,
                "pipeline_memo_id": "memo-1",
                "backlink_ids": [],
            },
        },
    }
    (store_root / "link_map.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    report = LinkMapValidator(store_root=store_root).validate()

    assert not report.ok
    detail = report.format_detail()
    assert "does not resolve back" in detail
    assert "mapped by multiple entries" in detail
    assert report.warnings, "unknown backlink target should be a warning"


def test_link_map_validator_reports_missing_file(tmp_path: Path) -> None:
    report = LinkMapValidator(store_root=tmp_path / "store").validate()
    assert not report.ok
    assert "not found" in report.format_detail()


def test_chunk_runner_resolves_links_and_adds_related_block(tmp_path: Path) -> None:
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
                "memo_text": "想法 https://v.flomoapp.com/mine/?memo_id=MTEx 结束",
                "source_relpath": "2025/flomo@X-20251201/x.html",
                "batch_label": "20251201",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            },
            {
                "memo_id": "memo-2",
                "created_at": "2025-12-02T09:00:00",
                "month": "2025-12",
                "memo_text": "没有链接的 memo",
                "source_relpath": "2025/flomo@X-20251201/x.html",
                "batch_label": "20251201",
                "ordinal": 2,
                "image_count_raw": 0,
                "images": [],
            },
        ],
    )

    grouped, stats = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        target_tokens=60,
        hard_max_tokens=160,
        overwrite=True,
        link_map=_link_map(),
    ).run()

    chunks = grouped["2025-12"]
    assert stats.resolved_links == 1
    assert stats.unresolved_links == 0
    assert [chunk.source_memo_ids for chunk in chunks] == [["memo-1"], ["memo-2"]]

    first = chunks[0]
    assert "〔关联 MEMO 2023-04-15「目标 memo 内容」〕" in first.text
    assert "memo_id=MTEx" not in first.text
    # source_items keep the original memo_text (fact layer untouched)
    assert first.source_items[0].memo_text == "想法 https://v.flomoapp.com/mine/?memo_id=MTEx 结束"
    assert first.resolved_links[0].to_internal_id == "111"
    assert first.resolved_links[0].from_memo_id == "memo-1"

    # memo-2 is the backlink target of entry 222 (关联自 = 111), so its
    # chunk carries the inbound [RELATED] block.
    second = chunks[1]
    assert "[RELATED]" in second.text
    assert "linked_from: 2023-04-15「目标 memo 内容」" in second.text
    assert second.resolved_links == []


def test_chunk_runner_without_link_map_keeps_urls_verbatim(tmp_path: Path) -> None:
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
                "memo_text": "想法 https://v.flomoapp.com/mine/?memo_id=MTEx 结束",
                "source_relpath": "2025/flomo@X-20251201/x.html",
                "batch_label": "20251201",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            }
        ],
    )

    grouped, stats = ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=True,
    ).run()

    chunks = grouped["2025-12"]
    assert stats.resolved_links == 0
    assert "memo_id=MTEx" in chunks[0].text
    assert "[RELATED]" not in chunks[0].text
    assert chunks[0].resolved_links == []


def test_chunk_validator_accepts_resolved_links(tmp_path: Path) -> None:
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
                "memo_text": "想法 https://v.flomoapp.com/mine/?memo_id=MTEx 结束",
                "source_relpath": "2025/flomo@X-20251201/x.html",
                "batch_label": "20251201",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            }
        ],
    )

    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=True,
        link_map=_link_map(),
    ).run()

    from flomo_pipeline.chunk import ChunkValidator

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()
    assert report.ok, report.format_detail()


def test_chunk_validator_catches_bad_resolved_link(tmp_path: Path) -> None:
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
                "memo_text": "想法",
                "source_relpath": "2025/flomo@X-20251201/x.html",
                "batch_label": "20251201",
                "ordinal": 1,
                "image_count_raw": 0,
                "images": [],
            }
        ],
    )

    ChunkBuildRunner(
        monthly_root=monthly_root,
        chunks_root=chunks_root,
        overwrite=True,
    ).run()

    from flomo_pipeline.chunk import ChunkValidator

    chunk_path = chunks_root / "2025-12" / "2025-12-0001.json"
    payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    payload["resolved_links"] = [{"from_memo_id": "other-memo", "to_internal_id": "111"}]
    chunk_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = ChunkValidator(monthly_root=monthly_root, chunks_root=chunks_root).validate()
    assert not report.ok
    detail = report.format_detail()
    assert "missing required field(s)" in detail
    assert "not a source memo" in detail


def _notion_mirror(tmp_path: Path) -> Path:
    """Synthetic Notion desktop mirror with one flomo collection."""
    import base64
    import sqlite3

    db_path = tmp_path / "notion.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table collection (
            id text primary key, name text, schema text, parent_id text, parent_table text
        );
        create table collection_view (
            id text primary key, name text, parent_id text, parent_table text
        );
        create table block (
            id text primary key, parent_id text, parent_table text,
            type text, properties text, alive integer
        );
        """
    )
    collection_id = "25c09197-e017-8042-a6e0-000b8d602663"
    page_id = "3bd09197-e017-81b3-b6a6-c8d31103942c"
    view_id = "25c09197-e017-80dc-8c73-000c382713b6"
    conn.execute(
        "insert into collection (id, name, schema, parent_id, parent_table) "
        "values (?, ?, ?, ?, ?)",
        (collection_id, '[["Flomo Database"]]', "{}", page_id, "block"),
    )
    conn.execute(
        "insert into collection_view (id, name, parent_id, parent_table) values (?, ?, ?, ?)",
        (view_id, "", page_id, "block"),
    )
    conn.execute(
        "insert into block (id, parent_id, parent_table, type, properties, alive) "
        "values (?, ?, ?, 'page', null, 1)",
        (page_id, collection_id, "collection"),
    )

    def url(internal_id: str) -> str:
        encoded = base64.b64encode(internal_id.encode()).decode().rstrip("=")
        return f"https://v.flomoapp.com/mine/?memo_id={encoded}"

    def props(title: str, link: str | None, date: str) -> str:
        payload = {
            "title": [[title]],
            ";RVb": [["\u2023", [["d", {"type": "date", "start_date": date}]]]],
        }
        if link is not None:
            payload["nc@X"] = [[link, [["a", link]]]]
        return json.dumps(payload, ensure_ascii=False)

    rows = [
        # normal memo with content and own link
        ("b1", props("心法就是用心看世界的方法", url("63762178"), "2023-04-15"), 1),
        # pure backlink note memo: title is only 关联自 + full url
        ("b2", props("关联自：" + url("63762178"), url("224552223"), "2026-03-06"), 1),
        # backlink note with truncated url (drop last char of 224552223 encoding)
        ("b3", props("关联自：" + url("224552223")[:-1], url("225552224"), "2026-03-07"), 1),
        # mixed content + trailing 关联自 with truncated url (unique prefix)
        (
            "b4",
            props("正文内容 关联自：" + url("63762178")[:-1], url("225552225"), "2026-03-08"),
            1,
        ),
        # row without own link -> skipped
        ("b5", props("没有链接的memo", None, "2026-03-09"), 1),
    ]
    for block_id, properties, alive in rows:
        conn.execute(
            "insert into block (id, parent_id, parent_table, type, properties, alive) "
            "values (?, ?, 'collection', 'page', ?, ?)",
            (block_id, collection_id, properties, alive),
        )
    conn.commit()
    conn.close()
    return db_path


def test_parse_notion_db_resolves_by_page_id(tmp_path: Path) -> None:
    db_path = _notion_mirror(tmp_path)

    rows, warnings = parse_notion_db(db_path, page_id="3bd09197e01781b3b6a6c8d31103942c")

    assert any("read 4 memo rows" in warning for warning in warnings)
    assert {row.internal_id for row in rows} == {
        "63762178",
        "224552223",
        "225552224",
        "225552225",
    }

    normal = next(row for row in rows if row.internal_id == "63762178")
    assert normal.content == "心法就是用心看世界的方法"
    assert normal.created_at == "2023-04-15"
    assert normal.backlink_ids == []

    pure = next(row for row in rows if row.internal_id == "224552223")
    assert pure.content == ""
    assert pure.backlink_ids == ["63762178"]

    truncated = next(row for row in rows if row.internal_id == "225552224")
    assert truncated.backlink_ids == ["224552223"]

    mixed = next(row for row in rows if row.internal_id == "225552225")
    assert mixed.content == "正文内容"
    assert mixed.backlink_ids == ["63762178"]


def test_parse_notion_db_resolves_by_view_id(tmp_path: Path) -> None:
    db_path = _notion_mirror(tmp_path)

    rows, _ = parse_notion_db(db_path, page_id="25c09197e01780dc8c73000c382713b6")

    assert len(rows) == 4


def test_parse_notion_db_finds_flomo_collection_without_id(tmp_path: Path) -> None:
    db_path = _notion_mirror(tmp_path)

    rows, _ = parse_notion_db(db_path, page_id=None)

    assert len(rows) == 4


def test_parse_notion_db_missing_page_id(tmp_path: Path) -> None:
    db_path = _notion_mirror(tmp_path)

    rows, warnings = parse_notion_db(db_path, page_id="00000000000000000000000000000000")

    assert rows == []
    assert warnings and "does not resolve" in warnings[0]


def test_import_script_accepts_notion_url(tmp_path: Path) -> None:
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    db_path = _notion_mirror(tmp_path)
    store_root = tmp_path / "store"
    store_root.mkdir()
    write_jsonl(
        store_root / "memo.raw.jsonl",
        [
            {
                "memo_id": "memo-42",
                "created_at": "2023-04-15T12:13:22",
                "body_md": "#心法\n\n心法就是用心看世界的方法",
                "source_relpath": "2023/flomo@X-20230415/x.html",
            }
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "import_notion_links.py"),
            "--notion-url",
            "https://app.notion.com/p/https-v-flomoapp-com-mine-memo_id-MjUyMDM5"
            "-3bd09197e01781b3b6a6c8d31103942c?v=25c09197e01780dc8c73000c382713b6",
            "--notion-db",
            str(db_path),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Reading Notion offline mirror" in result.stdout
    assert "Matched to pipeline memos: 1/4" in result.stdout
    assert (store_root / "link_map.json").exists()
