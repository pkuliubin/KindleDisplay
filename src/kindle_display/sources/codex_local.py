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
from kindle_display.sources.codex_pricing import CodexPricing


class CodexLocalSource:
    """Read local Codex thread metadata and append-only rollout event logs."""

    DAILY_TIMEZONE = ZoneInfo("Asia/Shanghai")

    def __init__(
        self, codex_home: Path | None = None, stale_minutes: int = 5, pricing_path: Path | None = None
    ) -> None:
        self.codex_home = codex_home or Path.home() / ".codex"
        self.stale_minutes = stale_minutes
        default_pricing = Path(__file__).resolve().parents[3] / "config" / "codex-pricing.toml"
        self.pricing = CodexPricing.from_toml(pricing_path or default_pricing)

    def collect(self, session_date: dt.date, now: dt.datetime | None = None) -> CodexCollectionSnapshot:
        now = now or dt.datetime.now(dt.timezone.utc)
        threads = self._load_threads()
        thread_names = self._load_thread_names()
        sessions: list[SessionSnapshot] = []
        daily_model_tokens: dict[str, Counter[str]] = {}

        for path in self._rollouts_updated_on(session_date):
            session, model_tokens = self._read_rollout(path, threads, thread_names, now, session_date)
            for model, usage in model_tokens.items():
                daily_model_tokens.setdefault(model, Counter()).update(usage)
            if session is not None:
                sessions.append(session)

        return CodexCollectionSnapshot(
            sessions=tuple(sorted(sessions, key=lambda session: session.last_event_at, reverse=True)),
            daily_model_tokens=tuple(
                ModelTokenUsage(
                    model=model,
                    today_tokens=usage["total_tokens"],
                    input_tokens=usage["input_tokens"],
                    cached_input_tokens=usage["cached_input_tokens"],
                    output_tokens=usage["output_tokens"],
                    estimated_cost_usd=self._estimate_cost(model, usage),
                )
                for model, usage in sorted(
                    daily_model_tokens.items(), key=lambda item: (-item[1]["total_tokens"], item[0])
                )
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

    def _load_thread_names(self) -> dict[str, str]:
        """Read the latest Desktop thread rename for each session ID."""
        path = self.codex_home / "session_index.jsonl"
        names: dict[str, str] = {}
        try:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    session_id = record.get("id")
                    thread_name = record.get("thread_name")
                    if isinstance(session_id, str) and isinstance(thread_name, str) and thread_name.strip():
                        names[session_id] = thread_name
        except OSError:
            return {}
        return names

    def _read_rollout(
        self,
        path: Path,
        threads: dict[str, dict[str, Any]],
        thread_names: dict[str, str],
        now: dt.datetime,
        session_date: dt.date,
    ) -> tuple[SessionSnapshot | None, dict[str, Counter[str]]]:
        session_id = path.stem[-36:]
        metadata: dict[str, Any] = {}
        latest_event_at: dt.datetime | None = None
        latest_token: dict[str, Any] | None = None
        latest_lifecycle: str | None = None
        current_model = "unknown"
        latest_model = "unknown"
        previous_usage: dict[str, int] | None = None
        today_tokens = 0
        daily_model_tokens: dict[str, Counter[str]] = {}

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
                        current_usage = self._total_usage_from_token_event(info)
                    except (KeyError, TypeError, ValueError):
                        continue

                    delta = (
                        current_usage
                        if previous_usage is None
                        else {field: current_usage[field] - previous_usage[field] for field in current_usage}
                    )
                    # A reset or corrupted event starts a fresh cumulative baseline.
                    if all(value >= 0 for value in delta.values()) and timestamp.astimezone(self.DAILY_TIMEZONE).date() == session_date:
                        today_tokens += delta["total_tokens"]
                        daily_model_tokens.setdefault(current_model, Counter()).update(delta)
                    previous_usage = current_usage
                    latest_token = info
        except OSError:
            return None, {}

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
        title = thread_names.get(session_id) or str(thread.get("title") or "untitled session")
        return (
            SessionSnapshot(
                id=session_id,
                project_name=Path(cwd).name,
                cwd=cwd,
                title=title,
                model=model,
                state=self._state(latest_lifecycle, latest_event_at, now),
                last_event_at=latest_event_at,
                metrics=metrics,
            ),
            daily_model_tokens,
        )

    def _estimate_cost(self, model: str, usage: Counter[str]):
        pricing = self.pricing.get(model)
        if pricing is None:
            return None
        return pricing.estimate_cost(
            input_tokens=usage["input_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            output_tokens=usage["output_tokens"],
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
    def _total_usage_from_token_event(info: dict[str, Any]) -> dict[str, int]:
        total_usage = info["total_token_usage"]
        input_tokens = int(total_usage["input_tokens"])
        total_tokens = int(total_usage["total_tokens"])
        output_tokens = int(total_usage.get("output_tokens", total_tokens - input_tokens))
        cached_input_tokens = int(total_usage["cached_input_tokens"])
        if cached_input_tokens > input_tokens or total_tokens != input_tokens + output_tokens:
            raise ValueError("invalid total token usage")
        return {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

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
