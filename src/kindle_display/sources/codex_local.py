from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from kindle_display.models import SessionMetrics, SessionSnapshot


class CodexLocalSource:
    """Read local Codex thread metadata and the append-only rollout event logs."""

    TAIL_READ_BYTES = 512 * 1024

    def __init__(self, codex_home: Path | None = None, stale_minutes: int = 5) -> None:
        self.codex_home = codex_home or Path.home() / ".codex"
        self.stale_minutes = stale_minutes

    def collect(self, session_date: dt.date, now: dt.datetime | None = None) -> list[SessionSnapshot]:
        now = now or dt.datetime.now(dt.timezone.utc)
        threads = self._load_threads()
        sessions = [
            session
            for path in self._rollouts_updated_on(session_date)
            if (session := self._read_session(path, threads, now, session_date)) is not None
        ]
        return sorted(sessions, key=lambda session: session.last_event_at, reverse=True)

    def _rollouts_updated_on(self, session_date: dt.date) -> list[Path]:
        """Find logs by append time, not by their original creation-date directory."""
        sessions_root = self.codex_home / "sessions"
        if not sessions_root.exists():
            return []
        candidates: list[Path] = []
        for path in sessions_root.rglob("rollout-*.jsonl"):
            try:
                modified_on = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().date()
            except OSError:
                continue
            if modified_on == session_date:
                candidates.append(path)
        return candidates

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
        self, path: Path, threads: dict[str, dict[str, Any]], now: dt.datetime, session_date: dt.date
    ) -> SessionSnapshot | None:
        session_id = path.stem[-36:]
        thread = threads.get(session_id, {})
        metadata: dict[str, Any] | None = None
        latest_event_at: dt.datetime | None = None
        latest_token: dict[str, Any] | None = None
        latest_lifecycle: str | None = None

        for event in self._tail_events(path):
            timestamp = self._parse_timestamp(event.get("timestamp"))
            if timestamp and latest_event_at is None:
                latest_event_at = timestamp
            payload = event.get("payload", {})
            if event.get("type") == "session_meta":
                metadata = payload
            if event.get("type") != "event_msg":
                continue
            event_type = payload.get("type")
            if event_type == "token_count" and latest_token is None:
                latest_token = payload.get("info")
            elif event_type in {"task_started", "task_complete", "turn_aborted"} and latest_lifecycle is None:
                latest_lifecycle = event_type

            if thread and latest_event_at and latest_token and latest_lifecycle:
                break

        if metadata:
            session_id = str(metadata.get("session_id") or metadata.get("id") or session_id)
            thread = threads.get(session_id, thread)

        # A tail read is sufficient for normal active threads. Older or malformed
        # logs fall back to the complete parser to preserve the original behavior.
        if not latest_event_at or not latest_token or not latest_lifecycle or (not thread and not metadata):
            return self._read_session_fully(path, threads, now, session_date)

        return self._session_snapshot(
            session_id=session_id,
            thread=thread,
            metadata=metadata or {},
            latest_event_at=latest_event_at,
            latest_token=latest_token,
            lifecycle=latest_lifecycle,
            now=now,
            session_date=session_date,
        )

    def _read_session_fully(
        self, path: Path, threads: dict[str, dict[str, Any]], now: dt.datetime, session_date: dt.date
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
        session_id = str(metadata.get("session_id") or metadata.get("id") or path.stem[-36:])
        return self._session_snapshot(
            session_id=session_id,
            thread=threads.get(session_id, {}),
            metadata=metadata,
            latest_event_at=latest_event_at,
            latest_token=latest_token,
            lifecycle=lifecycle[-1] if lifecycle else None,
            now=now,
            session_date=session_date,
        )

    def _session_snapshot(
        self,
        *,
        session_id: str,
        thread: dict[str, Any],
        metadata: dict[str, Any],
        latest_event_at: dt.datetime,
        latest_token: dict[str, Any],
        lifecycle: str | None,
        now: dt.datetime,
        session_date: dt.date,
    ) -> SessionSnapshot | None:
        if latest_event_at.astimezone().date() != session_date:
            return None
        try:
            metrics = self._metrics_from_token_event(latest_token)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None

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

    def _tail_events(self, path: Path) -> list[dict[str, Any]]:
        try:
            with path.open("rb") as source:
                source.seek(0, 2)
                size = source.tell()
                source.seek(max(0, size - self.TAIL_READ_BYTES))
                chunk = source.read()
        except OSError:
            return []

        # Ignore a partial first line when the tail begins mid-event.
        if size > self.TAIL_READ_BYTES:
            _, _, chunk = chunk.partition(b"\n")
        events: list[dict[str, Any]] = []
        for line in reversed(chunk.splitlines()):
            try:
                event = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

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

    def _state(self, last: str | None, latest: dt.datetime, now: dt.datetime) -> str:
        if last == "task_started":
            if now - latest > dt.timedelta(minutes=self.stale_minutes):
                return "STAL"
            return "RUN"
        if last == "turn_aborted":
            return "ABRT"
        if last == "task_complete":
            return "DONE"
        return "IDLE"
