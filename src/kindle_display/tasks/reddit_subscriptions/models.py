from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class RedditSubscription:
    subscription_id: str
    source_key: str
    enabled: bool
    interval_seconds: int
    next_run_at: dt.datetime | None
    last_successful_run_at: dt.datetime | None
    last_run_status: str
    new_document_count: int
    updated_document_count: int
    failed_item_count: int
    cumulative_post_count: int
    error: str | None

    @property
    def has_error(self) -> bool:
        return bool(self.error) or self.failed_item_count > 0


@dataclass(frozen=True)
class RedditSubscriptionsSnapshot:
    generated_at: dt.datetime
    subscription_count: int
    enabled_subscription_count: int
    due_subscription_count: int
    active_task_count: int
    subscribed_community_post_count: int
    subscriptions: tuple[RedditSubscription, ...]
