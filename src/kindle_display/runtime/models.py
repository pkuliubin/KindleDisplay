from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from enum import Enum


MAX_PAGE_BYTES = 256 * 1024


class RefreshMode(str, Enum):
    NORMAL = "normal"
    FULL = "full"


@dataclass(frozen=True)
class PageSpec:
    page_id: str
    text: str
    font_role: str
    font_px: int
    top: int
    left: int
    right: int
    bottom: int


@dataclass(frozen=True)
class PageSet:
    task_id: str
    generation: int
    source_generated_at: dt.datetime
    built_at: dt.datetime
    pages: tuple[PageSpec, ...]
    content_hash: str


@dataclass(frozen=True)
class CollectionPolicy:
    interval_seconds: int
    timeout_seconds: int
    run_on_start: bool = True


@dataclass(frozen=True)
class DisplayPolicy:
    block_seconds: int
    min_page_seconds: int
    max_pages: int
    weight: int = 1


@dataclass(frozen=True)
class TaskBuildResult:
    source_generated_at: dt.datetime
    pages: tuple[PageSpec, ...]


@dataclass(frozen=True)
class CollectionLease:
    task_id: str
    run_id: int


@dataclass(frozen=True)
class TaskRuntimeState:
    page_set: PageSet | None = None
    last_attempt_at: dt.datetime | None = None
    last_success_at: dt.datetime | None = None
    last_source_generated_at: dt.datetime | None = None
    last_error_at: dt.datetime | None = None
    last_error: str | None = None
    collecting: bool = False
    active_run_id: int | None = None


def validate_display_policy(policy: DisplayPolicy) -> None:
    if policy.max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if policy.min_page_seconds < 1:
        raise ValueError("min_page_seconds must be at least 1")
    if policy.block_seconds < policy.min_page_seconds:
        raise ValueError("block_seconds must be at least min_page_seconds")
    if policy.max_pages * policy.min_page_seconds > policy.block_seconds:
        raise ValueError("max_pages * min_page_seconds exceeds block_seconds")
    if not 1 <= policy.weight <= 10:
        raise ValueError("weight must be between 1 and 10")


def validate_collection_policy(policy: CollectionPolicy) -> None:
    if policy.interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if policy.timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")


def validate_pages(
    pages: tuple[PageSpec, ...], policy: DisplayPolicy, font_roles: frozenset[str]
) -> None:
    if not pages:
        raise ValueError("a page set must contain at least one page")
    if len(pages) > policy.max_pages:
        raise ValueError("page count exceeds max_pages")
    if len(pages) * policy.min_page_seconds > policy.block_seconds:
        raise ValueError("page count cannot satisfy the minimum dwell time")

    page_ids: set[str] = set()
    for page in pages:
        if not page.page_id:
            raise ValueError("page_id must not be empty")
        if page.page_id in page_ids:
            raise ValueError(f"duplicate page_id: {page.page_id}")
        page_ids.add(page.page_id)
        if page.font_role not in font_roles:
            raise ValueError(f"unknown font_role: {page.font_role}")
        if page.font_px <= 0 or page.font_px % 2:
            raise ValueError("font_px must be a positive even integer")
        if any(value < 0 for value in (page.top, page.left, page.right, page.bottom)):
            raise ValueError("page margins must be non-negative")
        if not page.text:
            raise ValueError("page text must not be empty")
        if len(page.text.encode("utf-8")) > MAX_PAGE_BYTES:
            raise ValueError("page text exceeds the maximum encoded size")
        for char in page.text:
            if char == "\n":
                continue
            if char in {"\t", "\x00", "\x1e"} or unicodedata.category(char) == "Cc":
                raise ValueError(f"page text contains unsupported control character U+{ord(char):04X}")


def page_content_hash(pages: tuple[PageSpec, ...]) -> str:
    payload = [asdict(page) for page in pages]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
