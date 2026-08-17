from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_VERSION = 1
FLOMO_ZIP_PATTERN = re.compile(r"^flomo@.+-(?P<date>\d{8})(?:-[0-9a-f]{8,64})?\.zip$", re.I)
MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024 * 1024


class UnsafeArchiveError(ValueError):
    """Raised when a ZIP cannot be safely imported."""


@dataclass(frozen=True)
class ImportReceipt:
    zip_sha256: str
    original_filename: str
    archived_zip: Path
    import_dir: Path
    duplicate: bool
    status: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class ImportManifestStore:
    def __init__(self, raw_root: Path) -> None:
        self.raw_root = raw_root
        self.path = raw_root / ".import-manifest.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": MANIFEST_VERSION, "imports": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("imports"), list):
            raise ValueError(f"Invalid import manifest: {self.path}")
        return payload

    def find(self, zip_sha256: str) -> dict[str, Any] | None:
        for entry in self.load()["imports"]:
            if isinstance(entry, dict) and entry.get("zip_sha256") == zip_sha256:
                return entry
        return None

    def upsert(self, zip_sha256: str, **changes: object) -> dict[str, Any]:
        payload = self.load()
        entries = payload["imports"]
        entry: dict[str, Any] | None = None
        for candidate in entries:
            if isinstance(candidate, dict) and candidate.get("zip_sha256") == zip_sha256:
                entry = candidate
                break
        if entry is None:
            entry = {"zip_sha256": zip_sha256, "created_at": _utc_now()}
            entries.append(entry)
        entry.update(changes)
        entry["updated_at"] = _utc_now()
        payload["version"] = MANIFEST_VERSION
        _write_json_atomic(self.path, payload)
        return dict(entry)


def import_flomo_zip(zip_path: Path, raw_root: Path) -> ImportReceipt:
    source = zip_path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Flomo ZIP not found: {source}")
    filename_match = FLOMO_ZIP_PATTERN.fullmatch(source.name)
    if filename_match is None:
        raise ValueError(f"Not a supported Flomo ZIP filename: {source.name}")

    zip_sha256 = _sha256(source)
    raw_root = raw_root.resolve()
    raw_root.mkdir(parents=True, exist_ok=True)
    store = ImportManifestStore(raw_root)
    existing = store.find(zip_sha256)
    if existing is not None:
        import_dir = raw_root / str(existing["import_relpath"])
        archived_zip = raw_root / str(existing["archive_relpath"])
        if import_dir.is_dir() and archived_zip.is_file():
            return ImportReceipt(
                zip_sha256=zip_sha256,
                original_filename=source.name,
                archived_zip=archived_zip,
                import_dir=import_dir,
                duplicate=True,
                status=str(existing.get("status", "received")),
            )

    export_date = filename_match.group("date")
    year = export_date[:4]
    archive_root = raw_root / ".zip-archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    archived_zip = _unique_path(archive_root / source.name, zip_sha256)
    if not archived_zip.exists():
        shutil.copy2(source, archived_zip)

    base_name = _base_export_name(source.stem)
    import_dir = _unique_directory(raw_root / year / base_name, zip_sha256)

    try:
        if not _directory_matches(import_dir, zip_sha256):
            with tempfile.TemporaryDirectory(
                prefix=".flomo-import-", dir=raw_root
            ) as temp_name:
                temp_root = Path(temp_name)
                _safe_extract(archived_zip, temp_root)
                content_root = _find_export_root(temp_root, base_name)
                import_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(content_root, import_dir)
                (import_dir / ".import-sha256").write_text(
                    zip_sha256 + "\n", encoding="ascii"
                )
    except Exception as exc:
        store.upsert(
            zip_sha256,
            original_filename=source.name,
            archive_relpath=archived_zip.relative_to(raw_root).as_posix(),
            import_relpath=import_dir.relative_to(raw_root).as_posix(),
            status="failed",
            error_message=str(exc),
        )
        raise

    store.upsert(
        zip_sha256,
        original_filename=source.name,
        archive_relpath=archived_zip.relative_to(raw_root).as_posix(),
        import_relpath=import_dir.relative_to(raw_root).as_posix(),
        status="received",
        error_message=None,
    )
    return ImportReceipt(
        zip_sha256=zip_sha256,
        original_filename=source.name,
        archived_zip=archived_zip,
        import_dir=import_dir,
        duplicate=False,
        status="received",
    )


def _base_export_name(stem: str) -> str:
    match = re.fullmatch(r"(?P<base>flomo@.+-\d{8})(?:-[0-9a-f]{8,64})?", stem, flags=re.I)
    return match.group("base") if match is not None else stem


def _unique_path(candidate: Path, zip_sha256: str) -> Path:
    if not candidate.exists():
        return candidate
    if candidate.is_file() and _sha256(candidate) == zip_sha256:
        return candidate
    return candidate.with_name(f"{candidate.stem}-{zip_sha256[:12]}{candidate.suffix}")


def _unique_directory(candidate: Path, zip_sha256: str) -> Path:
    if not candidate.exists():
        return candidate
    if _directory_matches(candidate, zip_sha256):
        return candidate
    hashed = candidate.with_name(f"{candidate.name}__{zip_sha256[:12]}")
    suffix = 1
    while hashed.exists():
        if _directory_matches(hashed, zip_sha256):
            return hashed
        suffix += 1
        hashed = candidate.with_name(f"{candidate.name}__{zip_sha256[:12]}__{suffix}")
    return hashed


def _directory_matches(candidate: Path, zip_sha256: str) -> bool:
    manifest_marker = candidate / ".import-sha256"
    return (
        candidate.is_dir()
        and manifest_marker.is_file()
        and manifest_marker.read_text(encoding="ascii").strip() == zip_sha256
    )


def _safe_extract(zip_path: Path, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UnsafeArchiveError(f"Invalid ZIP archive: {exc}") from exc

    with archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_FILES:
            raise UnsafeArchiveError(f"ZIP has too many entries: {len(members)}")
        total_bytes = sum(member.file_size for member in members)
        if total_bytes > MAX_ARCHIVE_BYTES:
            raise UnsafeArchiveError(f"ZIP expands beyond {MAX_ARCHIVE_BYTES} bytes")

        for member in members:
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or any(":" in part for part in path.parts)
            ):
                raise UnsafeArchiveError(f"Unsafe ZIP path: {member.filename}")
            if member.file_size > MAX_MEMBER_BYTES:
                raise UnsafeArchiveError(f"ZIP member is too large: {member.filename}")
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise UnsafeArchiveError(f"ZIP symlinks are not supported: {member.filename}")

        bad_member = archive.testzip()
        if bad_member is not None:
            raise UnsafeArchiveError(f"ZIP integrity check failed: {bad_member}")
        archive.extractall(destination)


def _find_export_root(temp_root: Path, base_name: str) -> Path:
    named = [
        candidate
        for candidate in temp_root.rglob("*")
        if candidate.name == base_name
        if candidate.is_dir()
        and any(child.suffix.lower() == ".html" for child in candidate.iterdir())
    ]
    if len(named) == 1:
        return named[0]

    candidates = sorted(
        {
            html.parent
            for html in temp_root.rglob("*.html")
            if html.is_file() and "__MACOSX" not in html.parts
        }
    )
    if len(candidates) != 1:
        raise UnsafeArchiveError(
            f"Expected one Flomo HTML directory, found {len(candidates)}"
        )
    return candidates[0]
