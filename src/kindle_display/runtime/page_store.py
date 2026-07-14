from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from kindle_display.runtime.models import (
    CollectionLease,
    DisplayPolicy,
    PageSet,
    PageSpec,
    TaskRuntimeState,
    page_content_hash,
    validate_pages,
)


class StaleCollectionError(RuntimeError):
    pass


@dataclass
class _MutableTaskState:
    page_set: PageSet | None = None
    last_attempt_at: dt.datetime | None = None
    last_success_at: dt.datetime | None = None
    last_source_generated_at: dt.datetime | None = None
    last_error_at: dt.datetime | None = None
    last_error: str | None = None
    collecting: bool = False
    active_run_id: int | None = None
    next_run_id: int = 1

    def snapshot(self) -> TaskRuntimeState:
        return TaskRuntimeState(
            page_set=self.page_set,
            last_attempt_at=self.last_attempt_at,
            last_success_at=self.last_success_at,
            last_source_generated_at=self.last_source_generated_at,
            last_error_at=self.last_error_at,
            last_error=self.last_error,
            collecting=self.collecting,
            active_run_id=self.active_run_id,
        )


class PageStore:
    def __init__(
        self,
        policies: dict[str, DisplayPolicy],
        font_roles: frozenset[str],
        cache_dir: Path | None = None,
    ) -> None:
        self._policies = dict(policies)
        self._font_roles = font_roles
        self._states = {task_id: _MutableTaskState() for task_id in policies}
        self._lock = asyncio.Lock()
        self._cache_dir = cache_dir
        self._cache_locks = {task_id: asyncio.Lock() for task_id in policies}
        self._cache_loaded = False

    async def mark_collecting(self, task_id: str, now: dt.datetime) -> CollectionLease | None:
        async with self._lock:
            state = self._state(task_id)
            if state.collecting:
                return None
            run_id = state.next_run_id
            state.next_run_id += 1
            state.collecting = True
            state.active_run_id = run_id
            state.last_attempt_at = now
            return CollectionLease(task_id=task_id, run_id=run_id)

    async def publish(
        self,
        lease: CollectionLease,
        pages: tuple[PageSpec, ...],
        source_generated_at: dt.datetime,
        now: dt.datetime,
    ) -> PageSet:
        self._validate_datetime(source_generated_at, "source_generated_at")
        self._validate_datetime(now, "built_at")
        policy = self._policies[lease.task_id]
        validate_pages(pages, policy, self._font_roles)
        content_hash = page_content_hash(pages)

        changed = False
        async with self._lock:
            state = self._state(lease.task_id)
            self._require_current(state, lease)
            if state.page_set is not None and state.page_set.content_hash == content_hash:
                page_set = state.page_set
            else:
                generation = 1 if state.page_set is None else state.page_set.generation + 1
                page_set = PageSet(
                    task_id=lease.task_id,
                    generation=generation,
                    source_generated_at=source_generated_at,
                    built_at=now,
                    pages=pages,
                    content_hash=content_hash,
                )
                state.page_set = page_set
                changed = True
            state.last_success_at = now
            state.last_source_generated_at = source_generated_at
            state.last_error = None
            state.collecting = False
            state.active_run_id = None

        if changed and self._cache_dir is not None:
            await self._persist_if_current(page_set)
        return page_set

    async def record_failure(
        self,
        lease: CollectionLease,
        error: str,
        now: dt.datetime,
        *,
        release: bool = True,
    ) -> None:
        async with self._lock:
            state = self._state(lease.task_id)
            if state.active_run_id != lease.run_id:
                return
            state.last_error_at = now
            state.last_error = error
            if release:
                state.collecting = False
                state.active_run_id = None

    async def release_collection(self, lease: CollectionLease) -> None:
        async with self._lock:
            state = self._state(lease.task_id)
            if state.active_run_id == lease.run_id:
                state.collecting = False
                state.active_run_id = None

    async def get_task_state(self, task_id: str) -> TaskRuntimeState:
        async with self._lock:
            return self._state(task_id).snapshot()

    async def snapshot_all(self) -> dict[str, TaskRuntimeState]:
        async with self._lock:
            return {task_id: state.snapshot() for task_id, state in self._states.items()}

    async def load_cache(self) -> None:
        if self._cache_loaded:
            return
        self._cache_loaded = True
        if self._cache_dir is None or not self._cache_dir.exists():
            return
        for task_id in self._states:
            path = self._cache_path(task_id)
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                page_set = self._deserialize_page_set(raw)
                if page_set.task_id != task_id:
                    raise ValueError("cached task ID does not match its filename")
                validate_pages(page_set.pages, self._policies[task_id], self._font_roles)
                if page_content_hash(page_set.pages) != page_set.content_hash:
                    raise ValueError("cached content hash is invalid")
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            async with self._lock:
                state = self._state(task_id)
                state.page_set = page_set
                state.last_success_at = page_set.built_at
                state.last_source_generated_at = page_set.source_generated_at
                state.next_run_id = max(state.next_run_id, page_set.generation + 1)

    async def _persist_if_current(self, page_set: PageSet) -> None:
        async with self._cache_locks[page_set.task_id]:
            async with self._lock:
                current = self._state(page_set.task_id).page_set
                if current is None or current.generation != page_set.generation:
                    return
            await asyncio.to_thread(self._write_cache, page_set)

    def _write_cache(self, page_set: PageSet) -> None:
        assert self._cache_dir is not None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": page_set.task_id,
            "generation": page_set.generation,
            "source_generated_at": page_set.source_generated_at.isoformat(),
            "built_at": page_set.built_at.isoformat(),
            "pages": [asdict(page) for page in page_set.pages],
            "content_hash": page_set.content_hash,
        }
        descriptor, temporary = tempfile.mkstemp(prefix=f".{page_set.task_id}.", suffix=".tmp", dir=self._cache_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._cache_path(page_set.task_id))
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _cache_path(self, task_id: str) -> Path:
        assert self._cache_dir is not None
        return self._cache_dir / f"{task_id}.json"

    @staticmethod
    def _deserialize_page_set(raw: dict[str, object]) -> PageSet:
        pages_raw = raw["pages"]
        if not isinstance(pages_raw, list):
            raise ValueError("cached pages must be a list")
        pages = tuple(PageSpec(**page) for page in pages_raw if isinstance(page, dict))
        if len(pages) != len(pages_raw):
            raise ValueError("cached page is not an object")
        return PageSet(
            task_id=str(raw["task_id"]),
            generation=PageStore._cached_integer(raw["generation"], "generation"),
            source_generated_at=dt.datetime.fromisoformat(str(raw["source_generated_at"])),
            built_at=dt.datetime.fromisoformat(str(raw["built_at"])),
            pages=pages,
            content_hash=str(raw["content_hash"]),
        )

    @staticmethod
    def _cached_integer(value: object, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"cached {label} must be an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as error:
                raise ValueError(f"cached {label} must be an integer") from error
        raise ValueError(f"cached {label} must be an integer")

    def _state(self, task_id: str) -> _MutableTaskState:
        try:
            return self._states[task_id]
        except KeyError as error:
            raise KeyError(f"unknown task: {task_id}") from error

    @staticmethod
    def _require_current(state: _MutableTaskState, lease: CollectionLease) -> None:
        if state.active_run_id != lease.run_id:
            raise StaleCollectionError(f"collection lease is stale: {lease.task_id}/{lease.run_id}")

    @staticmethod
    def _validate_datetime(value: dt.datetime, label: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
