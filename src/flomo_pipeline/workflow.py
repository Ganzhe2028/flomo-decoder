from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from flomo_pipeline.chunk import ChunkBuildRunner, ChunkValidator
from flomo_pipeline.enrich import EnrichedImageValidator, ImageEnrichmentRunner
from flomo_pipeline.enrich.providers import build_provider
from flomo_pipeline.enrich.providers.lmstudio_openai import LMStudioEnrichmentProvider
from flomo_pipeline.enrich.retry_config import resolve_lmstudio_retry_model_name
from flomo_pipeline.extract import FlomoParser, StoreValidator, StoreWriter
from flomo_pipeline.merge import MonthlyMergeRunner, MonthlyValidator
from flomo_pipeline.sync import ImportManifestStore, import_flomo_zip, publish_chunks_snapshot

if TYPE_CHECKING:
    from flomo_pipeline.enrich.provider import EnrichmentProvider

PLACEHOLDER_VALUES = {
    "",
    "<your-vision-model-name>",
    "<你的视觉模型名>",
    "your-local-vision-model",
}
QUEUED_EXIT_CODE = 75
DEDUPE_SCHEMA_VERSION = 1
PUBLICATION_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class WorkflowPaths:
    project_root: Path
    raw_root: Path
    store_root: Path
    monthly_root: Path
    chunks_root: Path
    publish_root: Path | None = None


def _normalize_month(month: str | None) -> str | None:
    """Normalize user-supplied month to zero-padded YYYY-MM format.

    Accepts flexible input like ``"2026-6"`` or ``"2026-06"`` and always
    returns ``"2026-06"`` so string comparisons against ``created_at[:7]``
    succeed downstream.
    """
    if month is None:
        return None
    stripped = month.strip()
    if not stripped:
        return None
    parts = stripped.split("-")
    if len(parts) == 2:
        try:
            year = int(parts[0])
            month_num = int(parts[1])
            return f"{year:04d}-{month_num:02d}"
        except (ValueError, TypeError):
            pass
    return stripped


@dataclass(frozen=True)
class WorkflowOptions:
    provider: str = "lmstudio"
    month: str | None = None
    image: Path | None = None
    rounds: int = 3
    workers: int = 1
    zip_path: Path | None = None


@dataclass(frozen=True)
class BuildSummary:
    memo_created_at: list[str]
    memo_ids: frozenset[str]
    affected_months: list[str]
    deduplicated_memos: int
    possible_revisions: int
    failed_images: int
    image_failures: list[dict[str, str]]


def project_path(project_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def display_path(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root))
    except ValueError:
        return str(path)


def python_executable() -> str:
    venv = os.getenv("VIRTUAL_ENV", "").strip()
    if not venv:
        return sys.executable

    venv_root = Path(venv)
    if os.name == "nt":
        candidate = venv_root / "Scripts" / "python.exe"
    else:
        candidate = venv_root / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []

    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").split("\n"):
        line = raw_line.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)

    return loaded


def require_vlm_config(*, include_retry: bool = False) -> None:
    missing: list[str] = []
    if not os.getenv("FLOMO_VLM_BASE_URL", "").strip():
        missing.append("FLOMO_VLM_BASE_URL")

    model = os.getenv("FLOMO_VLM_MODEL", "").strip()
    if model in PLACEHOLDER_VALUES:
        missing.append("FLOMO_VLM_MODEL")

    if missing:
        print(
            "Missing LM Studio configuration: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and set your real vision model name.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    print(f"vlm_model={model}")
    if include_retry:
        try:
            resolution = resolve_lmstudio_retry_model_name(base_model_name=model)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if resolution.warning is not None:
            print(f"Warning: {resolution.warning}", file=sys.stderr)
        print(f"retry_vlm_model={resolution.model_name or model}")


def run_action(action: str, paths: WorkflowPaths, options: WorkflowOptions) -> None:
    if options.rounds <= 0:
        print("--rounds must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)
    if options.workers <= 0:
        print("--workers must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)

    if action in {"first", "daily"}:
        build_chunks_from_raw(paths=paths, options=options)
        return

    if action == "probe":
        if options.image is None:
            print("--image is required for probe.", file=sys.stderr)
            raise SystemExit(2)
        probe_image(paths=paths, image=options.image)
        return

    if action == "retry":
        retry_failed_images(paths=paths, options=options)
        return

    if action == "import":
        import_and_publish(paths=paths, options=options)
        return

    raise AssertionError(f"Unhandled action: {action}")


def build_chunks_from_raw(
    *,
    paths: WorkflowPaths,
    options: WorkflowOptions,
    target_months: list[str] | None = None,
    rebuild_all: bool = False,
) -> BuildSummary:
    if options.provider == "lmstudio":
        require_vlm_config(include_retry=True)

    raw_root = paths.raw_root.resolve()
    store_root = paths.store_root.resolve()
    monthly_root = paths.monthly_root.resolve()
    chunks_root = paths.chunks_root.resolve()

    if not raw_root.is_dir():
        print(f"Error: raw directory not found: {raw_root}", file=sys.stderr)
        raise SystemExit(1)

    parse_result = FlomoParser(raw_root=raw_root, store_root=store_root).parse_all()
    StoreWriter(store_root=store_root).write(parse_result, raw_root=raw_root)
    print(f"Memos:          {len(parse_result.memos)}")
    print(f"Images:         {len(parse_result.images)}")
    print(f"Missing images: {len(parse_result.missing_images)}")
    print(f"Memo JSONL:     {store_root / 'memo.raw.jsonl'}")
    print(f"Image JSONL:    {store_root / 'image.raw.jsonl'}")
    print(f"Missing JSONL:  {store_root / 'missing_image.raw.jsonl'}")

    store_report = StoreValidator(
        store_root=store_root,
        raw_root=raw_root,
    ).validate()
    print(store_report.format_summary())
    if not store_report.ok:
        raise SystemExit(1)

    provider = _build_enrichment_provider(options.provider)
    retry_provider = _build_retry_provider(options.provider, provider, failed_only=False)
    months_to_process: list[str | None] = []
    if rebuild_all:
        months_to_process.extend(target_months or [options.month])
    elif target_months is None:
        months_to_process.append(options.month)
    else:
        all_memo_months = {
            record.created_at[:7] for record in parse_result.memos if len(record.created_at) >= 7
        }
        missing_derived_months = {
            month
            for month in all_memo_months
            if not (monthly_root / f"{month}.enriched.jsonl").is_file()
            or not any((chunks_root / month).glob("*.json"))
        }
        months_to_process.extend(sorted(set(target_months) | missing_derived_months))
    for target_month in months_to_process:
        _, enrich_stats = ImageEnrichmentRunner(
            store_root=store_root,
            provider=provider,
            retry_provider=retry_provider,
            month=target_month,
            workers=options.workers,
        ).run()
        print(enrich_stats.format_summary())
    print(f"Output: {store_root / 'image.enriched.jsonl'}")

    enriched_report = EnrichedImageValidator(store_root=store_root).validate()
    print(enriched_report.format_summary())
    if not enriched_report.ok:
        raise SystemExit(1)

    downstream_months: list[str | None] = [None] if rebuild_all else months_to_process
    for target_month in downstream_months:
        _, merge_stats = MonthlyMergeRunner(
            store_root=store_root,
            monthly_root=monthly_root,
            month=target_month,
        ).run()
        print(merge_stats.format_summary())

        monthly_report = MonthlyValidator(
            store_root=store_root,
            monthly_root=monthly_root,
            month=target_month,
        ).validate()
        print(monthly_report.format_summary())
        if not monthly_report.ok:
            raise SystemExit(1)

        _, chunk_stats = ChunkBuildRunner(
            monthly_root=monthly_root,
            chunks_root=chunks_root,
            month=target_month,
            overwrite=True,
        ).run()
        print(chunk_stats.format_summary())

        chunk_report = ChunkValidator(
            monthly_root=monthly_root,
            chunks_root=chunks_root,
            month=target_month,
        ).validate()
        print(chunk_report.format_summary())
        if not chunk_report.ok:
            raise SystemExit(1)

    if target_months is not None or rebuild_all:
        complete_monthly_report = MonthlyValidator(
            store_root=store_root,
            monthly_root=monthly_root,
        ).validate()
        print(complete_monthly_report.format_summary())
        if not complete_monthly_report.ok:
            raise SystemExit(1)
        complete_chunk_report = ChunkValidator(
            monthly_root=monthly_root,
            chunks_root=chunks_root,
        ).validate()
        print(complete_chunk_report.format_summary())
        if not complete_chunk_report.ok:
            raise SystemExit(1)
    print(f"Output dir: {monthly_root}")
    print(f"Output dir: {chunks_root}")

    if options.month:
        ready_path = display_path(paths.project_root, chunks_root / options.month)
    else:
        ready_path = display_path(paths.project_root, chunks_root / "YYYY-MM")
    print(f"Ready for external LLM input: {ready_path}")

    memo_created_at = [record.created_at for record in parse_result.memos]
    image_failures = _failed_image_details(store_root / "image.enriched.jsonl")
    return BuildSummary(
        memo_created_at=memo_created_at,
        memo_ids=frozenset(record.memo_id for record in parse_result.memos),
        affected_months=sorted({value[:7] for value in memo_created_at if len(value) >= 7}),
        deduplicated_memos=parse_result.deduplicated_count,
        possible_revisions=parse_result.possible_revision_count,
        failed_images=len(image_failures),
        image_failures=image_failures,
    )


def import_and_publish(*, paths: WorkflowPaths, options: WorkflowOptions) -> None:
    if options.zip_path is None:
        print("--zip is required for import.", file=sys.stderr)
        raise SystemExit(2)
    if paths.publish_root is None:
        print("--publish-root is required for import.", file=sys.stderr)
        raise SystemExit(2)

    raw_root = paths.raw_root.resolve()
    zip_path = project_path(paths.project_root, options.zip_path)
    manifest_store = ImportManifestStore(raw_root)
    try:
        receipt = import_flomo_zip(zip_path, raw_root)
        imported = FlomoParser(raw_root=raw_root, store_root=paths.store_root).parse_batch(
            receipt.import_dir
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    imported_times = sorted(record.created_at for record in imported.memos)
    imported_months = sorted({value[:7] for value in imported_times if len(value) >= 7})
    if not imported_times:
        manifest_store.upsert(
            receipt.zip_sha256,
            status="failed",
            memo_created_at_range={"earliest": None, "latest": None},
            affected_months=[],
            error_message="Flomo export contains no memos",
        )
        print("Error: Flomo export contains no memos.", file=sys.stderr)
        raise SystemExit(1)
    entry = manifest_store.find(receipt.zip_sha256) or {}
    if (
        receipt.duplicate
        and entry.get("status") == "published"
        and entry.get("publication_schema_version") == PUBLICATION_SCHEMA_VERSION
    ):
        print(f"Already published: {receipt.original_filename}")
        print(f"Release: {entry.get('release_id', '')}")
        return

    requires_dedupe_migration = not any(
        isinstance(candidate, dict)
        and candidate.get("status") == "published"
        and candidate.get("dedupe_schema_version") == DEDUPE_SCHEMA_VERSION
        for candidate in manifest_store.load()["imports"]
    )

    manifest_store.upsert(
        receipt.zip_sha256,
        status="received",
        memo_created_at_range={
            "earliest": imported_times[0] if imported_times else None,
            "latest": imported_times[-1] if imported_times else None,
        },
        affected_months=imported_months,
        error_message=None,
    )

    if options.provider == "lmstudio":
        queue_reason = _lmstudio_queue_reason()
        if queue_reason is not None:
            manifest_store.upsert(
                receipt.zip_sha256,
                status="queued",
                error_message=queue_reason,
            )
            print(f"Queued: {receipt.original_filename}")
            print(f"Reason: {queue_reason}")
            raise SystemExit(QUEUED_EXIT_CODE)

    manifest_store.upsert(receipt.zip_sha256, status="processing", error_message=None)
    try:
        summary = build_chunks_from_raw(
            paths=paths,
            options=options,
            target_months=imported_months,
            rebuild_all=requires_dedupe_migration,
        )
        imported_deduplicated_memos = sum(
            record.memo_id not in summary.memo_ids for record in imported.memos
        )
        result = publish_chunks_snapshot(
            chunks_root=paths.chunks_root,
            publish_root=paths.publish_root,
            memo_created_at=summary.memo_created_at,
            zip_sha256=receipt.zip_sha256,
            affected_months=imported_months,
            deduplicated_memos=imported_deduplicated_memos,
            failed_images=summary.failed_images,
            image_failures=summary.image_failures,
        )
    except (OSError, ValueError, SystemExit) as exc:
        manifest_store.upsert(
            receipt.zip_sha256,
            status="failed",
            error_message=str(exc),
        )
        raise

    manifest_store.upsert(
        receipt.zip_sha256,
        status="published",
        release_id=result.release_id,
        snapshot_relpath=result.snapshot_dir.relative_to(paths.publish_root.resolve()).as_posix(),
        max_successfully_published_created_at=max(summary.memo_created_at),
        next_export_start_date=result.next_export_start_date,
        deduplicated_memos=imported_deduplicated_memos,
        deduplicated_memos_total=summary.deduplicated_memos,
        possible_revisions=summary.possible_revisions,
        failed_images=summary.failed_images,
        image_failures=summary.image_failures,
        dedupe_schema_version=DEDUPE_SCHEMA_VERSION,
        publication_schema_version=PUBLICATION_SCHEMA_VERSION,
        error_message=None,
    )
    print(f"Published snapshot: {result.release_id}")
    print(f"Next export start date: {result.next_export_start_date}")


def _lmstudio_queue_reason() -> str | None:
    base_url = os.getenv("FLOMO_VLM_BASE_URL", "").strip()
    model = os.getenv("FLOMO_VLM_MODEL", "").strip()
    if not base_url or model in PLACEHOLDER_VALUES:
        return "LM Studio configuration is incomplete"
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return "LM Studio URL is invalid"
    models_url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(models_url, method="GET")
    api_key = os.getenv("FLOMO_VLM_API_KEY", "").strip()
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return f"LM Studio is unavailable: {exc}"
    available_models = {
        str(item.get("id", ""))
        for item in payload.get("data", [])
        if isinstance(item, dict)
    } if isinstance(payload, dict) else set()
    if available_models and model not in available_models:
        return f"LM Studio model is not loaded: {model}"
    return None


def probe_image(*, paths: WorkflowPaths, image: Path) -> None:
    require_vlm_config()
    image_path = project_path(paths.project_root, image)
    provider = LMStudioEnrichmentProvider()
    call = provider.enrich_with_response(
        image_path.resolve(),
        image_id="probe-image",
        memo_id="probe-memo",
    )

    print(f"Status: {call.result.status}")
    print(f"Base URL: {provider.base_url or '(unset)'}")
    print(f"Model: {provider.model_name}")
    print(f"Prompt version: {provider.prompt_version}")
    print(f"Slice long images: {provider.slice_long_images}")
    print(f"Force slice long images: {provider.force_slice_long_images}")
    print(f"Slice height: {provider.slice_height}")
    print(f"Slice overlap: {provider.slice_overlap}")
    print(f"Slice upscale: {provider.slice_upscale}")
    print(f"OCR text: {call.result.ocr_text}")
    print(f"Visual description: {call.result.visual_description}")
    print(f"Error: {call.result.error_message or ''}")

    if call.raw_response is not None:
        print("Raw response:")
        print(json.dumps(call.raw_response, ensure_ascii=False, indent=2))

    if call.result.status != "success":
        raise SystemExit(1)


def retry_failed_images(*, paths: WorkflowPaths, options: WorkflowOptions) -> None:
    if options.provider == "lmstudio":
        require_vlm_config(include_retry=True)

    store_root = paths.store_root.resolve()
    enriched_path = store_root / "image.enriched.jsonl"
    base_provider = _build_enrichment_provider(options.provider)
    provider = base_provider
    if options.provider == "lmstudio":
        resolution = resolve_lmstudio_retry_model_name(base_model_name=base_provider.model_name)
        if resolution.warning is not None:
            print(f"Warning: {resolution.warning}", file=sys.stderr)
        else:
            provider = build_provider(options.provider, model_name=resolution.model_name)
        print(f"retry_vlm_model={provider.model_name}")

    for round_index in range(1, options.rounds + 1):
        before = _count_failed(enriched_path, options.month)
        print(f"Retry round {round_index}/{options.rounds}")
        print(f"Failed before: {before}")
        if before == 0:
            break

        _, stats = ImageEnrichmentRunner(
            store_root=store_root,
            provider=provider,
            month=options.month,
            workers=options.workers,
            failed_only=True,
            max_failed_retries=0,
        ).run()

        print(stats.format_summary())

        report = EnrichedImageValidator(store_root=store_root).validate()
        print(report.format_summary())
        if not report.ok:
            raise SystemExit(1)

        after = _count_failed(enriched_path, options.month)
        print(f"Failed after: {after}")
        if after == 0:
            break

    print(f"Remaining failed: {_count_failed(enriched_path, options.month)}")


def _build_enrichment_provider(provider_name: str) -> EnrichmentProvider:
    try:
        provider = build_provider(provider_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if provider_name == "lmstudio":
        print(f"vlm_model={provider.model_name}")
    return provider


def _build_retry_provider(
    provider_name: str,
    provider: EnrichmentProvider,
    *,
    failed_only: bool,
) -> EnrichmentProvider | None:
    if provider_name != "lmstudio":
        return None
    if failed_only:
        return provider

    resolution = resolve_lmstudio_retry_model_name(base_model_name=provider.model_name)
    if resolution.warning is not None:
        print(f"Warning: {resolution.warning}", file=sys.stderr)
        return provider

    retry_provider = build_provider(provider_name, model_name=resolution.model_name)
    print(f"retry_vlm_model={retry_provider.model_name}")
    return retry_provider


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.rstrip("\r")
        if line.strip():
            records.append(json.loads(line))
    return records


def _count_failed(enriched_path: Path, month: str | None) -> int:
    failed = 0
    for record in _load_jsonl(enriched_path):
        if record.get("status") != "failed":
            continue
        if month is not None and record.get("month") != month:
            continue
        failed += 1
    return failed


def _failed_image_details(enriched_path: Path) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for record in _load_jsonl(enriched_path):
        if record.get("status") != "failed":
            continue
        failures.append(
            {
                "image_id": str(record.get("image_id", "")),
                "month": str(record.get("month", "")),
                "error_message": str(record.get("error_message", "Unknown image error")),
            }
        )
    return failures
