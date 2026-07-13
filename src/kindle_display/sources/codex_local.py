from __future__ import annotations

import datetime as dt
import glob
import json
import sqlite3
from pathlib import Path
from typing import Any

from kindle_display.models import SessionMetrics, SessionSnapshot


class CodexLocalSource:
    """Read local Codex thread metadata and the append-only rollout event logs."""

    def __init__(self, codex_home: Path | None = None, stale_minutes: int = 5) -> None:
        self.codex_home = codex_home or Path.home() / ".codex"
        self.stale_minutes = stale_minutes

    def collect(self, session_date: dt.date, now: dt.datetime | None = None) -> list[SessionSnapshot]:
        now = now or dt.datetime.now(dt.timezone.utc)
        threads = self._load_threads()
        session_dir = self.codex_home / "sessions" / session_date.strftime("%Y/%m/%d")
        sessions = [
            session
            for path in glob.glob(str(session_dir / "rollout-*.jsonl"))
            if (session := self._read_session(Path(path), threads, now)) is not None
        ]
        return sorted(sessions, key=lambda session: session.last_event_at, reverse=True)

    def _load_threads(self) -> dict[str, dict[str, Any]]:
        database = self.codex_home / "state_5.sqlite"
        if not database.exists():
            return {}
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT id, cwd, title, model FROM threads").fetchall()
        except sqlite3.Error:
            return {}
        finally:
            if "connection" in locals():
                connection.close()
        return {row["id"]: dict(row) for row in rows}

    def _read_session(
        self, path: Path, threads: dict[str, dict[str, Any]], now: dt.datetime
    ) -> SessionSnapshot | None:
        metadata: dict[str, Any] | None = None
        latest_event_at: dt.datetime | None = None
        latest_token: dict[str, Any] | None = None
        lifecycle: list[str] = []

        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # The active session can be read mid-append.
                    timestamp = self._parse_timestamp(event.get("timestamp"))
                    if timestamp:
                        latest_event_at = timestamp
                    payload = event.get("payload", {})
                    if event.get("type") == "session_meta":
                        metadata = payload
                    if event.get("type") != "event_msg":
                        continue
                    event_type = payload.get("type")
                    if event_type == "token_count":
                        latest_token = payload.get("info")
                    elif event_type in {"task_started", "task_complete", "turn_aborted"}:
                        lifecycle.append(event_type)
        except OSError:
            return None

        if not metadata or not latest_event_at or not latest_token:
            return None
        try:
            metrics = self._metrics_from_token_event(latest_token)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

        session_id = str(metadata.get("session_id") or metadata.get("id") or "")
        thread = threads.get(session_id, {})
        cwd = str(thread.get("cwd") or metadata.get("cwd") or "unknown")
        return SessionSnapshot(
            id=session_id,
            project_name=Path(cwd).name,
            cwd=cwd,
            title=str(thread.get("title") or "untitled session"),
            model=str(thread.get("model") or "unknown model"),
            state=self._state(lifecycle, latest_event_at, now),
            last_event_at=latest_event_at,
            metrics=metrics,
        )

    @staticmethod
    def _parse_timestamp(value: str | None) -> dt.datetime | None:
        if not value:
            return None
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _metrics_from_token_event(info: dict[str, Any]) -> SessionMetrics:
        last_usage = info["last_token_usage"]
        total_usage = info["total_token_usage"]
        context_used = int(last_usage["input_tokens"])
        total_input = int(total_usage["input_tokens"])
        return SessionMetrics(
            context_used_tokens=context_used,
            context_window_tokens=int(info["model_context_window"]),
            cache_total_percent=round(100 * int(total_usage["cached_input_tokens"]) / total_input),
            cache_last_percent=round(100 * int(last_usage["cached_input_tokens"]) / context_used)
            if context_used
            else 0,
            total_tokens=int(total_usage["total_tokens"]),
        )

    def _state(self, lifecycle: list[str], latest: dt.datetime, now: dt.datetime) -> str:
        last = lifecycle[-1] if lifecycle else None
        if last == "task_started":
            if now - latest > dt.timedelta(minutes=self.stale_minutes):
                return "STAL"
            return "RUN"
        if last == "turn_aborted":
            return "ABRT"
        if last == "task_complete":
            return "DONE"
        return "IDLE"
