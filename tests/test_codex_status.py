from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from kindle_display import CodexLocalSource, CodexStatusDashboard, KindleTextRenderer
from kindle_display.models import (
    CodexCollectionSnapshot,
    CodexStatusSnapshot,
    ProjectSnapshot,
    SessionMetrics,
    SessionSnapshot,
)
from kindle_display.runtime.models import CollectionPolicy, DisplayPolicy
from kindle_display.tasks.codex import CodexDashboardTask


class CodexStatusTest(unittest.TestCase):
    def test_collects_and_renders_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            connection = sqlite3.connect(home / "state_5.sqlite")
            connection.execute("CREATE TABLE threads (id TEXT, cwd TEXT, title TEXT, model TEXT)")
            connection.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?)",
                ("session-1", "/work/KindleDisplay", "阅读 wiki", "gpt-test"),
            )
            connection.commit()
            connection.close()

            log_dir = home / "sessions/2026/07/13"
            log_dir.mkdir(parents=True)
            events = [
                {"timestamp": "2026-07-13T06:00:00Z", "type": "session_meta", "payload": {"session_id": "session-1", "cwd": "/work/KindleDisplay"}},
                {"timestamp": "2026-07-13T06:01:00Z", "type": "event_msg", "payload": {"type": "task_started"}},
                {"timestamp": "2026-07-13T06:02:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "total_tokens": 1010}, "last_token_usage": {"input_tokens": 200, "cached_input_tokens": 100, "total_tokens": 205}, "model_context_window": 1000}}},
            ]
            log_path = log_dir / "rollout-test.jsonl"
            log_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            timestamp = dt.datetime(2026, 7, 13, 6, 2, tzinfo=dt.timezone.utc).timestamp()
            os.utime(log_path, (timestamp, timestamp))

            now = dt.datetime(2026, 7, 13, 6, 3, tzinfo=dt.timezone.utc)
            snapshot = CodexStatusDashboard(CodexLocalSource(home)).collect(dt.date(2026, 7, 13), now)

        session = snapshot.projects[0].sessions[0]
        self.assertEqual(session.state, "RUN")
        self.assertEqual(session.metrics.context_percent, 20)
        self.assertEqual(session.metrics.cache_total_percent, 80)
        self.assertEqual(session.metrics.cache_last_percent, 50)
        self.assertIn("24\t20\t20\t15\tttf_page\tCODEX STATUS", KindleTextRenderer().render_layout(snapshot))
        rendered = KindleTextRenderer().render(snapshot)
        self.assertIn("KindleDisplay [1]", rendered)
        self.assertIn("wiki [R]", rendered)
        layout = KindleTextRenderer().render_layout(snapshot)
        self.assertIn("KindleDisplay", layout)
        self.assertIn("> 阅读 wiki", layout)
        self.assertIn("gpt-test", layout)
        self.assertIn("阅读 wiki", layout)
        self.assertIn("STA", layout)
        self.assertIn("1k/1k", layout)
        self.assertIn("unknown", layout)
        self.assertIn("1.0%", layout)
        self.assertNotIn("$", layout)
        page = KindleTextRenderer().render_page(snapshot)
        self.assertEqual(page.page_id, "codex:0")
        self.assertIn("\n", page.text)
        self.assertNotIn("\x1e", page.text)
        self.assertEqual(KindleTextRenderer()._clip("123456789", 8), "1234567.")
        self.assertEqual(KindleTextRenderer()._clip_title("这篇文章讲了什么", 12), "这篇文章讲..")
        self.assertEqual(KindleTextRenderer()._width(KindleTextRenderer()._clip_title("这篇文章讲了什么", 12)), 12)
        self.assertEqual(
            KindleTextRenderer()._display_title(
                "[$zyb-op](/Users/liubin/.codex/skills/zyb-op/SKILL.md)\n获取 Exception 日志",
                "session-1",
            ),
            "获取 Exception 日志",
        )
        self.assertEqual(snapshot.as_dict()["projects"][0]["sessions"][0]["context"]["percent"], 20)

    def test_collects_a_session_resumed_from_an_older_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            connection = sqlite3.connect(home / "state_5.sqlite")
            connection.execute("CREATE TABLE threads (id TEXT, cwd TEXT, title TEXT, model TEXT)")
            connection.execute(
                "INSERT INTO threads VALUES (?, ?, ?, ?)",
                ("session-old", "/work/ResumedProject", "旧 session 的后续请求", "gpt-test"),
            )
            connection.commit()
            connection.close()

            log_dir = home / "sessions/2026/07/03"
            log_dir.mkdir(parents=True)
            events = [
                {"timestamp": "2026-07-03T06:00:00Z", "type": "session_meta", "payload": {"session_id": "session-old", "cwd": "/work/ResumedProject"}},
                {"timestamp": "2026-07-03T06:01:00Z", "type": "event_msg", "payload": {"type": "task_complete"}},
                {"timestamp": "2026-07-14T06:01:00Z", "type": "event_msg", "payload": {"type": "task_started"}},
                {"timestamp": "2026-07-14T06:02:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "total_tokens": 1010}, "last_token_usage": {"input_tokens": 200, "cached_input_tokens": 100, "total_tokens": 205}, "model_context_window": 1000}}},
            ]
            log_path = log_dir / "rollout-test.jsonl"
            log_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            timestamp = dt.datetime(2026, 7, 14, 6, 2, tzinfo=dt.timezone.utc).timestamp()
            os.utime(log_path, (timestamp, timestamp))

            now = dt.datetime(2026, 7, 14, 6, 3, tzinfo=dt.timezone.utc)
            collection = CodexLocalSource(home).collect(dt.date(2026, 7, 14), now)

        self.assertEqual(len(collection.sessions), 1)
        self.assertEqual(collection.sessions[0].id, "session-old")
        self.assertEqual(collection.sessions[0].project_name, "ResumedProject")
        self.assertEqual(collection.sessions[0].state, "RUN")

    def test_attributes_cross_day_deltas_to_models_before_display_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            connection = sqlite3.connect(home / "state_5.sqlite")
            connection.execute("CREATE TABLE threads (id TEXT, cwd TEXT, title TEXT, model TEXT)")
            connection.executemany(
                "INSERT INTO threads VALUES (?, ?, ?, ?)",
                (
                    ("session-terra", "/work/TerraProject", "terra task", "gpt-5.6-terra"),
                    ("session-sol", "/work/SolProject", "sol task", "gpt-5.6-sol"),
                ),
            )
            connection.commit()
            connection.close()

            log_dir = home / "sessions/2026/07/13"
            log_dir.mkdir(parents=True)
            terra_events = [
                {"timestamp": "2026-07-13T15:50:00Z", "type": "session_meta", "payload": {"session_id": "session-terra", "cwd": "/work/TerraProject"}},
                {"timestamp": "2026-07-13T15:51:00Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}},
                self._token_event("2026-07-13T15:59:00Z", 100),
                {"timestamp": "2026-07-13T16:00:00Z", "type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_settings": {"model": "gpt-5.6-terra"}}},
                {"timestamp": "2026-07-13T16:00:01Z", "type": "event_msg", "payload": {"type": "task_started"}},
                self._token_event("2026-07-13T16:01:00Z", 300),
            ]
            sol_events = [
                {"timestamp": "2026-07-14T00:30:00Z", "type": "session_meta", "payload": {"session_id": "session-sol", "cwd": "/work/SolProject"}},
                {"timestamp": "2026-07-14T00:30:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                self._token_event("2026-07-14T00:31:00Z", 70),
            ]
            for name, events in (("rollout-terra.jsonl", terra_events), ("rollout-sol.jsonl", sol_events)):
                log_path = log_dir / name
                log_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
                timestamp = dt.datetime(2026, 7, 14, 1, tzinfo=dt.timezone.utc).timestamp()
                os.utime(log_path, (timestamp, timestamp))

            now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
            snapshot = CodexStatusDashboard(CodexLocalSource(home)).collect(
                dt.date(2026, 7, 14), now
            )

        self.assertEqual(snapshot.projects[0].name, "SolProject")
        self.assertEqual(snapshot.projects[0].sessions[0].metrics.today_tokens, 70)
        self.assertEqual(
            [(usage.model, usage.today_tokens) for usage in snapshot.daily_model_tokens],
            [("gpt-5.6-terra", 200), ("gpt-5.6-sol", 70)],
        )
        data = snapshot.as_dict()
        self.assertEqual(
            data["daily_model_tokens"][0],
            {
                "model": "gpt-5.6-terra",
                "today_tokens": 200,
                "input_tokens": 200,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "output_token_rate": 0.0,
                "estimated_cost_usd": 0.0005,
            },
        )
        layout = KindleTextRenderer().render_layout(snapshot)
        self.assertIn("gpt-5.6-terra", layout)
        self.assertIn("$0.0005", layout)
        self.assertIn("gpt-5.6-sol", layout)
        self.assertIn("$0.0006", layout)

    def test_dashboard_keeps_every_session_returned_for_today(self) -> None:
        now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
        sessions = tuple(
            self._session(project_index, session_index, now)
            for project_index in range(4)
            for session_index in range(4)
        )
        source = Mock()
        source.collect.return_value = CodexCollectionSnapshot(sessions=sessions, daily_model_tokens=())

        snapshot = CodexStatusDashboard(source).collect(dt.date(2026, 7, 14), now)

        self.assertEqual(len(snapshot.projects), 4)
        self.assertEqual(snapshot.session_count, 16)
        self.assertTrue(all(len(project.sessions) == 4 for project in snapshot.projects))

    def test_renderer_paginates_all_sessions_with_stable_page_ids(self) -> None:
        now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
        projects = tuple(
            ProjectSnapshot(
                name=f"project-{project_index}",
                cwd=f"/work/project-{project_index}",
                sessions=tuple(self._session(project_index, session_index, now) for session_index in range(4)),
            )
            for project_index in range(4)
        )
        snapshot = CodexStatusSnapshot(now, now.date(), projects, ())

        pages = KindleTextRenderer(max_pages=8).render_pages(snapshot)

        self.assertEqual([page.page_id for page in pages], ["codex:0", "codex:1"])
        rendered = "\n".join(page.text for page in pages)
        for project_index in range(4):
            for session_index in range(4):
                self.assertEqual(rendered.count(f"> p{project_index}-s{session_index}"), 1)

    def test_renderer_marks_sessions_beyond_the_page_budget(self) -> None:
        now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
        projects = tuple(
            ProjectSnapshot(
                name=f"project-{index}",
                cwd=f"/work/project-{index}",
                sessions=(self._session(index, 0, now),),
            )
            for index in range(36)
        )
        snapshot = CodexStatusSnapshot(now, now.date(), projects, ())

        pages = KindleTextRenderer(max_pages=8).render_pages(snapshot)

        self.assertEqual(len(pages), 8)
        self.assertIn("+4 SESSIONS HIDDEN", pages[-1].text)

    def test_renderer_keeps_a_large_project_together_until_a_page_break(self) -> None:
        now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
        project = ProjectSnapshot(
            name="large-project",
            cwd="/work/large-project",
            sessions=tuple(self._session(0, index, now) for index in range(14)),
        )
        snapshot = CodexStatusSnapshot(now, now.date(), (project,), ())

        pages = KindleTextRenderer(max_pages=8).render_pages(snapshot)

        self.assertEqual([page.page_id for page in pages], ["codex:0", "codex:1"])
        self.assertEqual(pages[0].text.count("\nlarge-project\n"), 1)
        self.assertIn("large-project (续)", pages[1].text)
        self.assertNotIn("\nlarge-project\n", pages[1].text)
        self.assertEqual(sum(page.text.count("> p0-s") for page in pages), 14)

    def test_codex_task_publishes_every_rendered_page(self) -> None:
        now = dt.datetime(2026, 7, 14, 2, tzinfo=dt.timezone.utc)
        projects = tuple(
            ProjectSnapshot(
                name=f"project-{project_index}",
                cwd=f"/work/project-{project_index}",
                sessions=tuple(self._session(project_index, session_index, now) for session_index in range(4)),
            )
            for project_index in range(4)
        )
        dashboard = Mock()
        dashboard.collect.return_value = CodexStatusSnapshot(now, now.date(), projects, ())
        task = CodexDashboardTask(
            "daily-codex",
            dashboard,
            KindleTextRenderer(max_pages=8),
            CollectionPolicy(60, 20),
            DisplayPolicy(120, 15, 8),
        )

        result = asyncio.run(task.build_pages(now))

        self.assertEqual(
            [page.page_id for page in result.pages],
            ["daily-codex:0", "daily-codex:1"],
        )

    @staticmethod
    def _session(project_index: int, session_index: int, now: dt.datetime) -> SessionSnapshot:
        return SessionSnapshot(
            id=f"session-{project_index}-{session_index}",
            project_name=f"project-{project_index}",
            cwd=f"/work/project-{project_index}",
            title=f"p{project_index}-s{session_index}",
            model="gpt-test",
            state="DONE",
            last_event_at=now,
            metrics=SessionMetrics(100, 1000, 50, 50, 100, 200),
        )

    @staticmethod
    def _token_event(timestamp: str, total_tokens: int) -> dict[str, object]:
        return {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total_tokens - 10,
                        "cached_input_tokens": 0,
                        "total_tokens": total_tokens,
                    },
                    "last_token_usage": {
                        "input_tokens": total_tokens - 10,
                        "cached_input_tokens": 0,
                        "total_tokens": total_tokens,
                    },
                    "model_context_window": 1000,
                },
            },
        }
