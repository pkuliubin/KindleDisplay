from __future__ import annotations

import datetime as dt
import json
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
            (log_dir / "rollout-test.jsonl").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

            now = dt.datetime(2026, 7, 13, 6, 3, tzinfo=dt.timezone.utc)
            snapshot = CodexStatusDashboard(CodexLocalSource(home), max_projects=2, max_sessions_per_project=2).collect(dt.date(2026, 7, 13), now)

        session = snapshot.projects[0].sessions[0]
        self.assertEqual(session.state, "RUN")
        self.assertEqual(session.metrics.context_percent, 20)
        self.assertEqual(session.metrics.cache_total_percent, 80)
        self.assertEqual(session.metrics.cache_last_percent, 50)
        self.assertIn("\t1R\n", KindleTextRenderer().render_layout(snapshot))
        rendered = KindleTextRenderer().render(snapshot)
        self.assertIn("KindleDisplay [1]", rendered)
        self.assertIn("wiki [RUN]", rendered)
        rendered.encode("ascii")
        layout = KindleTextRenderer().render_layout(snapshot)
        self.assertIn("3\t1\t145\t0\tKINDLE DISPLAY", layout)
        self.assertIn("wiki     gpt-test       R  20%      1k   50/80", layout)
        layout.encode("ascii")
        self.assertEqual(snapshot.as_dict()["projects"][0]["sessions"][0]["context"]["percent"], 20)
