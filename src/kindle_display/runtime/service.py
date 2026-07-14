from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

from kindle_display.devices.kindle_sink import KindleSink
from kindle_display.runtime.collector_scheduler import CollectorScheduler
from kindle_display.runtime.config import AppConfig
from kindle_display.runtime.models import RefreshMode
from kindle_display.runtime.page_store import PageStore
from kindle_display.runtime.playlist_scheduler import PlaylistScheduler
from kindle_display.tasks.base import DashboardTask


class DashboardService:
    def __init__(
        self,
        config: AppConfig,
        tasks: tuple[DashboardTask, ...],
        sink: KindleSink,
    ) -> None:
        self.config = config
        self.tasks = tasks
        policies = {task.task_id: task.display_policy for task in tasks}
        cache_dir = config.runtime.run_dir / "cache" if config.runtime.persist_last_good_pages else None
        self.store = PageStore(policies, frozenset(config.kindle.fonts), cache_dir)
        self.collector = CollectorScheduler(tasks, self.store)
        self.playlist = PlaylistScheduler(
            self.store,
            sink,
            policies,
            config.playlist.task_order,
            config.playlist.full_refresh_interval_seconds,
            config.playlist.full_refresh_on_start,
            config.runtime.offline_retry_seconds,
        )
        self.sink = sink
        self.started_at = dt.datetime.now(dt.timezone.utc)

    async def run(self, stop: asyncio.Event) -> None:
        self.config.runtime.run_dir.mkdir(parents=True, exist_ok=True)
        await self.store.load_cache()
        collector_task = asyncio.create_task(self.collector.run(stop), name="collector-scheduler")
        playlist_task = asyncio.create_task(self.playlist.run(stop), name="playlist-scheduler")
        status_task = asyncio.create_task(self._status_loop(stop), name="status-writer")
        try:
            await stop.wait()
        finally:
            for task in (collector_task, playlist_task, status_task):
                task.cancel()
            await asyncio.gather(collector_task, playlist_task, status_task, return_exceptions=True)
            await self.collector.shutdown()
            await self.write_status(stopped=True)

    async def collect_all_now(self) -> None:
        await self.store.load_cache()
        await self.collector.collect_all_now()

    async def display_once(self, task_id: str | None = None, page_number: int = 1) -> None:
        await self.collect_all_now()
        states = await self.store.snapshot_all()
        selected = task_id
        if selected is None:
            selected = next(
                (candidate for candidate in self.config.playlist.task_order if states[candidate].page_set is not None),
                None,
            )
        if selected is None or selected not in states or states[selected].page_set is None:
            raise RuntimeError("no successfully collected page is available")
        page_set = states[selected].page_set
        assert page_set is not None
        if page_number < 1 or page_number > len(page_set.pages):
            raise ValueError(f"page must be between 1 and {len(page_set.pages)}")
        await self.sink.display(page_set.pages[page_number - 1], RefreshMode.FULL)

    async def write_status(self, *, stopped: bool = False) -> None:
        states = await self.store.snapshot_all()
        current = self.playlist.current_display
        payload = {
            "service_started_at": self.started_at.isoformat(),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stopped": stopped,
            "current_display": None
            if current is None
            else {
                "task_id": current.task_id,
                "page_number": current.page_number,
                "page_count": current.page_count,
                "generation": current.generation,
                "displayed_at": current.displayed_at.isoformat(),
                "refresh_mode": current.refresh_mode.value,
            },
            "last_full_refresh_at": self._iso(self.playlist.last_full_refresh_at),
            "tasks": {
                task_id: {
                    "collecting": state.collecting,
                    "generation": state.page_set.generation if state.page_set else None,
                    "page_count": len(state.page_set.pages) if state.page_set else 0,
                    "last_attempt_at": self._iso(state.last_attempt_at),
                    "last_success_at": self._iso(state.last_success_at),
                    "source_generated_at": self._iso(state.last_source_generated_at),
                    "last_error_at": self._iso(state.last_error_at),
                    "last_error": state.last_error,
                }
                for task_id, state in states.items()
            },
        }
        await asyncio.to_thread(self._write_json_atomic, self.config.runtime.run_dir / "status.json", payload)

    async def _status_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.write_status()
            await asyncio.sleep(2)

    @staticmethod
    def _iso(value: dt.datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _write_json_atomic(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
