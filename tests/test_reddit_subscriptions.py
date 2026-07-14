from __future__ import annotations

import datetime as dt
import unittest

from kindle_display.runtime.models import DisplayPolicy, validate_pages
from kindle_display.tasks.reddit_subscriptions.dashboard import RedditSubscriptionsDashboard
from kindle_display.tasks.reddit_subscriptions.renderer import RedditSubscriptionsRenderer


UTC = dt.timezone.utc


class RedditSubscriptionsTest(unittest.TestCase):
    def raw(self, count: int, *, active: int = 0) -> dict[str, object]:
        subscriptions = []
        for index in range(count):
            status = "running" if index < 4 else "completed"
            subscriptions.append(
                {
                    "subscription_id": f"id-{index}",
                    "source_key": f"community_{index:02d}",
                    "enabled": True,
                    "interval_seconds": 28800,
                    "next_run_at": "2026-07-14T02:00:00+00:00",
                    "last_successful_run_at": "2026-07-13T18:41:25+00:00",
                    "last_run": {
                        "status": status,
                        "new_document_count": index,
                        "updated_document_count": index + 1,
                        "failed_item_count": 0,
                        "error": None,
                    },
                    "cumulative_post_count": 100 + index,
                }
            )
        return {
            "generated_at": "2026-07-14T02:23:29+00:00",
            "summary": {
                "subscription_count": count,
                "enabled_subscription_count": count,
                "due_subscription_count": max(0, count - 4),
                "active_task_count": active,
                "subscribed_community_post_count": 5380,
            },
            "subscriptions": subscriptions,
        }

    def renderer(self, maximum: int = 24) -> RedditSubscriptionsRenderer:
        return RedditSubscriptionsRenderer("reddit", 12, maximum, "Asia/Shanghai")

    def test_nineteen_subscriptions_render_as_two_self_contained_pages(self) -> None:
        snapshot = RedditSubscriptionsDashboard().normalize(
            self.raw(19, active=0), dt.datetime(2026, 7, 14, 3, tzinfo=UTC)
        )
        pages = self.renderer().render_pages(snapshot)
        self.assertEqual(len(pages), 2)
        self.assertEqual([page.page_id for page in pages], ["reddit:0", "reddit:1"])
        for index, page in enumerate(pages, start=1):
            self.assertIn(f"{index}/2", page.text)
            self.assertIn("DATA 07-14 10:23", page.text)
            self.assertIn("0 ACTIVE", page.text)
            self.assertIn("FREQ", page.text)
            self.assertIn("NEXT", page.text)
        self.assertIn("8h", pages[0].text)
        self.assertIn("14-10:00", pages[0].text)
        self.assertIn("14-02:41", pages[0].text)
        self.assertNotIn("7h", pages[0].text)
        validate_pages(pages, DisplayPolicy(30, 15, 2), frozenset({"cjk_mono"}))

    def test_active_summary_does_not_use_last_run_running_count(self) -> None:
        snapshot = RedditSubscriptionsDashboard().normalize(
            self.raw(6, active=0), dt.datetime(2026, 7, 14, 3, tzinfo=UTC)
        )
        page = self.renderer().render_pages(snapshot)[0]
        self.assertIn("0 ACTIVE", page.text)
        self.assertEqual(sum(item.last_run_status == "running" for item in snapshot.subscriptions), 4)

    def test_errors_sort_first_and_null_last_run_is_supported(self) -> None:
        raw = self.raw(3)
        subscriptions = raw["subscriptions"]
        assert isinstance(subscriptions, list)
        subscriptions[0]["last_run"] = None
        subscriptions[1]["last_run"]["status"] = "failed"
        subscriptions[1]["last_run"]["error"] = "network"
        snapshot = RedditSubscriptionsDashboard().normalize(raw, dt.datetime(2026, 7, 14, 3, tzinfo=UTC))
        self.assertEqual(snapshot.subscriptions[0].source_key, "community_01")
        self.assertEqual(snapshot.subscriptions[-1].last_run_status, "none")
        page = self.renderer().render_pages(snapshot)[0]
        self.assertIn("FAIL!", page.text)

    def test_empty_and_overflow_pages_are_explicit(self) -> None:
        empty = RedditSubscriptionsDashboard().normalize(self.raw(0), dt.datetime(2026, 7, 14, 3, tzinfo=UTC))
        self.assertIn("NO SUBSCRIPTIONS", self.renderer().render_pages(empty)[0].text)
        overflow = RedditSubscriptionsDashboard().normalize(self.raw(25), dt.datetime(2026, 7, 14, 3, tzinfo=UTC))
        pages = self.renderer(maximum=24).render_pages(overflow)
        self.assertEqual(len(pages), 2)
        self.assertTrue(all("+1 HIDDEN" in page.text for page in pages))

    def test_source_names_are_sanitized_and_clipped_to_exact_width(self) -> None:
        raw = self.raw(1)
        subscriptions = raw["subscriptions"]
        assert isinstance(subscriptions, list)
        subscriptions[0]["source_key"] = "很长的中文社区名称\twith-control-and-extra-text"
        snapshot = RedditSubscriptionsDashboard().normalize(raw, dt.datetime(2026, 7, 14, 3, tzinfo=UTC))
        page = self.renderer().render_pages(snapshot)[0]
        self.assertNotIn("\t", page.text)
        data_line = page.text.splitlines()[4]
        self.assertEqual(self.renderer()._width(data_line), self.renderer()._table_width())
