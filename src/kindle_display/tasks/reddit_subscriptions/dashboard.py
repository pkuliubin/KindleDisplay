from __future__ import annotations

import datetime as dt

from .models import RedditSubscription, RedditSubscriptionsSnapshot


class RedditSubscriptionsDashboard:
    def normalize(self, raw: object, now: dt.datetime) -> RedditSubscriptionsSnapshot:
        if not isinstance(raw, dict):
            raise ValueError("Reddit status root must be an object")
        generated_at = self._timestamp(raw.get("generated_at"), "generated_at")
        summary = raw.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("summary must be an object")
        records = raw.get("subscriptions")
        if not isinstance(records, list):
            raise ValueError("subscriptions must be an array")

        subscriptions = tuple(self._subscription(item) for item in records)
        sorted_subscriptions = tuple(sorted(subscriptions, key=lambda item: self._sort_key(item, now)))
        return RedditSubscriptionsSnapshot(
            generated_at=generated_at,
            subscription_count=self._integer(summary.get("subscription_count", len(subscriptions))),
            enabled_subscription_count=self._integer(
                summary.get("enabled_subscription_count", sum(item.enabled for item in subscriptions))
            ),
            due_subscription_count=self._integer(
                summary.get("due_subscription_count", sum(self._is_due(item, now) for item in subscriptions))
            ),
            active_task_count=self._integer(summary.get("active_task_count", 0)),
            subscribed_community_post_count=self._integer(summary.get("subscribed_community_post_count", 0)),
            subscriptions=sorted_subscriptions,
        )

    def _subscription(self, raw: object) -> RedditSubscription:
        if not isinstance(raw, dict):
            raise ValueError("subscription item must be an object")
        last_run = raw.get("last_run")
        if last_run is not None and not isinstance(last_run, dict):
            raise ValueError("subscription.last_run must be an object or null")
        last_run = last_run or {}
        return RedditSubscription(
            subscription_id=str(raw.get("subscription_id") or "unknown"),
            source_key=self._clean_text(raw.get("source_key") or "unknown"),
            enabled=bool(raw.get("enabled", False)),
            interval_seconds=self._integer(raw.get("interval_seconds", 0)),
            next_run_at=self._optional_timestamp(raw.get("next_run_at"), "next_run_at"),
            last_successful_run_at=self._optional_timestamp(
                raw.get("last_successful_run_at"), "last_successful_run_at"
            ),
            last_run_status=str(last_run.get("status") or "none").lower(),
            new_document_count=self._integer(last_run.get("new_document_count", 0)),
            updated_document_count=self._integer(last_run.get("updated_document_count", 0)),
            failed_item_count=self._integer(last_run.get("failed_item_count", 0)),
            cumulative_post_count=self._integer(raw.get("cumulative_post_count", 0)),
            error=self._clean_text(last_run.get("error")) if last_run.get("error") else None,
        )

    def _sort_key(self, item: RedditSubscription, now: dt.datetime) -> tuple[object, ...]:
        status_rank = {
            "failed": 0,
            "partial": 1,
            "running": 2,
        }.get(item.last_run_status, 4)
        due_rank = 0 if self._is_due(item, now) else 1
        successful = item.last_successful_run_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        return (0 if item.has_error else 1, status_rank, due_rank, successful, item.source_key.lower())

    @staticmethod
    def _is_due(item: RedditSubscription, now: dt.datetime) -> bool:
        return bool(item.enabled and item.next_run_at and item.next_run_at <= now and item.last_run_status != "running")

    @staticmethod
    def _timestamp(value: object, label: str) -> dt.datetime:
        parsed = RedditSubscriptionsDashboard._optional_timestamp(value, label)
        if parsed is None:
            raise ValueError(f"{label} is required")
        return parsed

    @staticmethod
    def _optional_timestamp(value: object, label: str) -> dt.datetime | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise ValueError(f"{label} must be an ISO timestamp")
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO timestamp") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label} must include a timezone")
        return parsed

    @staticmethod
    def _integer(value: object) -> int:
        if isinstance(value, bool):
            raise ValueError("boolean is not a valid integer")
        if isinstance(value, int):
            return max(0, value)
        if not isinstance(value, str):
            raise ValueError(f"invalid integer value: {value!r}")
        try:
            parsed = int(value)
        except ValueError as error:
            raise ValueError(f"invalid integer value: {value!r}") from error
        return max(0, parsed)

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join("".join(char if char.isprintable() else " " for char in str(value)).split())
