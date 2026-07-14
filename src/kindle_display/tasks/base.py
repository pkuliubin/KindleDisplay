from __future__ import annotations

import datetime as dt
from typing import Protocol

from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy, TaskBuildResult


class DashboardTask(Protocol):
    task_id: str
    collection_policy: CollectionPolicy
    display_policy: DisplayPolicy
    cancel_on_timeout: bool

    async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
        ...
