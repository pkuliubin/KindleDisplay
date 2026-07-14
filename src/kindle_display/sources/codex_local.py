from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from kindle_display.models import (
    CodexCollectionSnapshot,
    ModelTokenUsage,
    SessionMetrics,
    SessionSnapshot,
)


class CodexLocalSource:
    """Read local Codex thread metadata and append-only rollout event logs."""

    DAILY_TIMEZONE = ZoneInfo("Asia/Shanghai")

    def __init__(self, codex_home: Path | None = None, stale_minutes: int = 5) -> None:
        self.codex_home = codex_home or Path.home() / ".codex"
        self.stale_minutes = stale_minutes

    def collect(self, session_date: dt.date, now: dt.datetime | None = None) -> CodexCollectionSnapshot:
        now = now or dt.datetime.now(dt.timezone.utc)
        threads = self._load_threads()
        sessions: list[SessionSnapshot] = []
        daily_model_tokens: Counter[str] = Counter()

        for path in self._rollouts_updated_on(session_date):
            session, model_tokens = self._read_rollout(path, threads, now, session_date)
            daily_model_tokens.update(model_tokens)
            if session is not None:
                sessions.append(session)

        return CodexCollectionSnapshot(
            sessions=tuple(sorted(sessions, key=lambda session: session.last_event_at, reverse=True)),
            daily_model_tokens=tuple(
                ModelTokenUsage(model=model, today_tokens=tokens)
                for model, tokens in sorted(daily_model_tokens.items(), key=lambda item: (-item[1], item[0]))
            ),
        )

    def _rollouts_updated_on(self, session_date: dt.date) -> list[Path]:
        """Find logs by append time, not by their original creation-date directory."""
        sessions_root = self.codex_home / "sessions"
        if not sessions_root.exists():
            return []
        candidates: list[Path] = []
        for path in sessions_root.rglob("rollout-*.jsonl"):
            try:
                modified_on = dt.datetime.fromtimestamp(path.stat().st_mtime, self.DAILY_TIMEZONE).date()
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

    def _read_rollout(
        self, path: Path, threads: dict[str, dict[str, Any]], now: dt.datetime, session_date: dt.date
    ) -> tuple[SessionSnapshot | None, Counter[str]]:
        session_id = path.stem[-36:]
        metadata: dict[str, Any] = {}
        latest_event_at: dt.datetime | None = None
        latest_token: dict[str, Any] | None = None
        latest_lifecycle: str | None = None
        current_model = "unknown"
        latest_model = "unknown"
        previous_total: int | None = None
        today_tokens = 0
        daily_model_tokens: Counter[str] = Counter()

        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # An active rollout may end in a partial append.
                    if not isinstance(event, dict):
                        continue
                    timestamp = self._parse_timestamp(event.get("timestamp"))
                    if timestamp is not None:
                        latest_event_at = timestamp
                    payload = event.get("payload")
                    if not isinstance(payload, dict):
                        continue

                    if event.get("type") == "session_meta":
                        metadata = payload
                        continue

                    model = self._model_from_event(event, payload)
                    if model:
                        current_model = model
                        latest_model = model

                    if event.get("type") != "event_msg":
                        continue
                    event_type = payload.get("type")
                    if event_type in {"task_started", "task_complete", "turn_aborted"}:
                        latest_lifecycle = str(event_type)
                    if event_type != "token_count" or timestamp is None:
                        continue

                    info = payload.get("info")
                    if not isinstance(info, dict):
                        continue
                    try:
                        metrics = self._metrics_from_token_event(info, today_tokens=0)
                    except (KeyError, TypeError, ValueError, ZeroDivisionError):
                        continue

                    current_total = metrics.total_tokens
                    delta = current_total if previous_total is None else current_total - previous_total
                    # A reset or corrupted event starts a fresh cumulative baseline.
                    if delta >= 0 and timestamp.astimezone(self.DAILY_TIMEZONE).date() == session_date:
                        today_tokens += delta
                        daily_model_tokens[current_model] += delta
                    previous_total = current_total
                    latest_token = info
        except OSError:
            return None, Counter()

        if not metadata or latest_event_at is None or latest_token is None:
            return None, daily_model_tokens
        if latest_event_at.astimezone(self.DAILY_TIMEZONE).date() != session_date:
            return None, daily_model_tokens

        session_id = str(metadata.get("session_id") or metadata.get("id") or session_id)
        thread = threads.get(session_id, {})
        try:
            metrics = self._metrics_from_token_event(latest_token, today_tokens=today_tokens)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None, daily_model_tokens
        cwd = str(thread.get("cwd") or metadata.get("cwd") or "unknown")
        model = latest_model if latest_model != "unknown" else str(thread.get("model") or "unknown")
        return (
            SessionSnapshot(
                id=session_id,
                project_name=Path(cwd).name,
                cwd=cwd,
                title=str(thread.get("title") or "untitled session"),
                model=model,
                state=self._state(latest_lifecycle, latest_event_at, now),
                last_event_at=latest_event_at,
                metrics=metrics,
            ),
            daily_model_tokens,
        )

    @staticmethod
    def _model_from_event(event: dict[str, Any], payload: dict[str, Any]) -> str | None:
        if event.get("type") == "turn_context":
            model = payload.get("model")
            return str(model) if model else None
        if event.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
            model = payload.get("thread_settings", {}).get("model")
            return str(model) if model else None
        return None

    @staticmethod
    def _parse_timestamp(value: str | None) -> dt.datetime | None:
        if not value:
            return None
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _metrics_from_token_event(info: dict[str, Any], *, today_tokens: int) -> SessionMetrics:
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
            today_tokens=today_tokens,
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
