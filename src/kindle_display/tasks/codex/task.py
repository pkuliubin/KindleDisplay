from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

from kindle_display.dashboards.codex_status import CodexStatusDashboard
from kindle_display.renderers.kindle_text import KindleTextRenderer
from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy, TaskBuildResult


class CodexDashboardTask:
    cancel_on_timeout = False
    timezone = ZoneInfo("Asia/Shanghai")

    def __init__(
        self,
        task_id: str,
        dashboard: CodexStatusDashboard,
        renderer: KindleTextRenderer,
        collection_policy: CollectionPolicy,
        display_policy: DisplayPolicy,
    ) -> None:
        self.task_id = task_id
        self.dashboard = dashboard
        self.renderer = renderer
        self.collection_policy = collection_policy
        self.display_policy = display_policy

    async def build_pages(self, now: dt.datetime) -> TaskBuildResult:
        session_date = now.astimezone(self.timezone).date()
        snapshot = await asyncio.to_thread(self.dashboard.collect, session_date, now)
        page = self.renderer.render_page(snapshot)
        if page.page_id != f"{self.task_id}:0":
            page = type(page)(
                page_id=f"{self.task_id}:0",
                text=page.text,
                font_role=page.font_role,
                font_px=page.font_px,
                top=page.top,
                left=page.left,
                right=page.right,
                bottom=page.bottom,
            )
        return TaskBuildResult(source_generated_at=snapshot.generated_at, pages=(page,))
