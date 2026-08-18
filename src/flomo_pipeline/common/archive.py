from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 1024 * 1024 * 1024


class UnsafeArchiveError(ValueError):
    """Raised when a ZIP cannot be safely extracted."""


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    """Validate a ZIP archive fully before extracting it into ``destination``.

    Rejects archives that could escape the destination directory (zip-slip):
    absolute paths, ``..`` segments, empty paths, drive-letter colons and
    symlinks are all refused, plus entry count / total size / per-member size
    limits and a CRC integrity pass.
    """
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
