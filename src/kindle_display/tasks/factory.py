from __future__ import annotations

from kindle_display.dashboards.codex_status import CodexStatusDashboard
from kindle_display.renderers.kindle_text import KindleTextRenderer
from kindle_display.runtime.config import AppConfig, TaskConfig
from kindle_display.sources.codex_local import CodexLocalSource
from kindle_display.sources.command_json import CommandJsonSource
from kindle_display.tasks.base import DashboardTask
from kindle_display.tasks.codex import CodexDashboardTask
from kindle_display.tasks.reddit_subscriptions import RedditSubscriptionsTask
from kindle_display.tasks.reddit_subscriptions.dashboard import RedditSubscriptionsDashboard
from kindle_display.tasks.reddit_subscriptions.renderer import RedditSubscriptionsRenderer


def build_tasks(config: AppConfig) -> tuple[DashboardTask, ...]:
    return tuple(build_task(task) for task in config.tasks if task.enabled)


def build_task(config: TaskConfig) -> DashboardTask:
    if config.kind == "codex":
        max_projects = _positive_option(config, "max_projects", 3)
        max_sessions = _positive_option(config, "max_sessions_per_project", 3)
        return CodexDashboardTask(
            config.task_id,
            CodexStatusDashboard(
                CodexLocalSource(),
                max_projects=max_projects,
                max_sessions_per_project=max_sessions,
            ),
            KindleTextRenderer(),
            config.collection,
            config.display,
        )
    if config.kind == "reddit_subscriptions":
        if config.source is None:
            raise ValueError(f"{config.task_id} requires a command source")
        rows = _positive_option(config, "rows_per_page", 6)
        maximum = _positive_option(config, "max_subscriptions", rows * config.display.max_pages)
        timezone = str(config.options.get("timezone", "Asia/Shanghai"))
        return RedditSubscriptionsTask(
            config.task_id,
            CommandJsonSource(config.source.cwd, config.source.argv, config.source.max_stdout_bytes),
            RedditSubscriptionsDashboard(),
            RedditSubscriptionsRenderer(config.task_id, rows, maximum, timezone),
            config.collection,
            config.display,
        )
    raise ValueError(f"unsupported task kind: {config.kind}")


def _positive_option(config: TaskConfig, name: str, default: int) -> int:
    value = config.options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{config.task_id}.options.{name} must be a positive integer")
    return value
