from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING

from flomo_pipeline.common.validation import (
    Severity,
    ValidationReport,
    Violation,
)
from flomo_pipeline.links.models import LINK_MAP_FILENAME, LINK_MAP_SCHEMA_VERSION
from flomo_pipeline.links.resolver import internal_id_from_url

if TYPE_CHECKING:
    from pathlib import Path

ENTRY_REQUIRED_FIELDS = {
    "internal_id",
    "memo_url",
    "content",
    "created_at",
    "pipeline_memo_id",
    "backlink_ids",
}


class Rule(StrEnum):
    L1_LINK_MAP_PARSEABLE = "L1"
    L2_SCHEMA_VERSION = "L2"
    L3_ENTRY_SHAPE = "L3"
    L4_MEMO_URL_MATCH = "L4"
    L5_BACKLINK_TARGET_EXISTS = "L5"
    L6_PIPELINE_MEMO_ID_UNIQUE = "L6"


class LinkMapValidator:
    def __init__(self, *, store_root: Path) -> None:
        self.store_root = store_root

    def validate(self) -> ValidationReport:
        report = ValidationReport(show_line_numbers=False)
        path = self.store_root / LINK_MAP_FILENAME
        if not path.exists():
            report.add(
                Violation(
                    rule=Rule.L1_LINK_MAP_PARSEABLE,
                    severity=Severity.ERROR,
                    message=f"{LINK_MAP_FILENAME} not found under store root",
                    table="store",
                    record_id="",
                )
            )
            return report

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            report.add(
                Violation(
                    rule=Rule.L1_LINK_MAP_PARSEABLE,
                    severity=Severity.ERROR,
                    message=f"{LINK_MAP_FILENAME} is not valid JSON: {exc}",
                    table="store",
                    record_id="",
                )
            )
            return report
        if not isinstance(payload, dict):
            report.add(
                Violation(
                    rule=Rule.L1_LINK_MAP_PARSEABLE,
                    severity=Severity.ERROR,
                    message=f"{LINK_MAP_FILENAME} must contain a JSON object",
                    table="store",
                    record_id="",
                )
            )
            return report

        if str(payload.get("schema_version", "")) != LINK_MAP_SCHEMA_VERSION:
            report.add(
                Violation(
                    rule=Rule.L2_SCHEMA_VERSION,
                    severity=Severity.ERROR,
                    message=(
                        f"schema_version must be {LINK_MAP_SCHEMA_VERSION}, "
                        f"got {payload.get('schema_version')!r}"
                    ),
                    table="store",
                    record_id="",
                )
            )

        entries = payload.get("entries")
        if not isinstance(entries, dict):
            report.add(
                Violation(
                    rule=Rule.L3_ENTRY_SHAPE,
                    severity=Severity.ERROR,
                    message="entries must be an object keyed by internal id",
                    table="store",
                    record_id="",
                )
            )
            return report

        seen_pipeline_ids: dict[str, str] = {}
        valid_ids: set[str] = set()
        for internal_id, raw_entry in entries.items():
            record_id = str(internal_id)
            if not isinstance(raw_entry, dict):
                report.add(
                    Violation(
                        rule=Rule.L3_ENTRY_SHAPE,
                        severity=Severity.ERROR,
                        message="entry must be an object",
                        table="store",
                        record_id=record_id,
                    )
                )
                continue
            missing = ENTRY_REQUIRED_FIELDS - raw_entry.keys()
            if missing:
                report.add(
                    Violation(
                        rule=Rule.L3_ENTRY_SHAPE,
                        severity=Severity.ERROR,
                        message="missing field(s): " + ", ".join(sorted(missing)),
                        table="store",
                        record_id=record_id,
                    )
                )
                continue
            if not str(internal_id).isdigit():
                report.add(
                    Violation(
                        rule=Rule.L3_ENTRY_SHAPE,
                        severity=Severity.ERROR,
                        message="internal id key must be a decimal string",
                        table="store",
                        record_id=record_id,
                    )
                )
                continue
            valid_ids.add(str(internal_id))

            decoded = internal_id_from_url(str(raw_entry["memo_url"]))
            if decoded != str(internal_id):
                report.add(
                    Violation(
                        rule=Rule.L4_MEMO_URL_MATCH,
                        severity=Severity.ERROR,
                        message="memo_url does not resolve back to the entry's internal id",
                        table="store",
                        record_id=record_id,
                    )
                )

            pipeline_memo_id = raw_entry["pipeline_memo_id"]
            if pipeline_memo_id is not None:
                previous = seen_pipeline_ids.get(str(pipeline_memo_id))
                if previous is not None:
                    report.add(
                        Violation(
                            rule=Rule.L6_PIPELINE_MEMO_ID_UNIQUE,
                            severity=Severity.ERROR,
                            message=(
                                "pipeline memo_id mapped by multiple entries: "
                                f"{previous} and {internal_id}"
                            ),
                            table="store",
                            record_id=record_id,
                        )
                    )
                seen_pipeline_ids[str(pipeline_memo_id)] = str(internal_id)

        for internal_id, raw_entry in entries.items():
            if not isinstance(raw_entry, dict):
                continue
            backlink_ids = raw_entry.get("backlink_ids")
            if not isinstance(backlink_ids, list):
                continue
            for backlink_id in backlink_ids:
                if str(backlink_id) not in valid_ids:
                    report.add(
                        Violation(
                            rule=Rule.L5_BACKLINK_TARGET_EXISTS,
                            severity=Severity.WARNING,
                            message=(
                                f"backlink target {backlink_id} not found in link map "
                                "(memo may be outside this Notion database)"
                            ),
                            table="store",
                            record_id=str(internal_id),
                        )
                    )
        return report
