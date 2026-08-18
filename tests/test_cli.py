from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

from tests.conftest import (
    FakeHTTPResponse,
    build_sample_raw,
    lmstudio_chat_response,
    run_fake_lmstudio_server,
)


def _load_guide_module() -> ModuleType:
    repo_root = Path(__file__).resolve().parent.parent
    spec = util.spec_from_file_location("guide", repo_root / "scripts" / "guide.py")
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_and_validate_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr
    assert "Memos:" in extract.stdout
    assert (store_root / "memo.raw.jsonl").exists()

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_store.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_enrich_and_validate_enriched_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    enrich = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert enrich.returncode == 0, enrich.stdout + enrich.stderr
    assert "Success:" in enrich.stdout
    assert (store_root / "image.enriched.jsonl").exists()

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_enriched_images.py"),
            "--store-root",
            str(store_root),
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_enrich_lmstudio_script_happy_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    with run_fake_lmstudio_server(
        [
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"photo text","visual_description":"First fixture image."}'
                ),
            ),
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"","visual_description":"Second fixture image."}'
                ),
            ),
        ]
    ) as server:
        env = os.environ.copy()
        env["FLOMO_VLM_BASE_URL"] = server.url
        env["FLOMO_VLM_MODEL"] = "local-vlm"
        env["FLOMO_VLM_TIMEOUT_SECONDS"] = "2"

        enrich = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "enrich_images.py"),
                "--store-root",
                str(store_root),
                "--provider",
                "lmstudio",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    assert enrich.returncode == 0, enrich.stdout + enrich.stderr
    assert "Warning: FLOMO_VLM_RETRY_MODEL is not set" in enrich.stderr
    assert "Success:" in enrich.stdout
    assert (store_root / "image.enriched.jsonl").exists()
    assert len(server.requests) == 2

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_enriched_images.py"),
            "--store-root",
            str(store_root),
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_enrich_lmstudio_script_retries_failed_records(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    with run_fake_lmstudio_server(
        [
            FakeHTTPResponse(status=500, body={"error": "temporary failure"}),
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"","visual_description":"Second fixture image."}'
                ),
            ),
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"retried text","visual_description":""}'
                ),
            ),
        ]
    ) as server:
        env = os.environ.copy()
        env["FLOMO_VLM_BASE_URL"] = server.url
        env["FLOMO_VLM_MODEL"] = "local-vlm"
        env["FLOMO_VLM_RETRY_MODEL"] = "retry-vlm"
        env["FLOMO_VLM_TIMEOUT_SECONDS"] = "2"

        enrich = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "enrich_images.py"),
                "--store-root",
                str(store_root),
                "--provider",
                "lmstudio",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    assert enrich.returncode == 0, enrich.stdout + enrich.stderr
    assert "Retry attempts: 1" in enrich.stdout
    assert "Retry success: 1" in enrich.stdout
    assert len(server.requests) == 3
    assert [request["model"] for request in server.requests] == [
        "local-vlm",
        "local-vlm",
        "retry-vlm",
    ]

    records = [
        json.loads(line)
        for line in (store_root / "image.enriched.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {record["status"] for record in records} == {"success"}
    assert {record["model_name"] for record in records} == {"local-vlm", "retry-vlm"}


def test_retry_failed_images_script_reprocesses_failed_only(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    image_record = json.loads(
        (store_root / "image.raw.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    memo_records = [
        json.loads(line)
        for line in (store_root / "memo.raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    memo_record = {
        record["memo_id"]: record for record in memo_records
    }[image_record["memo_id"]]

    with open(store_root / "image.enriched.jsonl", "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "image_id": image_record["image_id"],
                    "memo_id": image_record["memo_id"],
                    "created_at": memo_record["created_at"],
                    "month": memo_record["created_at"][:7],
                    "relative_path": image_record["image_relpath"],
                    "source_relpath": image_record["source_relpath"],
                    "media_type": "image/png",
                    "ocr_text": "",
                    "visual_description": "",
                    "model_name": "old-vlm",
                    "prompt_version": "old-v1",
                    "run_id": "old-run",
                    "status": "failed",
                    "error_message": "temporary failure",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    retry = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "retry_failed_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
            "--rounds",
            "3",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert "Remaining failed: 0" in retry.stdout

    records = [
        json.loads(line)
        for line in (store_root / "image.enriched.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["status"] == "success"
    assert records[0]["image_id"] == image_record["image_id"]


def test_retry_failed_images_script_uses_retry_lmstudio_model(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    image_record = json.loads(
        (store_root / "image.raw.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    memo_records = [
        json.loads(line)
        for line in (store_root / "memo.raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    memo_record = {record["memo_id"]: record for record in memo_records}[image_record["memo_id"]]
    (store_root / "image.enriched.jsonl").write_text(
        json.dumps(
            {
                "image_id": image_record["image_id"],
                "memo_id": image_record["memo_id"],
                "created_at": memo_record["created_at"],
                "month": memo_record["created_at"][:7],
                "relative_path": image_record["image_relpath"],
                "source_relpath": image_record["source_relpath"],
                "media_type": "image/png",
                "ocr_text": "",
                "visual_description": "",
                "model_name": "old-vlm",
                "prompt_version": "old-v1",
                "run_id": "old-run",
                "status": "failed",
                "error_message": "temporary failure",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with run_fake_lmstudio_server(
        [
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"retried text","visual_description":""}'
                ),
            )
        ]
    ) as server:
        env = os.environ.copy()
        env["FLOMO_VLM_BASE_URL"] = server.url
        env["FLOMO_VLM_MODEL"] = "regular-vlm"
        env["FLOMO_VLM_RETRY_MODEL"] = "retry-vlm"
        env["FLOMO_VLM_TIMEOUT_SECONDS"] = "2"

        retry = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "retry_failed_images.py"),
                "--store-root",
                str(store_root),
                "--provider",
                "lmstudio",
                "--rounds",
                "1",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert "retry_vlm_model=retry-vlm" in retry.stdout
    assert server.requests[0]["model"] == "retry-vlm"

    records = [
        json.loads(line)
        for line in (store_root / "image.enriched.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records[0]["status"] == "success"
    assert records[0]["model_name"] == "retry-vlm"


def test_probe_lmstudio_script_happy_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    image_path = tmp_path / "probe.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    with run_fake_lmstudio_server(
        [
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"probe text","visual_description":"Probe image."}'
                ),
            )
        ]
    ) as server:
        env = os.environ.copy()
        env["FLOMO_VLM_BASE_URL"] = server.url
        env["FLOMO_VLM_MODEL"] = "local-vlm"
        env["FLOMO_VLM_TIMEOUT_SECONDS"] = "2"

        probe = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "probe_lmstudio_vlm.py"),
                "--image",
                str(image_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert "Status: success" in probe.stdout
    assert "OCR text: probe text" in probe.stdout
    assert "Raw response:" in probe.stdout


def test_merge_and_validate_monthly_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    enrich = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert enrich.returncode == 0, enrich.stdout + enrich.stderr

    merge = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "merge_monthly.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert merge.returncode == 0, merge.stdout + merge.stderr
    assert "Monthly files written" in merge.stdout
    assert (monthly_root / "2026-03.enriched.jsonl").exists()

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_monthly.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_build_and_validate_chunks_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"

    for command in [
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "merge_monthly.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
        ],
    ]:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

    build = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "build_chunks.py"),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert "Chunks written" in build.stdout
    assert (chunks_root / "2026-03" / "2026-03-0001.json").exists()

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_chunks.py"),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_build_and_validate_reports_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    reports_root = tmp_path / "reports"

    for command in [
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "merge_monthly.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "build_chunks.py"),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
        ],
    ]:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

    build = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "build_reports.py"),
            "--chunks-root",
            str(chunks_root),
            "--reports-root",
            str(reports_root),
            "--provider",
            "mock",
            "--month",
            "2026-03",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert "Reports written: 1" in build.stdout
    assert (reports_root / "2026-03.report.md").exists()
    assert (reports_root / "2026-03.report.json").exists()

    validate = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_reports.py"),
            "--chunks-root",
            str(chunks_root),
            "--reports-root",
            str(reports_root),
            "--month",
            "2026-03",
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Validation passed" in validate.stdout


def test_run_pipeline_script_happy_path(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    reports_root = tmp_path / "reports"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    enrich = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert enrich.returncode == 0, enrich.stdout + enrich.stderr

    pipeline = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "run_pipeline.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--reports-root",
            str(reports_root),
            "--month",
            "2026-03",
            "--report-provider",
            "mock",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )
    assert pipeline.returncode == 0, pipeline.stdout + pipeline.stderr
    assert (reports_root / "2026-03.report.md").exists()


def test_guide_script_prefers_active_virtualenv_python(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    guide = _load_guide_module()
    venv_root = tmp_path / ".venv"
    if os.name == "nt":
        python_path = venv_root / "Scripts" / "python.exe"
    else:
        python_path = venv_root / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    monkeypatch.setenv("VIRTUAL_ENV", str(venv_root))

    assert guide._python_executable() == str(python_path)


def test_guide_script_mock_first_run_builds_chunks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"

    guide = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "first",
            "--provider",
            "mock",
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    assert guide.returncode == 0, guide.stdout + guide.stderr
    assert "Ready for external LLM input" in guide.stdout
    assert (chunks_root / "2026-03" / "2026-03-0001.json").exists()


def test_guide_script_loads_env_file_for_lmstudio(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"
    env_file = tmp_path / ".env"

    with run_fake_lmstudio_server(
        [
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"photo text","visual_description":"First fixture image."}'
                ),
            ),
            FakeHTTPResponse(
                status=200,
                body=lmstudio_chat_response(
                    '{"ocr_text":"","visual_description":"Second fixture image."}'
                ),
            ),
        ]
    ) as server:
        env_file.write_text(
            "\n".join(
                [
                    f"FLOMO_VLM_BASE_URL={server.url}",
                    "FLOMO_VLM_MODEL=local-vlm",
                    "FLOMO_VLM_TIMEOUT_SECONDS=2",
                ]
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.pop("FLOMO_VLM_BASE_URL", None)
        env.pop("FLOMO_VLM_MODEL", None)
        env.pop("FLOMO_VLM_TIMEOUT_SECONDS", None)

        guide = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "guide.py"),
                "--action",
                "first",
                "--provider",
                "lmstudio",
                "--env-file",
                str(env_file),
                "--raw-root",
                str(raw_root),
                "--store-root",
                str(store_root),
                "--monthly-root",
                str(monthly_root),
                "--chunks-root",
                str(chunks_root),
                "--month",
                "2026-03",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
            env=env,
        )

    assert guide.returncode == 0, guide.stdout + guide.stderr
    assert "Loaded configuration:" in guide.stdout
    assert (chunks_root / "2026-03" / "2026-03-0001.json").exists()
    assert len(server.requests) == 2


def test_guide_script_stops_when_lmstudio_config_is_missing(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    env = os.environ.copy()
    env.pop("FLOMO_VLM_BASE_URL", None)
    env.pop("FLOMO_VLM_MODEL", None)

    guide = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "first",
            "--provider",
            "lmstudio",
            "--env-file",
            str(tmp_path / ".env"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(tmp_path / "monthly"),
            "--chunks-root",
            str(tmp_path / "llm_chunks"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=env,
    )

    assert guide.returncode == 2
    assert "Missing LM Studio configuration" in guide.stderr
    assert not (store_root / "memo.raw.jsonl").exists()


def test_guide_script_stops_when_retry_model_matches_base(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["FLOMO_VLM_BASE_URL"] = "http://127.0.0.1:1234/v1"
    env["FLOMO_VLM_MODEL"] = "same-vlm"
    env["FLOMO_VLM_RETRY_MODEL"] = "same-vlm"

    guide = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "retry",
            "--provider",
            "lmstudio",
            "--env-file",
            str(tmp_path / ".env"),
            "--store-root",
            str(tmp_path / "store"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=env,
    )

    assert guide.returncode == 2
    assert "FLOMO_VLM_RETRY_MODEL must be different from FLOMO_VLM_MODEL" in guide.stderr


def test_guide_script_retry_action_uses_retry_flow(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"

    extract = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extract.returncode == 0, extract.stderr

    image_record = json.loads(
        (store_root / "image.raw.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    memo_records = [
        json.loads(line)
        for line in (store_root / "memo.raw.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    memo_record = {record["memo_id"]: record for record in memo_records}[image_record["memo_id"]]

    with open(store_root / "image.enriched.jsonl", "w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "image_id": image_record["image_id"],
                    "memo_id": image_record["memo_id"],
                    "created_at": memo_record["created_at"],
                    "month": memo_record["created_at"][:7],
                    "relative_path": image_record["image_relpath"],
                    "source_relpath": image_record["source_relpath"],
                    "media_type": "image/png",
                    "ocr_text": "",
                    "visual_description": "",
                    "model_name": "old-vlm",
                    "prompt_version": "old-v1",
                    "run_id": "old-run",
                    "status": "failed",
                    "error_message": "temporary failure",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    guide = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "guide.py"),
            "--action",
            "retry",
            "--provider",
            "mock",
            "--store-root",
            str(store_root),
            "--rounds",
            "3",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    assert guide.returncode == 0, guide.stdout + guide.stderr
    assert "Remaining failed: 0" in guide.stdout


def test_flomo_sidecar_mock_first_run_builds_chunks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = build_sample_raw(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"

    sidecar = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "flomo_sidecar.py"),
            "--action",
            "first",
            "--provider",
            "mock",
            "--project-root",
            str(tmp_path),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
    )

    assert sidecar.returncode == 0, sidecar.stdout + sidecar.stderr
    assert "Ready for external LLM input" in sidecar.stdout
    assert (chunks_root / "2026-03" / "2026-03-0001.json").exists()


def _build_sample_raw_with_links(raw_root: Path) -> Path:
    batch_dir = raw_root / "2026" / "flomo@ExampleUser-20260304"
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "ExampleUser的笔记.html").write_text(
        """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<div class="name">@ExampleUser</div>
<div class="date">于 2026-3-4 导出 2 条 MEMO</div>

<div class="memo">
  <div class="time">2026-03-01 10:00:00</div>
  <div class="content"><p>想法 https://v.flomoapp.com/mine/?memo_id=MTIz 结束</p></div>
</div>

<div class="memo">
  <div class="time">2026-03-02 14:30:00</div>
  <div class="content"><p>目标内容在这里</p></div>
</div>
</body>
</html>
""",
        encoding="utf-8",
    )
    return raw_root


def test_import_notion_links_and_build_chunks_scripts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = _build_sample_raw_with_links(tmp_path / "raw")
    store_root = tmp_path / "store"
    monthly_root = tmp_path / "monthly"
    chunks_root = tmp_path / "llm_chunks"

    for command in [
        [
            sys.executable,
            str(repo_root / "scripts" / "extract_raw.py"),
            "--raw-root",
            str(raw_root),
            "--store-root",
            str(store_root),
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "enrich_images.py"),
            "--store-root",
            str(store_root),
            "--provider",
            "mock",
        ],
        [
            sys.executable,
            str(repo_root / "scripts" / "merge_monthly.py"),
            "--store-root",
            str(store_root),
            "--monthly-root",
            str(monthly_root),
        ],
    ]:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

    csv_path = tmp_path / "notion-export.csv"
    csv_path.write_text(
        "内容,创建时间,链接,关联自\n"
        "目标内容在这里,2026-03-02 14:30:00,"
        "https://v.flomoapp.com/mine/?memo_id=MTIz,"
        "https://v.flomoapp.com/mine/?memo_id=NDU2\n"
        "想法 https://v.flomoapp.com/mine/?memo_id=MTIz 结束,2026-03-01 10:00:00,"
        "https://v.flomoapp.com/mine/?memo_id=NDU2,\n",
        encoding="utf-8",
    )

    imported = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "import_notion_links.py"),
            "--input",
            str(csv_path),
            "--store-root",
            str(store_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert "Matched to pipeline memos: 2/2" in imported.stdout
    assert (store_root / "link_map.json").exists()

    validate_map = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_link_map.py"),
            "--store-root",
            str(store_root),
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate_map.returncode == 0, validate_map.stdout + validate_map.stderr

    build = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "build_chunks.py"),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
            "--link-map",
            str(store_root / "link_map.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    assert "Links resolved: 1" in build.stdout

    chunk_payload = json.loads(
        (chunks_root / "2026-03" / "2026-03-0001.json").read_text(encoding="utf-8")
    )
    assert "〔关联 MEMO 2026-03-02「目标内容在这里」〕" in chunk_payload["text"]
    assert "memo_id=MTIz" not in chunk_payload["text"]
    assert chunk_payload["build_version"] == "chunk-v2"
    assert [link["to_internal_id"] for link in chunk_payload["resolved_links"]] == ["123"]
    # The 关联自 column of memo 123 lists 456, so the target memo's chunk
    # carries an inbound [RELATED] block.
    assert "[RELATED]" in chunk_payload["text"]
    assert "linked_from:" in chunk_payload["text"]

    validate_chunks = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "validate_chunks.py"),
            "--monthly-root",
            str(monthly_root),
            "--chunks-root",
            str(chunks_root),
            "--month",
            "2026-03",
            "--summary",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate_chunks.returncode == 0, validate_chunks.stdout + validate_chunks.stderr
