from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from flomo_pipeline.common.validation import (
    Severity,
    ValidationReport,
    Violation,
    load_json_for_validation,
    load_jsonl_for_validation,
)

if TYPE_CHECKING:
    from pathlib import Path

MONTHLY_FILE_SUFFIX = ".enriched.jsonl"
CHUNK_FILE_SUFFIX = ".json"
CHUNK_FILE_PATTERN = re.compile(r"^(\d{4}-\d{2})-(\d{4})\.json$")
MONTH_DIR_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class Rule(StrEnum):
    C1_CHUNK_ID_UNIQUE = "C1"
    C2_MONTH_MATCH = "C2"
    C3_SOURCE_MEMO_EXISTS = "C3"
    C4_SOURCE_COUNT_MATCH = "C4"
    C5_TOKEN_ESTIMATE_POSITIVE = "C5"
    C6_TEXT_NON_EMPTY = "C6"
    C7_CHUNK_INDEX_UNIQUE = "C7"
    C8_MONTH_MEMO_COVERAGE = "C8"
    C9_CREATED_AT_RANGE_VALID = "C9"
    C10_PATH_RELATIVE = "C10"
    C11_RESOLVED_LINKS_SHAPE = "C11"
    R1_MONTHLY_JSONL_PARSEABLE = "R1"
    R2_CHUNK_JSON_PARSEABLE = "R2"
    R3_REQUIRED_FIELD_MISSING = "R3"


REQUIRED_TOP_LEVEL_FIELDS = {
    "chunk_id",
    "month",
    "chunk_index",
    "source_memo_ids",
    "source_count",
    "created_at_range",
    "token_estimate",
    "text",
    "source_items",
    "build_version",
    "strategy",
    "status",
}
REQUIRED_SOURCE_ITEM_FIELDS = {
    "memo_id",
    "created_at",
    "memo_text",
    "source_relpath",
    "image_count_raw",
    "images",
}
REQUIRED_SOURCE_IMAGE_FIELDS = {
    "image_id",
    "status",
    "media_type",
    "relative_path",
    "source_relpath",
    "ocr_text",
    "visual_description",
    "error_message",
}

RESOLVED_LINK_FIELDS = {
    "from_memo_id",
    "to_internal_id",
    "to_memo_id",
    "to_created_at",
    "to_snippet",
}


class ChunkValidator:
    def __init__(self, *, monthly_root: Path, chunks_root: Path, month: str | None = None) -> None:
        self.monthly_root = monthly_root
        self.chunks_root = chunks_root
        self.month = month

    def validate(self) -> ValidationReport:
        report = ValidationReport(show_line_numbers=False)
        seen_chunk_ids: set[str] = set()

        target_months = self._discover_months()
        for month in target_months:
            monthly_records = load_jsonl_for_validation(
                self.monthly_root / f"{month}{MONTHLY_FILE_SUFFIX}",
                report=report,
                table=f"monthly/{month}.enriched.jsonl",
                rule=Rule.R1_MONTHLY_JSONL_PARSEABLE,
            )
            monthly_by_id = {str(record.get("memo_id", "")): record for record in monthly_records}
            chunk_dir = self.chunks_root / month
            chunk_paths = sorted(chunk_dir.glob(f"*{CHUNK_FILE_SUFFIX}"))

            if monthly_records and not chunk_paths:
                report.add(
                    Violation(
                        rule=Rule.C8_MONTH_MEMO_COVERAGE,
                        severity=Severity.ERROR,
                        message=f"No chunk files found for month {month}",
                        table=f"llm_chunks/{month}",
                        record_id="",
                    )
                )
                continue

            observed_memo_ids: list[str] = []
            seen_chunk_indexes: set[int] = set()
            chunk_indexes: list[int] = []

            for chunk_path in chunk_paths:
                record = load_json_for_validation(
                    chunk_path,
                    report=report,
                    table=f"llm_chunks/{month}",
                    rule=Rule.R2_CHUNK_JSON_PARSEABLE,
                )
                if record is None:
                    continue

                chunk_id = str(record.get("chunk_id", ""))
                missing_fields = REQUIRED_TOP_LEVEL_FIELDS - record.keys()
                if missing_fields:
                    report.add(
                        Violation(
                            rule=Rule.R3_REQUIRED_FIELD_MISSING,
                            severity=Severity.ERROR,
                    message=(
                        "Missing required field(s): "
                        f"{', '.join(sorted(missing_fields))}"
                    ),
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id or chunk_path.name,
                        )
                    )
                    continue

                if chunk_id in seen_chunk_ids:
                    report.add(
                        Violation(
                            rule=Rule.C1_CHUNK_ID_UNIQUE,
                            severity=Severity.ERROR,
                            message="Duplicate chunk_id across generated output",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )
                seen_chunk_ids.add(chunk_id)

                path_match = CHUNK_FILE_PATTERN.match(chunk_path.name)
                if not path_match:
                    report.add(
                        Violation(
                            rule=Rule.C2_MONTH_MATCH,
                            severity=Severity.ERROR,
                            message=f"Unexpected chunk filename: {chunk_path.name}",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )
                elif path_match.group(1) != month:
                    report.add(
                        Violation(
                            rule=Rule.C2_MONTH_MATCH,
                            severity=Severity.ERROR,
                            message="Chunk filename month does not match directory month",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )

                if str(record.get("month", "")) != month:
                    report.add(
                        Violation(
                            rule=Rule.C2_MONTH_MATCH,
                            severity=Severity.ERROR,
                            message="Chunk month does not match directory/source month",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )

                token_estimate = record.get("token_estimate")
                if not isinstance(token_estimate, int) or token_estimate <= 0:
                    report.add(
                        Violation(
                            rule=Rule.C5_TOKEN_ESTIMATE_POSITIVE,
                            severity=Severity.ERROR,
                            message="token_estimate must be a positive integer",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )

                if (
                    str(record.get("status", "")) == "success"
                    and not str(record.get("text", "")).strip()
                ):
                    report.add(
                        Violation(
                            rule=Rule.C6_TEXT_NON_EMPTY,
                            severity=Severity.ERROR,
                            message="successful chunk must have non-empty text",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )

                chunk_index = record.get("chunk_index")
                if not isinstance(chunk_index, int):
                    report.add(
                        Violation(
                            rule=Rule.C7_CHUNK_INDEX_UNIQUE,
                            severity=Severity.ERROR,
                            message="chunk_index must be an integer",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )
                else:
                    chunk_indexes.append(chunk_index)
                    if chunk_index in seen_chunk_indexes:
                        report.add(
                            Violation(
                                rule=Rule.C7_CHUNK_INDEX_UNIQUE,
                                severity=Severity.ERROR,
                                message="Duplicate chunk_index within month",
                                table=f"llm_chunks/{month}",
                                record_id=chunk_id,
                            )
                        )
                    seen_chunk_indexes.add(chunk_index)

                source_memo_ids = record.get("source_memo_ids")
                if not isinstance(source_memo_ids, list):
                    report.add(
                        Violation(
                            rule=Rule.C4_SOURCE_COUNT_MATCH,
                            severity=Severity.ERROR,
                            message="source_memo_ids must be an array",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )
                    continue

                if record.get("source_count") != len(source_memo_ids):
                    report.add(
                        Violation(
                            rule=Rule.C4_SOURCE_COUNT_MATCH,
                            severity=Severity.ERROR,
                            message="source_count does not match source_memo_ids length",
                            table=f"llm_chunks/{month}",
                            record_id=chunk_id,
                        )
                    )

                observed_memo_ids.extend(str(memo_id) for memo_id in source_memo_ids)
                for memo_id in source_memo_ids:
                    if str(memo_id) not in monthly_by_id:
                        report.add(
                            Violation(
                                rule=Rule.C3_SOURCE_MEMO_EXISTS,
                                severity=Severity.ERROR,
                                message="source_memo_id not found in monthly source",
                                table=f"llm_chunks/{month}",
                                record_id=chunk_id,
                            )
                        )

                self._validate_created_at_range(record, monthly_by_id, report, month)
                self._validate_source_items(record, monthly_by_id, report, month)
                self._validate_resolved_links(record, report, month)

            expected_memo_ids = [str(record.get("memo_id", "")) for record in monthly_records]
            if observed_memo_ids != expected_memo_ids:
                report.add(
                    Violation(
                        rule=Rule.C8_MONTH_MEMO_COVERAGE,
                        severity=Severity.ERROR,
                        message="Monthly memo coverage does not match chunk source membership",
                        table=f"llm_chunks/{month}",
                        record_id="",
                    )
                )

            if chunk_indexes and sorted(chunk_indexes) != list(range(1, len(chunk_indexes) + 1)):
                report.add(
                    Violation(
                        rule=Rule.C7_CHUNK_INDEX_UNIQUE,
                        severity=Severity.ERROR,
                        message="chunk_index values must be contiguous starting at 1",
                        table=f"llm_chunks/{month}",
                        record_id="",
                    )
                )

        return report

    def _discover_months(self) -> list[str]:
        if self.month is not None:
            return [self.month]

        monthly_months = {
            path.name[:7]
            for path in self.monthly_root.glob(f"*{MONTHLY_FILE_SUFFIX}")
        }
        chunk_months = {
            path.name
            for path in self.chunks_root.iterdir()
            if path.is_dir() and MONTH_DIR_PATTERN.fullmatch(path.name)
        } if self.chunks_root.exists() else set()
        return sorted(monthly_months | chunk_months)

    def _validate_created_at_range(
        self,
        record: dict[str, Any],
        monthly_by_id: dict[str, dict[str, Any]],
        report: ValidationReport,
        month: str,
    ) -> None:
        chunk_id = str(record.get("chunk_id", ""))
        created_at_range = record.get("created_at_range")
        if not isinstance(created_at_range, dict):
            report.add(
                Violation(
                    rule=Rule.C9_CREATED_AT_RANGE_VALID,
                    severity=Severity.ERROR,
                    message="created_at_range must be an object",
                    table=f"llm_chunks/{month}",
                    record_id=chunk_id,
                )
            )
            return

        start = str(created_at_range.get("start", ""))
        end = str(created_at_range.get("end", ""))
        if not ISO8601_RE.match(start) or not ISO8601_RE.match(end):
            report.add(
                Violation(
                    rule=Rule.C9_CREATED_AT_RANGE_VALID,
                    severity=Severity.ERROR,
                    message="created_at_range must contain valid ISO timestamps",
                    table=f"llm_chunks/{month}",
                    record_id=chunk_id,
                )
            )
            return

        source_times = [
            str(monthly_by_id[str(memo_id)]["created_at"])
            for memo_id in record.get("source_memo_ids", [])
            if str(memo_id) in monthly_by_id
        ]
        if source_times and (start != min(source_times) or end != max(source_times)):
            report.add(
                Violation(
                    rule=Rule.C9_CREATED_AT_RANGE_VALID,
                    severity=Severity.ERROR,
                    message="created_at_range does not match included memo timestamps",
                    table=f"llm_chunks/{month}",
                    record_id=chunk_id,
                )
            )

    def _validate_source_items(
        self,
        record: dict[str, Any],
        monthly_by_id: dict[str, dict[str, Any]],
        report: ValidationReport,
        month: str,
    ) -> None:
        chunk_id = str(record.get("chunk_id", ""))
        source_items = record.get("source_items")
        if not isinstance(source_items, list):
            report.add(
                Violation(
                    rule=Rule.R3_REQUIRED_FIELD_MISSING,
                    severity=Severity.ERROR,
                    message="source_items must be an array",
                    table=f"llm_chunks/{month}",
                    record_id=chunk_id,
                )
            )
            return

        source_item_memo_ids: list[str] = []
        for item in source_items:
            if not isinstance(item, dict):
                report.add(
                    Violation(
                        rule=Rule.R3_REQUIRED_FIELD_MISSING,
                        severity=Severity.ERROR,
                        message="source_items entries must be objects",
                        table=f"llm_chunks/{month}",
                        record_id=chunk_id,
                    )
                )
                continue

            missing_fields = REQUIRED_SOURCE_ITEM_FIELDS - item.keys()
            memo_id = str(item.get("memo_id", ""))
            if missing_fields:
                report.add(
                    Violation(
                        rule=Rule.R3_REQUIRED_FIELD_MISSING,
                        severity=Severity.ERROR,
                        message=(
                            "source_item missing required field(s): "
                            f"{', '.join(sorted(missing_fields))}"
                        ),
                        table=f"llm_chunks/{month}",
                        record_id=memo_id or chunk_id,
                    )
                )
                continue

            source_item_memo_ids.append(memo_id)
            if memo_id in monthly_by_id:
                monthly_record = monthly_by_id[memo_id]
                if str(item.get("created_at", "")) != str(monthly_record.get("created_at", "")):
                    report.add(
                        Violation(
                            rule=Rule.C3_SOURCE_MEMO_EXISTS,
                            severity=Severity.ERROR,
                            message="source_item created_at does not match monthly source",
                            table=f"llm_chunks/{month}",
                            record_id=memo_id,
                        )
                    )
                if str(item.get("memo_text", "")) != str(monthly_record.get("memo_text", "")):
                    report.add(
                        Violation(
                            rule=Rule.C3_SOURCE_MEMO_EXISTS,
                            severity=Severity.ERROR,
                            message="source_item memo_text does not match monthly source",
                            table=f"llm_chunks/{month}",
                            record_id=memo_id,
                        )
                    )

            self._check_relative_path(
                table=f"llm_chunks/{month}",
                report=report,
                record_id=memo_id or chunk_id,
                value=str(item.get("source_relpath", "")),
            )

            images = item.get("images")
            if not isinstance(images, list):
                report.add(
                    Violation(
                        rule=Rule.R3_REQUIRED_FIELD_MISSING,
                        severity=Severity.ERROR,
                        message="source_item images must be an array",
                        table=f"llm_chunks/{month}",
                        record_id=memo_id or chunk_id,
                    )
                )
                continue

            for image in images:
                if not isinstance(image, dict):
                    report.add(
                        Violation(
                            rule=Rule.R3_REQUIRED_FIELD_MISSING,
                            severity=Severity.ERROR,
                            message="source_item image entries must be objects",
                            table=f"llm_chunks/{month}",
                            record_id=memo_id or chunk_id,
                        )
                    )
                    continue
                missing_image_fields = REQUIRED_SOURCE_IMAGE_FIELDS - image.keys()
                image_id = str(image.get("image_id", ""))
                if missing_image_fields:
                    report.add(
                        Violation(
                            rule=Rule.R3_REQUIRED_FIELD_MISSING,
                            severity=Severity.ERROR,
                            message=(
                                "source_item image missing required field(s): "
                                + ", ".join(sorted(missing_image_fields))
                            ),
                            table=f"llm_chunks/{month}",
                            record_id=image_id or memo_id or chunk_id,
                        )
                    )
                    continue
                self._check_relative_path(
                    table=f"llm_chunks/{month}",
                    report=report,
                    record_id=image_id or memo_id or chunk_id,
                    value=str(image.get("relative_path", "")),
                )
                self._check_relative_path(
                    table=f"llm_chunks/{month}",
                    report=report,
                    record_id=image_id or memo_id or chunk_id,
                    value=str(image.get("source_relpath", "")),
                )

        if source_item_memo_ids != [str(memo_id) for memo_id in record.get("source_memo_ids", [])]:
            report.add(
                Violation(
                    rule=Rule.C8_MONTH_MEMO_COVERAGE,
                    severity=Severity.ERROR,
                    message="source_items memo order does not match source_memo_ids",
                    table=f"llm_chunks/{month}",
                    record_id=chunk_id,
                )
            )

    @staticmethod
    def _check_relative_path(
        *,
        table: str,
        report: ValidationReport,
        record_id: str,
        value: str,
    ) -> None:
        if value.startswith("/") or value.startswith("\\"):
            report.add(
                Violation(
                    rule=Rule.C10_PATH_RELATIVE,
                    severity=Severity.ERROR,
                    message=f"Absolute path found: {value}",
                    table=table,
                    record_id=record_id,
                )
            )

    def _validate_resolved_links(
        self,
        record: dict[str, Any],
        report: ValidationReport,
        month: str,
    ) -> None:
        resolved_links = record.get("resolved_links")
        if resolved_links is None:
            return
        chunk_id = str(record.get("chunk_id", ""))
        table = f"llm_chunks/{month}"
        if not isinstance(resolved_links, list):
            report.add(
                Violation(
                    rule=Rule.C11_RESOLVED_LINKS_SHAPE,
                    severity=Severity.ERROR,
                    message="resolved_links must be an array",
                    table=table,
                    record_id=chunk_id,
                )
            )
            return

        source_memo_ids = {
            str(memo_id) for memo_id in record.get("source_memo_ids", [])
        }
        for link in resolved_links:
            if not isinstance(link, dict):
                report.add(
                    Violation(
                        rule=Rule.C11_RESOLVED_LINKS_SHAPE,
                        severity=Severity.ERROR,
                        message="resolved_links entries must be objects",
                        table=table,
                        record_id=chunk_id,
                    )
                )
                continue
            missing = RESOLVED_LINK_FIELDS - link.keys()
            if missing:
                report.add(
                    Violation(
                        rule=Rule.C11_RESOLVED_LINKS_SHAPE,
                        severity=Severity.ERROR,
                        message=(
                            "resolved link missing required field(s): "
                            + ", ".join(sorted(missing))
                        ),
                        table=table,
                        record_id=chunk_id,
                    )
                )
            if "from_memo_id" in link and str(link["from_memo_id"]) not in source_memo_ids:
                report.add(
                    Violation(
                        rule=Rule.C11_RESOLVED_LINKS_SHAPE,
                        severity=Severity.ERROR,
                        message=(
                            "resolved link from_memo_id is not a source memo "
                            "of this chunk"
                        ),
                        table=table,
                        record_id=chunk_id,
                    )
                )
            if "to_internal_id" in link and not str(link["to_internal_id"]).isdigit():
                report.add(
                    Violation(
                        rule=Rule.C11_RESOLVED_LINKS_SHAPE,
                        severity=Severity.ERROR,
                        message="resolved link to_internal_id must be a decimal string",
                        table=table,
                        record_id=chunk_id,
                    )
                )
