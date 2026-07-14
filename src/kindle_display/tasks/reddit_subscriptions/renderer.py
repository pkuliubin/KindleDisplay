from __future__ import annotations

import math
import unicodedata
from zoneinfo import ZoneInfo

from kindle_display.runtime.models import PageSpec

from .models import RedditSubscription, RedditSubscriptionsSnapshot


class RedditSubscriptionsRenderer:
    TABLE_SPACE = "\u2007"
    SOURCE_WIDTH = 20
    RESULT_WIDTH = 6
    FREQUENCY_WIDTH = 5
    NEXT_WIDTH = 8
    LAST_WIDTH = 8
    CHANGE_WIDTH = 7
    TOTAL_WIDTH = 6

    def __init__(
        self,
        task_id: str,
        rows_per_page: int,
        max_subscriptions: int,
        timezone: str,
    ) -> None:
        self.task_id = task_id
        self.rows_per_page = rows_per_page
        self.max_subscriptions = max_subscriptions
        self.timezone = ZoneInfo(timezone)

    def render_pages(self, snapshot: RedditSubscriptionsSnapshot) -> tuple[PageSpec, ...]:
        displayed = snapshot.subscriptions[: self.max_subscriptions]
        hidden = max(0, len(snapshot.subscriptions) - len(displayed))
        page_count = max(1, math.ceil(len(displayed) / self.rows_per_page))
        pages: list[PageSpec] = []
        for page_index in range(page_count):
            start = page_index * self.rows_per_page
            rows = displayed[start : start + self.rows_per_page]
            lines = self._header(snapshot, page_index + 1, page_count, hidden)
            lines.extend(self._row(item) for item in rows)
            if not rows:
                lines.append("NO SUBSCRIPTIONS")
            pages.append(
                PageSpec(
                    page_id=f"{self.task_id}:{page_index}",
                    text="\n".join(lines),
                    font_role="cjk_mono",
                    font_px=26,
                    top=20,
                    left=20,
                    right=15,
                    bottom=20,
                )
            )
        return tuple(pages)

    def _header(
        self,
        snapshot: RedditSubscriptionsSnapshot,
        page_number: int,
        page_count: int,
        hidden: int,
    ) -> list[str]:
        generated = snapshot.generated_at.astimezone(self.timezone).strftime("%m-%d %H:%M")
        error_count = sum(item.has_error for item in snapshot.subscriptions)
        summary = (
            f"{snapshot.enabled_subscription_count} ON / {snapshot.active_task_count} ACTIVE / "
            f"{error_count} ERR / {self._number(snapshot.subscribed_community_post_count)} POSTS"
        )
        if hidden:
            summary += f" / +{hidden} HIDDEN"
        return [
            f"REDDIT SUBSCRIPTIONS / DATA {generated}  {page_number}/{page_count}",
            summary,
            self._row_values("SOURCE", "RESULT", "FREQ", "NEXT", "LAST", "N/U", "TOTAL"),
            "-" * self._table_width(),
        ]

    def _row(self, item: RedditSubscription) -> str:
        result = "OFF" if not item.enabled else self._result(item)
        last = "--"
        if item.last_successful_run_at is not None:
            last = item.last_successful_run_at.astimezone(self.timezone).strftime("%d-%H:%M")
        next_run = "--"
        if item.next_run_at is not None:
            next_run = item.next_run_at.astimezone(self.timezone).strftime("%d-%H:%M")
        changes = f"{item.new_document_count}/{item.updated_document_count}"
        return self._row_values(
            item.source_key,
            result,
            self._frequency(item.interval_seconds),
            next_run,
            last,
            changes,
            self._number(item.cumulative_post_count),
        )

    def _row_values(
        self,
        source: str,
        result: str,
        frequency: str,
        next_run: str,
        last: str,
        changes: str,
        total: str,
    ) -> str:
        values = (
            self._pad(self._clip(source, self.SOURCE_WIDTH), self.SOURCE_WIDTH),
            self._pad(self._clip(result, self.RESULT_WIDTH), self.RESULT_WIDTH),
            self._pad_left(frequency, self.FREQUENCY_WIDTH),
            self._pad_left(next_run, self.NEXT_WIDTH),
            self._pad_left(last, self.LAST_WIDTH),
            self._pad_left(changes, self.CHANGE_WIDTH),
            self._pad_left(total, self.TOTAL_WIDTH),
        )
        return self.TABLE_SPACE.join(values)

    @staticmethod
    def _result(item: RedditSubscription) -> str:
        label = {
            "completed": "DONE",
            "running": "RUN",
            "failed": "FAIL",
            "partial": "PART",
            "none": "NONE",
        }.get(item.last_run_status, "UNKN")
        if item.has_error and not label.endswith("!"):
            label += "!"
        return label

    def _clip(self, value: str, width: int) -> str:
        normalized = " ".join(value.split())
        if self._width(normalized) <= width:
            return normalized
        kept: list[str] = []
        used = 0
        for char in normalized:
            char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
            if used + char_width > width - 1:
                break
            kept.append(char)
            used += char_width
        clipped = "".join(kept) + "."
        return clipped + "." * (width - self._width(clipped))

    def _pad(self, value: str, width: int) -> str:
        return value + self.TABLE_SPACE * max(0, width - self._width(value))

    def _pad_left(self, value: str, width: int) -> str:
        clipped = self._clip(value, width)
        return self.TABLE_SPACE * max(0, width - self._width(clipped)) + clipped

    def _table_width(self) -> int:
        return (
            self.SOURCE_WIDTH
            + self.RESULT_WIDTH
            + self.FREQUENCY_WIDTH
            + self.NEXT_WIDTH
            + self.LAST_WIDTH
            + self.CHANGE_WIDTH
            + self.TOTAL_WIDTH
            + 6
        )

    @staticmethod
    def _width(value: str) -> int:
        return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in value)

    @staticmethod
    def _number(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}k"
        return str(value)

    @staticmethod
    def _frequency(seconds: int) -> str:
        if seconds and seconds % 86400 == 0:
            return f"{seconds // 86400}d"
        if seconds and seconds % 3600 == 0:
            return f"{seconds // 3600}h"
        if seconds and seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"
