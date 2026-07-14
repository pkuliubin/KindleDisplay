from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from kindle_display.runtime.models import DisplayPolicy, PageSpec
from kindle_display.runtime.page_store import PageStore, StaleCollectionError


UTC = dt.timezone.utc


class PageStoreTest(unittest.IsolatedAsyncioTestCase):
    def page(self, text: str = "hello") -> PageSpec:
        return PageSpec("task:0", text, "cjk_mono", 26, 20, 20, 15, 20)

    def store(self, cache_dir: Path | None = None) -> PageStore:
        return PageStore(
            {"task": DisplayPolicy(block_seconds=60, min_page_seconds=20, max_pages=3)},
            frozenset({"cjk_mono"}),
            cache_dir,
        )

    async def test_publishes_generations_and_deduplicates_content(self) -> None:
        store = self.store()
        now = dt.datetime(2026, 7, 14, 1, tzinfo=UTC)
        first_lease = await store.mark_collecting("task", now)
        self.assertIsNotNone(first_lease)
        first = await store.publish(first_lease, (self.page(),), now, now)  # type: ignore[arg-type]
        self.assertEqual(first.generation, 1)

        second_lease = await store.mark_collecting("task", now + dt.timedelta(minutes=1))
        second = await store.publish(  # type: ignore[arg-type]
            second_lease, (self.page(),), now + dt.timedelta(minutes=1), now + dt.timedelta(minutes=1)
        )
        self.assertEqual(second.generation, 1)
        state = await store.get_task_state("task")
        self.assertEqual(state.last_source_generated_at, now + dt.timedelta(minutes=1))

        third_lease = await store.mark_collecting("task", now + dt.timedelta(minutes=2))
        third = await store.publish(  # type: ignore[arg-type]
            third_lease, (self.page("changed"),), now, now + dt.timedelta(minutes=2)
        )
        self.assertEqual(third.generation, 2)

    async def test_stale_leases_cannot_publish_or_release_current_runs(self) -> None:
        store = self.store()
        now = dt.datetime(2026, 7, 14, 1, tzinfo=UTC)
        lease = await store.mark_collecting("task", now)
        await store.record_failure(lease, "timeout", now, release=False)  # type: ignore[arg-type]
        self.assertIsNone(await store.mark_collecting("task", now))
        await store.release_collection(lease)  # type: ignore[arg-type]
        current = await store.mark_collecting("task", now)
        await store.release_collection(lease)  # type: ignore[arg-type]
        self.assertTrue((await store.get_task_state("task")).collecting)
        with self.assertRaises(StaleCollectionError):
            await store.publish(lease, (self.page(),), now, now)  # type: ignore[arg-type]
        await store.release_collection(current)  # type: ignore[arg-type]

    async def test_failure_preserves_last_good_page(self) -> None:
        store = self.store()
        now = dt.datetime(2026, 7, 14, 1, tzinfo=UTC)
        first = await store.mark_collecting("task", now)
        published = await store.publish(first, (self.page(),), now, now)  # type: ignore[arg-type]
        failed = await store.mark_collecting("task", now)
        await store.record_failure(failed, "broken", now)  # type: ignore[arg-type]
        state = await store.get_task_state("task")
        self.assertEqual(state.page_set, published)
        self.assertEqual(state.last_error, "broken")
        self.assertFalse(state.collecting)

    async def test_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            store = self.store(cache_dir)
            now = dt.datetime(2026, 7, 14, 1, tzinfo=UTC)
            lease = await store.mark_collecting("task", now)
            published = await store.publish(lease, (self.page("缓存"),), now, now)  # type: ignore[arg-type]

            restored = self.store(cache_dir)
            await restored.load_cache()
            state = await restored.get_task_state("task")
        self.assertEqual(state.page_set, published)

    async def test_cache_is_loaded_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            now = dt.datetime(2026, 7, 14, 1, tzinfo=UTC)
            original = self.store(cache_dir)
            lease = await original.mark_collecting("task", now)
            await original.publish(lease, (self.page("cached"),), now, now)  # type: ignore[arg-type]

            restored = self.store(cache_dir)
            await restored.load_cache()
            changed_lease = await restored.mark_collecting("task", now)
            changed = await restored.publish(  # type: ignore[arg-type]
                changed_lease, (self.page("new"),), now, now
            )
            await restored.load_cache()
            state = await restored.get_task_state("task")
        self.assertEqual(state.page_set, changed)
