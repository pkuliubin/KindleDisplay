# 新增数据看板接入指南

## 1. 适用范围

本文说明如何把新的数据源接入 KindleDisplay。数据可以来自：

- 本机文件、数据库或 Python API；
- 输出 JSON 的外部命令；
- 后续新增的 HTTP/API Source。

接入目标不是把原始数据交给播放器，而是让任务生成一组可以直接显示的完整 `PageSpec`。播放器只负责选择任务、连续播放其页面并决定刷新模式。

## 2. 任务边界

每种看板必须自行负责：

```text
采集原始数据
  -> 校验并归一化为业务 Snapshot
  -> 排序、筛选和分页
  -> 生成完整 PageSpec
```

任务决定字段、字体大小、页边距、列宽、行数和页数。以下模块不应包含新业务的字段判断：

- `PageStore`
- `CollectorScheduler`
- `PlaylistScheduler`
- `KindleSink`

## 3. 推荐目录

以新任务 `system_health` 为例：

```text
src/kindle_display/tasks/system_health/
  __init__.py
  models.py       # 不可变的归一化数据模型
  dashboard.py    # 原始数据校验、归一化和排序
  renderer.py     # Kindle 页面格式与分页
  task.py         # 组合 Source、Dashboard 和 Renderer
```

通用数据采集器放在 `src/kindle_display/sources/`。只有确定能被多种任务复用时才新增通用 Source。

## 4. 实现 DashboardTask

所有任务实现同一个协议：

```python
class DashboardTask(Protocol):
    task_id: str
    collection_policy: CollectionPolicy
    display_policy: DisplayPolicy
    cancel_on_timeout: bool

    async def build_pages(self, now: datetime) -> TaskBuildResult: ...
```

典型实现：

```python
class SystemHealthTask:
    cancel_on_timeout = True

    def __init__(self, task_id, source, dashboard, renderer, collection_policy, display_policy):
        self.task_id = task_id
        self.source = source
        self.dashboard = dashboard
        self.renderer = renderer
        self.collection_policy = collection_policy
        self.display_policy = display_policy

    async def build_pages(self, now):
        raw = await self.source.collect()
        snapshot = self.dashboard.normalize(raw, now)
        pages = self.renderer.render_pages(snapshot)
        return TaskBuildResult(snapshot.generated_at, pages)
```

`source_generated_at` 应表示源数据的生成时间，而不是页面播放时间。数据源没有该字段时，才使用本次采集时间。

`cancel_on_timeout` 的选择：

- `True`：异步子进程、HTTP 请求等能够安全取消的采集；
- `False`：通过 `asyncio.to_thread()` 包装、取消后底层仍会继续运行的同步采集。

## 5. 外部命令数据源

已有 `CommandJsonSource` 可直接复用。外部命令必须满足：

1. 成功时退出码为 `0`；
2. `stdout` 只输出一个 UTF-8 JSON 文档；
3. 日志写入 `stderr`，不能混入 JSON；
4. 时间戳使用带时区的 ISO 8601；
5. JSON schema 由具体任务的 Dashboard 校验。

配置示例：

```toml
[tasks.source]
type = "command_json"
cwd = "/absolute/path/to/project"
argv = [
  "/absolute/path/to/python",
  "scripts/show_status.py",
  "--format", "json",
]
max_stdout_bytes = 5242880
```

`argv` 直接传给子进程，不经过 Shell。因此不要使用管道、重定向、`$VAR` 或 `~` 展开。需要这些行为时，应由被调用脚本自身实现。

命令超时、退出码非零、非法 UTF-8、非法 JSON 或输出超限时，本次采集失败；`PageStore` 会继续保留上一次成功页面。

## 6. Renderer 与分页

Renderer 返回 `tuple[PageSpec, ...]`。每一页必须已经是最终可显示内容：

```python
PageSpec(
    page_id=f"{task_id}:{page_index}",
    text="\n".join(lines),
    font_role="cjk_mono",
    font_px=26,
    top=20,
    left=20,
    right=15,
    bottom=20,
)
```

必须遵守：

- `page_id` 在同一 PageSet 内唯一且稳定；
- 一页包含标题、数据时间、页码及理解本页所需的摘要；
- 项目名和数据内容允许任意中英文，不按当前字符集裁剪字体；
- 表格使用完整 CJK 等宽字体和 `U+2007 FIGURE SPACE` 对齐；
- 按显示宽度截断中英文，不直接使用 `len()`；
- 页面不包含 Tab、NUL 或其他控制字符；
- 页数不得超过配置中的 `max_pages`；
- `page_count * min_page_seconds <= block_seconds`；
- 一页是一个完整文本块，不能要求播放器逐行或逐字段绘制。

同一任务的多页会固定在同一个 generation 内连续播放。采集过程中发布的新版本只会在下一次进入该任务时显示。

## 7. 注册新任务类型

当前配置采用严格白名单。新增 `system_health` 至少需要修改以下位置：

1. 在 `runtime/config.py` 的 `TASK_KINDS` 中加入 `system_health`；
2. 在同一文件的 `allowed_options` 中声明该任务允许的配置项；
3. 如果任务使用 `[tasks.source]`，扩展 `_parse_task()` 的 Source 解析分支；当前只为 `reddit_subscriptions` 开放了 `command_json`；
4. 在 `tasks/factory.py` 中增加构建分支，组合 Source、Dashboard、Renderer 和 Task。

不要把业务构建逻辑放进调度器。Factory 是运行时唯一需要知道具体任务类型的地方。

然后在 `config/dashboard.toml` 注册任务，并加入播放顺序：

```toml
[playlist]
task_order = ["codex", "reddit-subscriptions", "system-health"]

[[tasks]]
id = "system-health"
kind = "system_health"
enabled = true

[tasks.collection]
interval_seconds = 300
timeout_seconds = 30
run_on_start = true

[tasks.display]
block_seconds = 30
min_page_seconds = 15
max_pages = 2
weight = 1

[tasks.options]
rows_per_page = 10
timezone = "Asia/Shanghai"
```

配置含义：

- `collection.interval_seconds`：多久重新采集一次，与播放周期无关；
- `block_seconds`：每次轮到该任务时，整组页面占用的总时间；
- `min_page_seconds`：单页最短停留时间；
- `max_pages`：任务允许生成的最大页数；
- `weight`：任务块被选中的相对频率，不会打散任务内部页面。

## 8. 测试与接入验证

至少增加以下测试：

- 正常、空数据、缺失字段和错误类型的 schema 校验；
- 中英文长字段的截断与对齐；
- 边界行数对应的分页结果；
- 每页都有唯一 ID、页码、数据时间和摘要；
- 页数及停留时间符合 `DisplayPolicy`；
- Source 超时或失败后不会发布半成品页面；
- 真实样例 JSON 的回归测试，但不要依赖真实外部服务运行单元测试。

本机验证：

```sh
PYTHONPATH=src pytest -q
ruff check src tests scripts
mypy --ignore-missing-imports src/kindle_display
bash -n scripts/*.sh
git diff --check
```

先只预览，不修改 Kindle：

```sh
./scripts/kindle-dashboard.sh check
./scripts/kindle-dashboard.sh preview --task system-health --format text
```

确认文本后发送指定页面：

```sh
./scripts/kindle-dashboard.sh once --task system-health --page 1
```

最后启动完整轮播，确认新任务多页连续、其他任务仍能正常采集和显示：

```sh
./scripts/kindle-dashboard.sh stop
./scripts/kindle-dashboard.sh start
./scripts/kindle-dashboard.sh status
```

## 9. 完成检查清单

- 新任务不要求修改 `PageStore`、播放器或 Kindle 发送器；
- 采集失败时仍能显示最后成功页面；
- 外部命令路径和参数全部可配置；
- 任务自行完成字段选择、分页和页面格式；
- 所有页面均为一次 TrueType 绘制；
- 页面高度和宽度经过真实 Kindle 检查；
- 采集频率、显示时长和权重符合实际信息价值；
- 自动化测试与至少一次真实数据预览通过。
