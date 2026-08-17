"""Validation for the Stage 1 raw truth layer."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from flomo_pipeline.common.validation import (
    Severity,
    ValidationReport,
    Violation,
    load_jsonl_for_validation,
)

if TYPE_CHECKING:
    from pathlib import Path


class Rule(StrEnum):
    C1_MEMO_ID_UNIQUE = "C1"
    C2_IMAGE_ID_UNIQUE = "C2"
    C3_IMAGE_COUNT_CONSISTENT = "C3"
    C4_IMAGE_MEMO_ID_EXISTS = "C4"
    C5_MISSING_IMAGE_MEMO_ID_EXISTS = "C5"
    C6_IMAGE_ID_NO_CROSS = "C6"
    C7_PATH_RELATIVE = "C7"
    C8_IMAGE_FILE_EXISTS = "C8"
    C9_SOURCE_FILE_EXPECTATION = "C9"
    C10_CREATED_AT_ISO = "C10"
    C11_NO_FRONTMATTER = "C11"
    C12_MEMO_HAS_CONTENT = "C12"
    R1_MEMO_JSONL_PARSEABLE = "R1"
    R2_IMAGE_JSONL_PARSEABLE = "R2"
    R3_MISSING_IMAGE_JSONL_PARSEABLE = "R3"
    R4_EMPTY_KEY_FIELD = "R4"
    R5_MISSING_REQUIRED_FIELD = "R5"


MEMO_FIELDS = {
    "memo_id",
    "created_at",
    "body_md",
    "image_count",
    "source_relpath",
    "batch_label",
    "ordinal",
}
IMAGE_FIELDS = {"image_id", "memo_id", "image_relpath", "source_relpath", "ordinal"}
MISSING_FIELDS = {"image_id", "memo_id", "source_relpath", "ordinal", "reason"}

MEMO_KEY_FIELDS = {"memo_id", "created_at", "source_relpath", "batch_label"}
IMAGE_KEY_FIELDS = {"image_id", "memo_id", "image_relpath", "source_relpath"}
MISSING_KEY_FIELDS = {"image_id", "memo_id", "source_relpath", "reason"}

MEMO_PATH_FIELDS = {"source_relpath"}
IMAGE_PATH_FIELDS = {"image_relpath", "source_relpath"}
MISSING_PATH_FIELDS = {"source_relpath"}

ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


class StoreValidator:
    def __init__(
        self,
        store_root: Path,
        project_root: Path | None = None,
        raw_root: Path | None = None,
    ) -> None:
        self.store_root = store_root
        self.project_root = project_root or store_root.parent
        self.raw_root = raw_root or self.project_root / "raw"
        self.memo_path = store_root / "memo.raw.jsonl"
        self.image_path = store_root / "image.raw.jsonl"
        self.missing_image_path = store_root / "missing_image.raw.jsonl"

    def validate(self) -> ValidationReport:
        report = ValidationReport(
            table_order=("memo.raw", "image.raw", "missing_image.raw", "cross-table"),
            include_warning_count=True,
        )

        memos = load_jsonl_for_validation(
            self.memo_path,
            table="memo.raw",
            report=report,
            rule=Rule.R1_MEMO_JSONL_PARSEABLE,
        )
        images = load_jsonl_for_validation(
            self.image_path,
            table="image.raw",
            report=report,
            rule=Rule.R2_IMAGE_JSONL_PARSEABLE,
        )
        missing_images = load_jsonl_for_validation(
            self.missing_image_path,
            table="missing_image.raw",
            report=report,
            rule=Rule.R3_MISSING_IMAGE_JSONL_PARSEABLE,
        )

        if not memos and not images and not missing_images:
            return report

        self._check_required_fields(memos, "memo.raw", MEMO_FIELDS, report)
        self._check_required_fields(images, "image.raw", IMAGE_FIELDS, report)
        self._check_required_fields(missing_images, "missing_image.raw", MISSING_FIELDS, report)

        self._check_empty_keys(memos, "memo.raw", MEMO_KEY_FIELDS, report)
        self._check_empty_keys(images, "image.raw", IMAGE_KEY_FIELDS, report)
        self._check_empty_keys(missing_images, "missing_image.raw", MISSING_KEY_FIELDS, report)

        self._check_id_unique(memos, "memo.raw", "memo_id", Rule.C1_MEMO_ID_UNIQUE, report)
        self._check_id_unique(images, "image.raw", "image_id", Rule.C2_IMAGE_ID_UNIQUE, report)

        memo_ids = {record.get("memo_id", "") for record in memos}
        self._check_fk_exists(
            images,
            "image.raw",
            "memo_id",
            memo_ids,
            Rule.C4_IMAGE_MEMO_ID_EXISTS,
            report,
        )
        self._check_fk_exists(
            missing_images,
            "missing_image.raw",
            "memo_id",
            memo_ids,
            Rule.C5_MISSING_IMAGE_MEMO_ID_EXISTS,
            report,
        )

        image_ids = {record.get("image_id", "") for record in images}
        missing_ids = {record.get("image_id", "") for record in missing_images}
        for image_id in image_ids & missing_ids:
            if image_id:
                report.add(
                    Violation(
                        rule=Rule.C6_IMAGE_ID_NO_CROSS,
                        severity=Severity.ERROR,
                        message="image_id appears in both image.raw and missing_image.raw",
                        table="cross-table",
                        line=0,
                        record_id=image_id,
                    )
                )

        self._check_relative_paths(memos, "memo.raw", MEMO_PATH_FIELDS, report)
        self._check_relative_paths(images, "image.raw", IMAGE_PATH_FIELDS, report)
        self._check_relative_paths(missing_images, "missing_image.raw", MISSING_PATH_FIELDS, report)

        self._check_image_files_exist(images, report)
        self._check_source_files_exist(memos, images, missing_images, report)
        self._check_iso8601(memos, report)
        self._check_image_count(memos, images, missing_images, report)
        self._check_memo_has_content(memos, report)
        self._check_frontmatter(memos, report)

        return report

    @staticmethod
    def _record_id(record: dict[str, Any]) -> str:
        return str(record.get("memo_id") or record.get("image_id") or "")

    def _check_required_fields(
        self,
        records: list[dict[str, Any]],
        table: str,
        required: set[str],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(records, start=1):
            missing_fields = required - record.keys()
            if missing_fields:
                report.add(
                    Violation(
                        rule=Rule.R5_MISSING_REQUIRED_FIELD,
                        severity=Severity.ERROR,
                        message=f"Missing required field(s): {', '.join(sorted(missing_fields))}",
                        table=table,
                        line=line_number,
                        record_id=self._record_id(record),
                    )
                )

    def _check_empty_keys(
        self,
        records: list[dict[str, Any]],
        table: str,
        key_fields: set[str],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(records, start=1):
            for field_name in sorted(key_fields):
                if record.get(field_name) == "":
                    report.add(
                        Violation(
                            rule=Rule.R4_EMPTY_KEY_FIELD,
                            severity=Severity.ERROR,
                            message=f"Empty string in key field '{field_name}'",
                            table=table,
                            line=line_number,
                            record_id=self._record_id(record),
                        )
                    )

    def _check_id_unique(
        self,
        records: list[dict[str, Any]],
        table: str,
        id_field: str,
        rule: Rule,
        report: ValidationReport,
    ) -> None:
        seen: dict[str, int] = {}
        for line_number, record in enumerate(records, start=1):
            record_id = str(record.get(id_field, ""))
            if record_id in seen:
                report.add(
                    Violation(
                        rule=rule,
                        severity=Severity.ERROR,
                        message=f"Duplicate {id_field}",
                        table=table,
                        line=line_number,
                        record_id=record_id,
                    )
                )
            else:
                seen[record_id] = line_number

    def _check_fk_exists(
        self,
        records: list[dict[str, Any]],
        table: str,
        fk_field: str,
        parent_ids: set[str],
        rule: Rule,
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(records, start=1):
            fk_value = str(record.get(fk_field, ""))
            if fk_value and fk_value not in parent_ids:
                report.add(
                    Violation(
                        rule=rule,
                        severity=Severity.ERROR,
                        message=f"{fk_field} '{fk_value}' not found in memo.raw",
                        table=table,
                        line=line_number,
                        record_id=fk_value,
                    )
                )

    def _check_relative_paths(
        self,
        records: list[dict[str, Any]],
        table: str,
        path_fields: set[str],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(records, start=1):
            for field_name in sorted(path_fields):
                value = record.get(field_name, "")
                if value and isinstance(value, str) and (
                    value.startswith("/") or value.startswith("\\")
                ):
                    report.add(
                        Violation(
                            rule=Rule.C7_PATH_RELATIVE,
                            severity=Severity.ERROR,
                            message=f"Absolute path in '{field_name}': {value}",
                            table=table,
                            line=line_number,
                            record_id=self._record_id(record),
                        )
                    )

    def _check_image_files_exist(
        self,
        images: list[dict[str, Any]],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(images, start=1):
            image_relpath = record.get("image_relpath", "")
            if not image_relpath:
                continue
            full_path = self.project_root / str(image_relpath)
            if not full_path.exists():
                report.add(
                    Violation(
                        rule=Rule.C8_IMAGE_FILE_EXISTS,
                        severity=Severity.ERROR,
                        message=f"Image file not found: {image_relpath}",
                        table="image.raw",
                        line=line_number,
                        record_id=str(record.get("image_id", "")),
                    )
                )

    def _check_source_files_exist(
        self,
        memos: list[dict[str, Any]],
        images: list[dict[str, Any]],
        missing_images: list[dict[str, Any]],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(memos, start=1):
            self._check_source_file(
                table="memo.raw",
                line_number=line_number,
                record=record,
                should_exist=True,
                report=report,
            )
        for line_number, record in enumerate(images, start=1):
            self._check_source_file(
                table="image.raw",
                line_number=line_number,
                record=record,
                should_exist=True,
                report=report,
            )
        for line_number, record in enumerate(missing_images, start=1):
            self._check_source_file(
                table="missing_image.raw",
                line_number=line_number,
                record=record,
                should_exist=False,
                report=report,
            )

    def _check_source_file(
        self,
        table: str,
        line_number: int,
        record: dict[str, Any],
        should_exist: bool,
        report: ValidationReport,
    ) -> None:
        source_relpath = record.get("source_relpath", "")
        if not source_relpath:
            return
        full_path = self.raw_root / str(source_relpath)
        exists = full_path.exists()
        if should_exist and not exists:
            report.add(
                Violation(
                    rule=Rule.C9_SOURCE_FILE_EXPECTATION,
                    severity=Severity.ERROR,
                    message=f"Source file not found under raw root: {source_relpath}",
                    table=table,
                    line=line_number,
                    record_id=self._record_id(record),
                )
            )
        if not should_exist and exists:
            report.add(
                Violation(
                    rule=Rule.C9_SOURCE_FILE_EXPECTATION,
                    severity=Severity.ERROR,
                    message=f"Missing-image record points to an existing file: {source_relpath}",
                    table=table,
                    line=line_number,
                    record_id=self._record_id(record),
                )
            )

    def _check_iso8601(self, memos: list[dict[str, Any]], report: ValidationReport) -> None:
        for line_number, record in enumerate(memos, start=1):
            created_at = record.get("created_at", "")
            if created_at and not ISO8601_RE.match(str(created_at)):
                report.add(
                    Violation(
                        rule=Rule.C10_CREATED_AT_ISO,
                        severity=Severity.ERROR,
                        message=f"Invalid ISO 8601 format: '{created_at}'",
                        table="memo.raw",
                        line=line_number,
                        record_id=str(record.get("memo_id", "")),
                    )
                )

    def _check_image_count(
        self,
        memos: list[dict[str, Any]],
        images: list[dict[str, Any]],
        missing_images: list[dict[str, Any]],
        report: ValidationReport,
    ) -> None:
        image_count_by_memo: dict[str, int] = {}
        for record in images:
            memo_id = str(record.get("memo_id", ""))
            if memo_id:
                image_count_by_memo[memo_id] = image_count_by_memo.get(memo_id, 0) + 1
        for record in missing_images:
            memo_id = str(record.get("memo_id", ""))
            if memo_id:
                image_count_by_memo[memo_id] = image_count_by_memo.get(memo_id, 0) + 1

        for line_number, record in enumerate(memos, start=1):
            memo_id = str(record.get("memo_id", ""))
            declared = record.get("image_count")
            if memo_id and declared is not None:
                actual = image_count_by_memo.get(memo_id, 0)
                if declared != actual:
                    report.add(
                        Violation(
                            rule=Rule.C3_IMAGE_COUNT_CONSISTENT,
                            severity=Severity.ERROR,
                            message=f"image_count={declared} but found {actual} image records",
                            table="memo.raw",
                            line=line_number,
                            record_id=memo_id,
                        )
                    )

    def _check_frontmatter(self, memos: list[dict[str, Any]], report: ValidationReport) -> None:
        for line_number, record in enumerate(memos, start=1):
            body_md = record.get("body_md", "")
            if isinstance(body_md, str) and body_md.startswith("---\n"):
                report.add(
                    Violation(
                        rule=Rule.C11_NO_FRONTMATTER,
                        severity=Severity.WARNING,
                        message="body_md starts with frontmatter-like header",
                        table="memo.raw",
                        line=line_number,
                        record_id=str(record.get("memo_id", "")),
                    )
                )

    def _check_memo_has_content(
        self,
        memos: list[dict[str, Any]],
        report: ValidationReport,
    ) -> None:
        for line_number, record in enumerate(memos, start=1):
            body_md = record.get("body_md")
            image_count = record.get("image_count")
            if isinstance(body_md, str) and not body_md.strip() and image_count == 0:
                report.add(
                    Violation(
                        rule=Rule.C12_MEMO_HAS_CONTENT,
                        severity=Severity.ERROR,
                        message="Memo must contain text or at least one image",
                        table="memo.raw",
                        line=line_number,
                        record_id=str(record.get("memo_id", "")),
                    )
                )
