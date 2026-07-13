from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class SessionMetrics:
    context_used_tokens: int
    context_window_tokens: int
    cache_total_percent: int
    cache_last_percent: int
    total_tokens: int

    @property
    def context_percent(self) -> int:
        return round(100 * self.context_used_tokens / self.context_window_tokens)


@dataclass(frozen=True)
class SessionSnapshot:
    id: str
    project_name: str
    cwd: str
    title: str
    model: str
    state: str
    last_event_at: datetime
    metrics: SessionMetrics


@dataclass(frozen=True)
class ProjectSnapshot:
    name: str
    cwd: str
    sessions: tuple[SessionSnapshot, ...]

    @property
    def running_count(self) -> int:
        return sum(session.state == "RUN" for session in self.sessions)


@dataclass(frozen=True)
class CodexStatusSnapshot:
    generated_at: datetime
    session_date: date
    projects: tuple[ProjectSnapshot, ...]

    @property
    def session_count(self) -> int:
        return sum(len(project.sessions) for project in self.projects)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "session_date": self.session_date.isoformat(),
            "project_count": len(self.projects),
            "session_count": self.session_count,
            "projects": [
                {
                    "name": project.name,
                    "cwd": project.cwd,
                    "session_count": len(project.sessions),
                    "running_count": project.running_count,
                    "sessions": [
                        {
                            "id": session.id,
                            "title": session.title,
                            "model": session.model,
                            "state": session.state,
                            "last_event_at": session.last_event_at.isoformat(),
                            "context": {
                                "used_tokens": session.metrics.context_used_tokens,
                                "window_tokens": session.metrics.context_window_tokens,
                                "percent": session.metrics.context_percent,
                            },
                            "cache": {
                                "total_percent": session.metrics.cache_total_percent,
                                "last_percent": session.metrics.cache_last_percent,
                            },
                            "total_tokens": session.metrics.total_tokens,
                        }
                        for session in project.sessions
                    ],
                }
                for project in self.projects
            ],
        }
