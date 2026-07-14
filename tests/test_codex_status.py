from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kindle_display import CodexLocalSource, CodexStatusDashboard, KindleTextRenderer


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
            snapshot = CodexStatusDashboard(CodexLocalSource(home), max_projects=2, max_sessions_per_project=2).collect(dt.date(2026, 7, 13), now)

        session = snapshot.projects[0].sessions[0]
        self.assertEqual(session.state, "RUN")
        self.assertEqual(session.metrics.context_percent, 20)
        self.assertEqual(session.metrics.cache_total_percent, 80)
        self.assertEqual(session.metrics.cache_last_percent, 50)
        self.assertIn("26\t20\t20\t15\tttf_page\tCODEX STATUS", KindleTextRenderer().render_layout(snapshot))
        rendered = KindleTextRenderer().render(snapshot)
        self.assertIn("KindleDisplay [1]", rendered)
        self.assertIn("wiki [RUN]", rendered)
        layout = KindleTextRenderer().render_layout(snapshot)
        self.assertIn("KindleDisplay", layout)
        self.assertIn("> 阅读 wiki", layout)
        self.assertIn("gpt-test", layout)
        self.assertIn("阅读 wiki", layout)
        self.assertEqual(KindleTextRenderer()._clip("123456789", 8), "1234567.")
        self.assertEqual(KindleTextRenderer()._clip_title("这篇文章讲了什么", 12), "这篇文章讲..")
        self.assertEqual(KindleTextRenderer()._width(KindleTextRenderer()._clip_title("这篇文章讲了什么", 12)), 12)
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
            sessions = CodexLocalSource(home).collect(dt.date(2026, 7, 14), now)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "session-old")
        self.assertEqual(sessions[0].project_name, "ResumedProject")
        self.assertEqual(sessions[0].state, "RUN")
