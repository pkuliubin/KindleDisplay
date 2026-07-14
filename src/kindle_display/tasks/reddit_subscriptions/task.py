from __future__ import annotations

import datetime as dt

from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy, TaskBuildResult
from kindle_display.sources.command_json import CommandJsonSource

from .dashboard import RedditSubscriptionsDashboard
from .renderer import RedditSubscriptionsRenderer


class RedditSubscriptionsTask:
    cancel_on_timeout = True

    def __init__(
        self,
        task_id: str,
        source: CommandJsonSource,
        dashboard: RedditSubscriptionsDashboard,
        renderer: RedditSubscriptionsRenderer,
        collection_policy: CollectionPolicy,
        display_policy: DisplayPolicy,
    ) -> None:
        self.task_id = task_id
        self.source = source
        self.dashboard = dashboard
        self.renderer = renderer
        self.collection_policy = collection_policy
        self.display_policy = display_policy

    async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
        raw = await self.source.collect()
        snapshot = self.dashboard.normalize(raw, now)
        return TaskBuildResult(snapshot.generated_at, self.renderer.render_pages(snapshot))
