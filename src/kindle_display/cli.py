from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import asdict
from pathlib import Path

from kindle_display.devices.kindle_sink import KindleSink
from kindle_display.devices.layout_protocol import serialize_ttf_page
from kindle_display.runtime.config import AppConfig, load_config
from kindle_display.runtime.service import DashboardService
from kindle_display.tasks.factory import build_tasks


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPOSITORY_ROOT / "config" / "dashboard.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect and rotate Kindle dashboard pages")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("KINDLE_DISPLAY_CONFIG", DEFAULT_CONFIG)),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run collection and playback until stopped")
    subparsers.add_parser("validate", help="validate configuration and local device prerequisites")
    subparsers.add_parser("check", help="collect every task and validate pages without sending")

    once = subparsers.add_parser("once", help="collect all tasks and send one page")
    once.add_argument("--task")
    once.add_argument("--page", type=int, default=1)

    preview = subparsers.add_parser("preview", help="collect one task without sending")
    preview.add_argument("--task", required=True)
    preview.add_argument("--format", choices=("text", "layout", "json"), default="text")

    subparsers.add_parser("status", help="print the service status file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
        logging.basicConfig(
            level=getattr(logging, config.runtime.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        if args.command == "status":
            return print_status(config)
        if args.command == "validate":
            validate_device_prerequisites(config)
            build_tasks(config)
            print("Configuration and local Kindle prerequisites are valid.")
            return 0
        return asyncio.run(run_command(args, config))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


async def run_command(args: argparse.Namespace, config: AppConfig) -> int:
    tasks = build_tasks(config)
    sender = REPOSITORY_ROOT / "scripts" / "kindle-display.sh"
    sink = KindleSink(config.kindle, sender)
    service = DashboardService(config, tasks, sink)
    if args.command == "run":
        validate_device_prerequisites(config)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(signum, stop.set)
            except NotImplementedError:
                pass
        await service.run(stop)
        return 0
    if args.command == "once":
        validate_device_prerequisites(config)
        await service.display_once(args.task, args.page)
        return 0
    if args.command == "check":
        await service.collect_all_now()
        states = await service.store.snapshot_all()
        summary = {
            task_id: {
                "generation": state.page_set.generation if state.page_set else None,
                "page_count": len(state.page_set.pages) if state.page_set else 0,
                "source_generated_at": state.last_source_generated_at.isoformat()
                if state.last_source_generated_at
                else None,
                "error": state.last_error,
            }
            for task_id, state in states.items()
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if any(state.page_set is None or state.last_error for state in states.values()):
            raise RuntimeError("one or more dashboard tasks failed validation")
        return 0
    if args.command == "preview":
        task = next((candidate for candidate in tasks if candidate.task_id == args.task), None)
        if task is None:
            raise ValueError(f"unknown enabled task: {args.task}")
        result = await asyncio.wait_for(task.build_pages(service.started_at), task.collection_policy.timeout_seconds)
        if args.format == "json":
            print(json.dumps([asdict(page) for page in result.pages], ensure_ascii=False, indent=2))
        elif args.format == "layout":
            print("".join(serialize_ttf_page(page) for page in result.pages), end="")
        else:
            for index, page in enumerate(result.pages, start=1):
                if index > 1:
                    print(f"\n--- page {index}/{len(result.pages)} ---")
                print(page.text)
        return 0
    raise ValueError(f"unsupported command: {args.command}")


def print_status(config: AppConfig) -> int:
    path = config.runtime.run_dir / "status.json"
    if not path.exists():
        print("Dashboard has not written a status file yet.")
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def validate_device_prerequisites(config: AppConfig) -> None:
    if not config.kindle.ssh_key.is_file() or not os.access(config.kindle.ssh_key, os.R_OK):
        raise ValueError(f"Kindle SSH key is not readable: {config.kindle.ssh_key}")
    sender = REPOSITORY_ROOT / "scripts" / "kindle-display.sh"
    if not sender.is_file() or not os.access(sender, os.X_OK):
        raise ValueError(f"Kindle sender is not executable: {sender}")


if __name__ == "__main__":
    raise SystemExit(main())
