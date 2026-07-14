from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kindle_display.runtime.models import (
    CollectionPolicy,
    DisplayPolicy,
    validate_collection_policy,
    validate_display_policy,
)


REFRESH_PROFILES = frozenset({"clean", "flash_clean"})
TASK_KINDS = frozenset({"codex", "reddit_subscriptions"})


@dataclass(frozen=True)
class RuntimeConfig:
    run_dir: Path
    log_level: str
    offline_retry_seconds: int
    persist_last_good_pages: bool


@dataclass(frozen=True)
class KindleConfig:
    host: str
    ssh_key: Path
    connect_timeout_seconds: int
    display_timeout_seconds: int
    orientation: str
    normal_refresh_profile: str
    full_refresh_profile: str
    fonts: dict[str, str]


@dataclass(frozen=True)
class PlaylistConfig:
    task_order: tuple[str, ...]
    full_refresh_interval_seconds: int
    full_refresh_on_start: bool


@dataclass(frozen=True)
class CommandSourceConfig:
    cwd: Path
    argv: tuple[str, ...]
    max_stdout_bytes: int


@dataclass(frozen=True)
class TaskConfig:
    task_id: str
    kind: str
    enabled: bool
    collection: CollectionPolicy
    display: DisplayPolicy
    options: dict[str, Any] = field(default_factory=dict)
    source: CommandSourceConfig | None = None


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    kindle: KindleConfig
    playlist: PlaylistConfig
    tasks: tuple[TaskConfig, ...]


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as source:
        raw = tomllib.load(source)
    _check_keys(raw, {"runtime", "kindle", "playlist", "tasks"}, "root")

    runtime_raw = _mapping(raw, "runtime")
    _check_keys(
        runtime_raw,
        {"run_dir", "log_level", "offline_retry_seconds", "persist_last_good_pages"},
        "runtime",
    )
    runtime = RuntimeConfig(
        run_dir=_absolute_path(
            os.environ.get("KINDLE_DISPLAY_RUN_DIR", runtime_raw.get("run_dir", "/tmp/kindle-display")),
            "runtime.run_dir",
        ),
        log_level=str(runtime_raw.get("log_level", "INFO")).upper(),
        offline_retry_seconds=_positive_int(
            runtime_raw.get("offline_retry_seconds", 15), "runtime.offline_retry_seconds"
        ),
        persist_last_good_pages=_boolean(
            runtime_raw.get("persist_last_good_pages", True), "runtime.persist_last_good_pages"
        ),
    )

    kindle_raw = _mapping(raw, "kindle")
    _check_keys(
        kindle_raw,
        {
            "host",
            "ssh_key",
            "connect_timeout_seconds",
            "display_timeout_seconds",
            "orientation",
            "normal_refresh_profile",
            "full_refresh_profile",
            "fonts",
        },
        "kindle",
    )
    fonts = _mapping(kindle_raw, "fonts")
    if not fonts or any(not isinstance(key, str) or not isinstance(value, str) for key, value in fonts.items()):
        raise ValueError("kindle.fonts must be a non-empty string mapping")
    normal_profile = str(kindle_raw.get("normal_refresh_profile", "clean"))
    full_profile = str(kindle_raw.get("full_refresh_profile", "flash_clean"))
    for name, profile in (("normal_refresh_profile", normal_profile), ("full_refresh_profile", full_profile)):
        if profile not in REFRESH_PROFILES:
            raise ValueError(f"unknown kindle.{name}: {profile}")
    orientation = str(kindle_raw.get("orientation", "landscape"))
    if orientation != "landscape":
        raise ValueError("only the verified landscape orientation is supported")
    kindle = KindleConfig(
        host=os.environ.get("KINDLE_HOST", str(kindle_raw.get("host", "192.168.15.244"))),
        ssh_key=_absolute_path(
            os.environ.get("KINDLE_SSH_KEY", _required(kindle_raw, "ssh_key", "kindle")),
            "kindle.ssh_key",
        ),
        connect_timeout_seconds=_positive_int(
            kindle_raw.get("connect_timeout_seconds", 5), "kindle.connect_timeout_seconds"
        ),
        display_timeout_seconds=_positive_int(
            kindle_raw.get("display_timeout_seconds", 20), "kindle.display_timeout_seconds"
        ),
        orientation=orientation,
        normal_refresh_profile=normal_profile,
        full_refresh_profile=full_profile,
        fonts={str(key): str(value) for key, value in fonts.items()},
    )

    playlist_raw = _mapping(raw, "playlist")
    _check_keys(
        playlist_raw,
        {"task_order", "full_refresh_interval_seconds", "full_refresh_on_start"},
        "playlist",
    )
    order_raw = _required(playlist_raw, "task_order", "playlist")
    if not isinstance(order_raw, list) or not all(isinstance(item, str) for item in order_raw):
        raise ValueError("playlist.task_order must be an array of task IDs")
    if len(order_raw) != len(set(order_raw)):
        raise ValueError("playlist.task_order must not contain duplicates")
    playlist = PlaylistConfig(
        task_order=tuple(order_raw),
        full_refresh_interval_seconds=_positive_int(
            playlist_raw.get("full_refresh_interval_seconds", 1800),
            "playlist.full_refresh_interval_seconds",
        ),
        full_refresh_on_start=_boolean(
            playlist_raw.get("full_refresh_on_start", True), "playlist.full_refresh_on_start"
        ),
    )

    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError("tasks must be a non-empty array")
    tasks = tuple(_parse_task(item, index) for index, item in enumerate(tasks_raw))
    all_ids = [task.task_id for task in tasks]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("task IDs must be unique")
    enabled_ids = [task.task_id for task in tasks if task.enabled]
    if set(playlist.task_order) != set(enabled_ids) or len(playlist.task_order) != len(enabled_ids):
        raise ValueError("playlist.task_order must contain every enabled task exactly once")

    return AppConfig(runtime=runtime, kindle=kindle, playlist=playlist, tasks=tasks)


def _parse_task(value: Any, index: int) -> TaskConfig:
    if not isinstance(value, dict):
        raise ValueError(f"tasks[{index}] must be a table")
    _check_keys(value, {"id", "kind", "enabled", "collection", "display", "source", "options"}, f"tasks[{index}]")
    task_id = str(_required(value, "id", f"tasks[{index}]"))
    kind = str(_required(value, "kind", f"tasks[{index}]"))
    if kind not in TASK_KINDS:
        raise ValueError(f"unknown task kind: {kind}")
    enabled = _boolean(value.get("enabled", True), f"{task_id}.enabled")

    collection_raw = _mapping(value, "collection")
    _check_keys(collection_raw, {"interval_seconds", "timeout_seconds", "run_on_start"}, f"{task_id}.collection")
    collection = CollectionPolicy(
        interval_seconds=_positive_int(
            _required(collection_raw, "interval_seconds", f"{task_id}.collection"),
            f"{task_id}.collection.interval_seconds",
        ),
        timeout_seconds=_positive_int(
            _required(collection_raw, "timeout_seconds", f"{task_id}.collection"),
            f"{task_id}.collection.timeout_seconds",
        ),
        run_on_start=_boolean(collection_raw.get("run_on_start", True), f"{task_id}.collection.run_on_start"),
    )
    validate_collection_policy(collection)

    display_raw = _mapping(value, "display")
    _check_keys(display_raw, {"block_seconds", "min_page_seconds", "max_pages", "weight"}, f"{task_id}.display")
    display = DisplayPolicy(
        block_seconds=_positive_int(
            _required(display_raw, "block_seconds", f"{task_id}.display"), f"{task_id}.display.block_seconds"
        ),
        min_page_seconds=_positive_int(
            _required(display_raw, "min_page_seconds", f"{task_id}.display"),
            f"{task_id}.display.min_page_seconds",
        ),
        max_pages=_positive_int(
            _required(display_raw, "max_pages", f"{task_id}.display"), f"{task_id}.display.max_pages"
        ),
        weight=_positive_int(display_raw.get("weight", 1), f"{task_id}.display.weight"),
    )
    validate_display_policy(display)

    options = value.get("options", {})
    if not isinstance(options, dict):
        raise ValueError(f"{task_id}.options must be a table")
    allowed_options = {
        "codex": {"max_projects", "max_sessions_per_project"},
        "reddit_subscriptions": {"rows_per_page", "max_subscriptions", "timezone"},
    }[kind]
    _check_keys(options, allowed_options, f"{task_id}.options")

    source: CommandSourceConfig | None = None
    source_raw = value.get("source")
    if kind == "reddit_subscriptions":
        if not isinstance(source_raw, dict):
            raise ValueError(f"{task_id}.source is required")
        _check_keys(source_raw, {"type", "cwd", "argv", "max_stdout_bytes"}, f"{task_id}.source")
        if source_raw.get("type") != "command_json":
            raise ValueError(f"{task_id}.source.type must be command_json")
        argv_raw = _required(source_raw, "argv", f"{task_id}.source")
        if not isinstance(argv_raw, list) or not argv_raw or not all(isinstance(item, str) for item in argv_raw):
            raise ValueError(f"{task_id}.source.argv must be a non-empty string array")
        executable = _absolute_path(argv_raw[0], f"{task_id}.source.argv[0]")
        source = CommandSourceConfig(
            cwd=_absolute_path(_required(source_raw, "cwd", f"{task_id}.source"), f"{task_id}.source.cwd"),
            argv=(str(executable), *argv_raw[1:]),
            max_stdout_bytes=_positive_int(
                source_raw.get("max_stdout_bytes", 5 * 1024 * 1024), f"{task_id}.source.max_stdout_bytes"
            ),
        )
        rows = _positive_int(options.get("rows_per_page", 6), f"{task_id}.options.rows_per_page")
        maximum = _positive_int(options.get("max_subscriptions", rows * display.max_pages), f"{task_id}.options.max_subscriptions")
        if rows * display.max_pages < maximum:
            raise ValueError(f"{task_id} page capacity is smaller than max_subscriptions")
    elif source_raw is not None:
        raise ValueError(f"{task_id}.source is not supported for kind {kind}")

    return TaskConfig(
        task_id=task_id,
        kind=kind,
        enabled=enabled,
        collection=collection,
        display=display,
        options=dict(options),
        source=source,
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return value


def _check_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(sorted(unknown))}")


def _required(value: dict[str, Any], key: str, label: str) -> Any:
    if key not in value:
        raise ValueError(f"missing {label}.{key}")
    return value[key]


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _absolute_path(value: Any, label: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not expanded.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return expanded
