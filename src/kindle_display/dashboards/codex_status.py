from __future__ import annotations

import datetime as dt
from collections import defaultdict

from kindle_display.models import CodexStatusSnapshot, ProjectSnapshot
from kindle_display.sources.codex_local import CodexLocalSource


class CodexStatusDashboard:
    """Select and group Codex sessions without making any display decisions."""

    def __init__(self, source: CodexLocalSource) -> None:
        self.source = source

    def collect(self, session_date: dt.date, now: dt.datetime | None = None) -> CodexStatusSnapshot:
        now = now or dt.datetime.now(dt.timezone.utc)
        collection = self.source.collect(session_date, now)
        grouped = defaultdict(list)
        for session in collection.sessions:
            grouped[session.cwd].append(session)
        projects = tuple(
            ProjectSnapshot(
                name=project_sessions[0].project_name,
                cwd=cwd,
                sessions=tuple(project_sessions),
            )
            for cwd, project_sessions in grouped.items()
        )
        return CodexStatusSnapshot(
            generated_at=now,
            session_date=session_date,
            projects=projects,
            daily_model_tokens=collection.daily_model_tokens,
        )
