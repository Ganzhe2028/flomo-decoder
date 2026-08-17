from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath

from bs4 import BeautifulSoup, Tag

from flomo_pipeline.common.models import ImageRecord, MemoRecord, MissingImageRecord, ParseResult


def _discover_html_files(batch_dir: Path) -> list[Path]:
    html_files = [
        candidate
        for candidate in batch_dir.iterdir()
        if candidate.is_file()
        and candidate.suffix.lower() == ".html"
        and candidate.name != ".DS_Store"
    ]
    return sorted(html_files)


def _extract_user_name(soup: BeautifulSoup) -> str:
    name_div = soup.find("div", class_="name")
    if name_div is None:
        raise ValueError("Cannot find <div class='name'> in HTML; not a valid flomo export")
    text = name_div.get_text(strip=True)
    if text.startswith("@"):
        text = text[1:]
    return text


def _slugify_user(name: str) -> str:
    return name.strip().replace(" ", "").lower()


def _extract_batch_label(batch_dir_name: str) -> str:
    pattern = r"flomo@(.+?)-(\d{8}(?:__[^/\\]+)?)$"
    match = re.search(pattern, batch_dir_name)
    if not match:
        raise ValueError(f"Cannot parse batch label from directory: {batch_dir_name}")
    return match.group(2)


def _html_to_markdown(content_div: Tag) -> str:
    parts: list[str] = []

    for element in content_div.children:
        if isinstance(element, str):
            text = element.strip()
            if text:
                parts.append(text)
            continue

        if not isinstance(element, Tag):
            continue

        tag = element.name

        if tag == "p":
            inner = _process_inline(element)
            if inner:
                parts.append(inner)
        elif tag == "br":
            parts.append("")
        elif tag in ("strong", "b"):
            parts.append(f"**{_get_inner_text(element)}**")
        elif tag in ("em", "i"):
            parts.append(f"*{_get_inner_text(element)}*")
        elif tag == "a":
            href = element.get("href", "")
            link_text = _get_inner_text(element)
            if href:
                parts.append(f"[{link_text}]({href})")
            else:
                parts.append(link_text)
        elif tag in ("ul", "ol"):
            parts.append(_html_list_to_markdown(element))
        elif tag == "img":
            continue
        elif tag == "div":
            class_list = element.get("class")
            if isinstance(class_list, list) and (
                "files" in class_list or "audio-player" in class_list
            ):
                continue
            parts.append(_html_to_markdown(element))

    while parts and parts[-1] == "":
        parts.pop()
    while parts and parts[0] == "":
        parts.pop(0)

    return "\n\n".join(parts)


def _process_inline(element: Tag) -> str:
    parts: list[str] = []
    for child in element.children:
        if isinstance(child, str):
            parts.append(child)
            continue
        if not isinstance(child, Tag):
            continue
        tag = child.name
        if tag in ("strong", "b"):
            parts.append(f"**{_get_inner_text(child)}**")
        elif tag in ("em", "i"):
            parts.append(f"*{_get_inner_text(child)}*")
        elif tag == "a":
            href = child.get("href", "")
            link_text = _get_inner_text(child)
            if href:
                parts.append(f"[{link_text}]({href})")
            else:
                parts.append(link_text)
        elif tag == "code":
            parts.append(f"`{_get_inner_text(child)}`")
        elif tag == "img":
            continue
        else:
            parts.append(_get_inner_text(child))
    return "".join(parts).strip()


def _get_inner_text(tag: Tag) -> str:
    return tag.get_text(strip=True)


def _html_list_to_markdown(element: Tag) -> str:
    ordered = element.name == "ol"
    items: list[str] = []
    for idx, li in enumerate(element.find_all("li", recursive=False), start=1):
        inner = _html_to_markdown(li).replace("\n", " ").strip()
        if ordered:
            items.append(f"{idx}. {inner}")
        else:
            items.append(f"- {inner}")
    return "\n".join(items)


def _parse_time(time_div: Tag) -> str | None:
    raw = time_div.get_text(strip=True)
    pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2}):?(\d{2})?"
    match = re.match(pattern, raw)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    second = second or "00"
    return (
        f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        f"T{int(hour):02d}:{minute}:{int(second):02d}"
    )


def _format_ordinal(value: int, *, width: int = 4) -> str:
    return f"{value:0{width}d}"


def _to_posix(path: Path | PurePosixPath) -> str:
    return path.as_posix()


def _memo_user_slug(record: MemoRecord) -> str:
    suffix = f"-{record.batch_label}--{_format_ordinal(record.ordinal)}"
    if record.memo_id.startswith("flomo-") and record.memo_id.endswith(suffix):
        return record.memo_id[len("flomo-") : -len(suffix)]
    return record.memo_id


def _canonical_image_relpath(image_relpath: str, canonical_image_id: str) -> str:
    path = PurePosixPath(image_relpath)
    return _to_posix(path.with_name(f"{canonical_image_id}{path.suffix}"))


class FlomoParser:
    def __init__(self, raw_root: Path, store_root: Path) -> None:
        self.raw_root = raw_root
        self.store_root = store_root

    def parse_all(self) -> ParseResult:
        all_memos: list[MemoRecord] = []
        images_by_id: dict[str, ImageRecord] = {}
        missing_by_id: dict[str, MissingImageRecord] = {}
        canonical_by_overlap: dict[tuple[str, str, str, int, int], MemoRecord] = {}
        prior_bodies_by_time: dict[tuple[str, str], set[str]] = defaultdict(set)
        image_id_aliases: dict[str, str] = {}
        deduplicated_count = 0
        possible_revision_count = 0

        for batch_dir in self._discover_batches():
            result = self.parse_batch(batch_dir)
            images_by_memo: dict[str, list[ImageRecord]] = defaultdict(list)
            missing_by_memo: dict[str, list[MissingImageRecord]] = defaultdict(list)
            for image in result.images:
                images_by_memo[image.memo_id].append(image)
            for missing in result.missing_images:
                missing_by_memo[missing.memo_id].append(missing)

            occurrences: dict[tuple[str, str, str, int], int] = defaultdict(int)
            batch_bodies_by_time: dict[tuple[str, str], set[str]] = defaultdict(set)
            for memo in result.memos:
                user_slug = _memo_user_slug(memo)
                signature = (user_slug, memo.created_at, memo.body_md, memo.image_count)
                occurrences[signature] += 1
                overlap_key = (*signature, occurrences[signature])
                time_key = (user_slug, memo.created_at)

                prior_bodies = prior_bodies_by_time.get(time_key)
                if prior_bodies and memo.body_md not in prior_bodies:
                    possible_revision_count += 1
                batch_bodies_by_time[time_key].add(memo.body_md)

                canonical = canonical_by_overlap.get(overlap_key)
                if canonical is None:
                    canonical_by_overlap[overlap_key] = memo
                    all_memos.append(memo)
                    for image in images_by_memo[memo.memo_id]:
                        images_by_id[image.image_id] = image
                    for missing in missing_by_memo[memo.memo_id]:
                        missing_by_id[missing.image_id] = missing
                    continue

                deduplicated_count += 1
                self._merge_duplicate_images(
                    canonical=canonical,
                    duplicate_images=images_by_memo[memo.memo_id],
                    duplicate_missing=missing_by_memo[memo.memo_id],
                    images_by_id=images_by_id,
                    missing_by_id=missing_by_id,
                    image_id_aliases=image_id_aliases,
                )

            for time_key, bodies in batch_bodies_by_time.items():
                prior_bodies_by_time[time_key].update(bodies)

        all_memos.sort(key=lambda record: record.memo_id)
        all_images = sorted(images_by_id.values(), key=lambda record: record.image_id)
        all_missing = sorted(missing_by_id.values(), key=lambda record: record.image_id)

        return ParseResult(
            memos=all_memos,
            images=all_images,
            missing_images=all_missing,
            deduplicated_count=deduplicated_count,
            possible_revision_count=possible_revision_count,
            image_id_aliases=image_id_aliases,
        )

    @staticmethod
    def _merge_duplicate_images(
        *,
        canonical: MemoRecord,
        duplicate_images: list[ImageRecord],
        duplicate_missing: list[MissingImageRecord],
        images_by_id: dict[str, ImageRecord],
        missing_by_id: dict[str, MissingImageRecord],
        image_id_aliases: dict[str, str],
    ) -> None:
        for image in duplicate_images:
            canonical_image_id = (
                f"{canonical.memo_id}--{_format_ordinal(image.ordinal, width=2)}"
            )
            image_id_aliases[image.image_id] = canonical_image_id
            if canonical_image_id in images_by_id:
                continue
            remapped = dataclasses.replace(
                image,
                image_id=canonical_image_id,
                memo_id=canonical.memo_id,
                image_relpath=_canonical_image_relpath(
                    image.image_relpath,
                    canonical_image_id,
                ),
            )
            missing_by_id.pop(canonical_image_id, None)
            images_by_id[canonical_image_id] = remapped

        for missing in duplicate_missing:
            canonical_image_id = (
                f"{canonical.memo_id}--{_format_ordinal(missing.ordinal, width=2)}"
            )
            image_id_aliases[missing.image_id] = canonical_image_id
            if canonical_image_id in images_by_id or canonical_image_id in missing_by_id:
                continue
            missing_by_id[canonical_image_id] = dataclasses.replace(
                missing,
                image_id=canonical_image_id,
                memo_id=canonical.memo_id,
            )

    def parse_batch(self, batch_dir: Path) -> ParseResult:
        html_files = _discover_html_files(batch_dir)
        if not html_files:
            raise ValueError(f"No HTML files found in {batch_dir}")

        batch_label = _extract_batch_label(batch_dir.name)
        first_html = html_files[0]
        source_html_rel = _to_posix(first_html.relative_to(self.raw_root))

        with open(first_html, encoding="utf-8") as handle:
            soup = BeautifulSoup(handle.read(), "html.parser")

        user_slug = _slugify_user(_extract_user_name(soup))
        memo_divs = soup.find_all("div", class_="memo")

        memos: list[MemoRecord] = []
        images: list[ImageRecord] = []
        missing: list[MissingImageRecord] = []

        source_batch_rel = batch_dir.relative_to(self.raw_root)
        store_images_root = PurePosixPath(self.store_root.name) / "images"

        for memo_ordinal, memo_div in enumerate(memo_divs, start=1):
            time_div = memo_div.find("div", class_="time")
            content_div = memo_div.find("div", class_="content")

            created_at = _parse_time(time_div) if isinstance(time_div, Tag) else None
            body_md = _html_to_markdown(content_div) if isinstance(content_div, Tag) else ""
            memo_id = f"flomo-{user_slug}-{batch_label}--{_format_ordinal(memo_ordinal)}"

            image_records: list[ImageRecord] = []
            missing_records: list[MissingImageRecord] = []

            for image_ordinal, image_tag in enumerate(memo_div.find_all("img"), start=1):
                src_raw = image_tag.get("src")
                if not src_raw or not isinstance(src_raw, str):
                    continue

                source_relpath = _to_posix(source_batch_rel / PurePosixPath(src_raw))
                source_abs = batch_dir / str(PurePosixPath(src_raw))
                image_id = f"{memo_id}--{_format_ordinal(image_ordinal, width=2)}"

                year_month_match = re.search(r"(\d{4})-(\d{2})", source_relpath)
                if year_month_match:
                    year = year_month_match.group(1)
                    year_month = f"{year}-{year_month_match.group(2)}"
                else:
                    year = "1970"
                    year_month = "1970-01"

                ext = PurePosixPath(source_relpath).suffix or ".png"
                image_relpath = _to_posix(
                    store_images_root / year / year_month / f"{image_id}{ext}"
                )

                if source_abs.exists():
                    image_records.append(
                        ImageRecord(
                            image_id=image_id,
                            memo_id=memo_id,
                            image_relpath=image_relpath,
                            source_relpath=source_relpath,
                            ordinal=image_ordinal,
                        )
                    )
                else:
                    missing_records.append(
                        MissingImageRecord(
                            image_id=image_id,
                            memo_id=memo_id,
                            source_relpath=source_relpath,
                            ordinal=image_ordinal,
                            reason="source_file_missing",
                        )
                    )

            memos.append(
                MemoRecord(
                    memo_id=memo_id,
                    created_at=created_at or "1970-01-01T00:00:00",
                    body_md=body_md,
                    image_count=len(image_records) + len(missing_records),
                    source_relpath=source_html_rel,
                    batch_label=batch_label,
                    ordinal=memo_ordinal,
                )
            )
            images.extend(image_records)
            missing.extend(missing_records)

        return ParseResult(memos=memos, images=images, missing_images=missing)

    def _discover_batches(self) -> list[Path]:
        batch_dirs: list[Path] = []
        for year_dir in sorted(self.raw_root.iterdir()):
            if not year_dir.is_dir() or year_dir.name.startswith("."):
                continue
            for candidate in sorted(year_dir.iterdir()):
                if not candidate.is_dir() or candidate.name.startswith("."):
                    continue
                if candidate.name.startswith("flomo@"):
                    if _discover_html_files(candidate):
                        batch_dirs.append(candidate)
                    else:
                        nested_batches = [
                            nested
                            for nested in sorted(candidate.iterdir())
                            if nested.is_dir() and nested.name.startswith("flomo@")
                        ]
                        batch_dirs.extend(nested_batches or [candidate])
                else:
                    for nested in sorted(candidate.iterdir()):
                        if nested.is_dir() and nested.name.startswith("flomo@"):
                            batch_dirs.append(nested)
        return batch_dirs
