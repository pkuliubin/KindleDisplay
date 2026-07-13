#!/usr/bin/env python3
"""Local development preview for the Codex-to-Kindle data pipeline."""

from __future__ import annotations

import argparse
import datetime as dt
import json

from kindle_display import CodexLocalSource, CodexStatusDashboard, KindleTextRenderer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--max-projects", type=int, default=3)
    parser.add_argument("--max-sessions-per-project", type=int, default=3)
    parser.add_argument("--width", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--layout", action="store_true", help="emit FBInk layout blocks")
    args = parser.parse_args()
    session_date = dt.date.fromisoformat(args.date)

    snapshot = CodexStatusDashboard(
        CodexLocalSource(),
        max_projects=args.max_projects,
        max_sessions_per_project=args.max_sessions_per_project,
    ).collect(session_date)
    if args.json:
        print(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2))
    elif args.layout:
        print(KindleTextRenderer(args.width).render_layout(snapshot), end="")
    else:
        print(KindleTextRenderer(args.width).render(snapshot), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
