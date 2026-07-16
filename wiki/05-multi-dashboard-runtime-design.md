# Kindle 多看板采集与轮播运行时设计

## 1. 文档目的

本文是 KindleDisplay 从“单个 Codex 看板循环”演进为“多个独立数据任务采集并连续轮播”的实现规范。后续开发者应能够只阅读本文，完成核心运行时、Codex 迁移、外部命令数据源、Reddit 订阅看板、刷新策略和验证工作。

本文规定的是目标实现，不代表所有模块已经存在。当前已经验证的 Kindle CJK 单页渲染约束仍以 `wiki/04-cjk-table-rendering.md` 为基础；本文在其上增加多任务采集、页面存储、连续轮播和普通/完整刷新调度。

## 2. 已确定的产品行为

以下决策不再留给实现阶段重新选择：

1. 数据采集周期与 Kindle 播放周期完全独立。
2. 每个任务自包含数据采集、业务归一化、筛选排序、分页和页面格式。
3. 播放器不理解表格字段、字体大小、列宽或换行，只读取任务生成的完整页面。
4. 同一任务的多页必须连续播放，不能被其他主题插入。
5. 每次进入一个任务页面块时固定使用同一代 `PageSet`，中途产生的新数据到下一轮才生效。
6. 数据采集失败时保留并继续播放该任务最后一次成功的页面。
7. 一个 Kindle 页面仍然只执行一次 FBInk TrueType 文本绘制。
8. 普通换页不使用黑闪式全刷；按照设备级周期执行一次完整刷新清除残影。
9. Shell 只负责 `start / stop / status / once` 生命周期；长期调度在一个 Python 服务中完成。
10. 外部命令通过 stdout 返回 JSON，由 Python 直接捕获，不依赖固定的 `tmp.json` 中转文件。
11. `block_seconds` 决定一次任务块的占屏时间，`weight` 独立决定该任务块的相对出现频率。

## 3. 非目标

第一版不实现以下能力：

- Kindle 侧业务逻辑、分页或模板渲染；
- Web 管理后台；
- 多台 Kindle 同时播放；
- 秒级动画或局部字段刷新；
- 任务优先级抢占和告警页强制插播；
- 任意 Shell 字符串执行；外部命令必须使用参数数组；
- 在播放器中针对 Codex、Reddit 等业务类型编写条件分支。

## 4. 术语与职责

| 名称 | 职责 |
| --- | --- |
| `DashboardTask` | 一个完整的信息主题，例如 Codex 状态或 Reddit 订阅状态。 |
| `Source` | 获取原始数据；可以是项目内 Python 代码，也可以是外部命令。 |
| `Snapshot` | 任务归一化后的业务数据，只供该任务使用。 |
| `TaskRenderer` | 把 Snapshot 排序、分页并生成完整 Kindle 页面。 |
| `PageSpec` | 一个已经排版完成、可直接交给 KindleSink 的页面描述。 |
| `PageSet` | 某个任务同一时刻生成的一组页面，也称“一代页面”。 |
| `PageStore` | 原子保存每个任务最后一次成功的 PageSet 和运行健康信息。 |
| `CollectorScheduler` | 按每个任务的采集周期执行任务并更新 PageStore。 |
| `PlaylistScheduler` | 按任务顺序连续播放 PageSet，并决定每页停留时间。 |
| `KindleSink` | 把 PageSpec 转换成一次 SSH + FBInk 调用，不参与页面格式设计。 |

不要把 `TaskRenderer` 和 `KindleSink` 合并。前者决定“页面长什么样”，后者只决定“怎样把这一页送到设备”。

## 5. 总体架构

```text
                         Python service

  CollectorScheduler                           PlaylistScheduler
          |                                             |
          | 到期执行                                    | 选择下一个任务块
          v                                             v
  +------------------+                         +------------------+
  | DashboardTask    |                         | PageStore        |
  |                  |---- atomic publish ---->| latest PageSet   |
  | Source           |                         | per task         |
  | normalize        |                         +------------------+
  | TaskRenderer     |                                  |
  +------------------+                                  | pin generation
                                                        v
                                               +------------------+
                                               | KindleSink       |
                                               | normal / full    |
                                               +------------------+
                                                        |
                                              one SSH + one FBInk call
                                                        |
                                                        v
                                                     Kindle
```

采集器和播放器运行在同一个 Python 服务内，但使用独立的调度循环。外部命令运行缓慢、超时或失败时，不能阻塞正在进行的页面轮播。

## 6. 建议目录结构

保留现有业务模块，新增运行时和任务封装：

```text
src/kindle_display/
  runtime/
    models.py                 # PageSpec、PageSet、策略和运行状态
    config.py                 # TOML 加载、校验和环境变量展开
    page_store.py             # 原子内存存储及可选磁盘缓存
    collector_scheduler.py    # 采集周期、超时、失败和防重入
    playlist_scheduler.py     # 连续任务块、停留时间、全刷周期
    service.py                # 组合两个 scheduler 和 KindleSink
  devices/
    kindle_sink.py            # 调用 scripts/kindle-display.sh
  sources/
    command_json.py           # 通用外部 JSON 命令执行器
    codex_local.py            # 现有实现保留
  tasks/
    base.py                   # DashboardTask Protocol
    codex/
      task.py                 # 包装现有 Codex pipeline
    reddit_subscriptions/
      models.py
      dashboard.py
      renderer.py
      task.py
  dashboards/
    codex_status.py           # 第一阶段继续复用
  renderers/
    kindle_text.py            # 第一阶段继续复用
  cli.py                      # foreground、once、preview、status 数据

config/
  dashboard.example.toml

scripts/
  kindle-dashboard.sh         # 唯一正式生命周期入口
  kindle-display.sh           # 单页设备发送器
  codex-dashboard.sh          # 迁移期兼容入口
```

第一阶段不要求立即移动现有 Codex 文件。先用 `tasks/codex/task.py` 包装它们，等统一运行时稳定后再决定是否整理目录。

## 7. 核心数据契约

### 7.1 PageSpec

建议在 `runtime/models.py` 中使用不可变 dataclass：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    page_id: str
    text: str
    font_role: str
    font_px: int
    top: int
    left: int
    right: int
    bottom: int
```

规则：

- `page_id` 在同一任务内稳定，例如 `reddit-subscriptions:0`；
- `text` 是包含真实换行的完整页面文本；
- 字号和边距由任务 Renderer 决定；
- `font_role` 是逻辑名称，例如 `cjk_mono`，不保存 Kindle 上的绝对路径；
- 设备配置负责把 `cjk_mono` 映射到 `/mnt/us/fonts/SarasaMonoSC-Regular.ttf`；
- PageSpec 不包含刷新模式，普通刷新还是完整刷新由 PlaylistScheduler 决定。

PageSpec 发布前必须通过以下校验：

- `page_id` 非空，并且在同一 PageSet 内唯一；
- `font_role` 必须存在于设备字体映射；
- `font_px` 为正偶数，边距均为非负整数；
- `text` 非空，UTF-8 编码后不超过 256 KiB；
- `text` 只允许换行符 `\n`，禁止 TAB、NUL、`U+001E` 和其他 C0/C1 控制字符；
- Renderer 必须先把业务数据中的不可打印字符替换为空格，再交给 PageSpec；
- 序列化器遇到非法字符必须报错，不能静默生成损坏的 layout record。

PageSpec 必须能序列化为现有 `ttf_page` 单页布局记录，但运行时内部不要用 TSV 字符串作为对象间接口。只有 KindleSink 调用 Shell 发送器时才序列化。

### 7.2 PageSet

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PageSet:
    task_id: str
    generation: int
    source_generated_at: datetime
    built_at: datetime
    pages: tuple[PageSpec, ...]
    content_hash: str
```

规则：

- `generation` 由 PageStore 为每个任务递增，任务本身不管理并发版本；
- `source_generated_at` 来自数据源；数据源没有该字段时使用采集完成时间；
- `built_at` 是本机页面生成完成时间；
- `content_hash` 对所有影响显示的 PageSpec 字段计算 SHA-256；
- PageSet 必须至少包含一页；“没有数据”应由任务生成一页明确的空状态页面；
- PageSet 发布后不可修改。

### 7.3 任务策略

```python
@dataclass(frozen=True)
class CollectionPolicy:
    interval_seconds: int
    timeout_seconds: int
    run_on_start: bool = True


@dataclass(frozen=True)
class DisplayPolicy:
    block_seconds: int
    min_page_seconds: int
    max_pages: int
    weight: int = 1
```

`block_seconds` 是一次进入该任务后允许使用的展示时间预算。它不是采集周期。

必须满足：

```text
max_pages >= 1
min_page_seconds >= 1
block_seconds >= min_page_seconds
max_pages * min_page_seconds <= block_seconds
1 <= weight <= 10
```

TaskRenderer 生成的实际页数还必须满足：

```text
1 <= page_count <= max_pages
page_count * min_page_seconds <= block_seconds
```

不满足时视为任务实现或配置错误，不能发布这一代 PageSet；继续保留上一代页面。

### 7.4 DashboardTask 接口

统一运行时只依赖一个窄接口：

```python
@dataclass(frozen=True)
class TaskBuildResult:
    source_generated_at: datetime
    pages: tuple[PageSpec, ...]


from typing import Protocol


class DashboardTask(Protocol):
    task_id: str
    collection_policy: CollectionPolicy
    display_policy: DisplayPolicy

    async def build_pages(self, now: datetime) -> TaskBuildResult:
        """Collect, normalize and render one complete page generation."""
```

任务包内部可以继续细分 Source、Dashboard 和 Renderer；运行时不感知这些内部结构。`source_generated_at` 优先使用源 JSON 或源事件中的生成时间，没有可靠来源时使用采集完成时间。

## 8. 配置格式

项目要求 Python 3.11 以上，可以直接使用标准库 `tomllib`，不增加 YAML 依赖。建议配置文件为 `config/dashboard.toml`，仓库只提交 `dashboard.example.toml`。

完整示例：

```toml
[runtime]
run_dir = "/tmp/kindle-display"
log_level = "INFO"
offline_retry_seconds = 15
persist_last_good_pages = true

[kindle]
host = "192.168.15.244"
ssh_key = "${HOME}/.ssh/kindle_display_ed25519"
connect_timeout_seconds = 5
display_timeout_seconds = 20
orientation = "landscape"
normal_refresh_profile = "clean"
full_refresh_profile = "flash_clean"

[kindle.fonts]
cjk_mono = "/mnt/us/fonts/SarasaMonoSC-Regular.ttf"

[playlist]
task_order = ["codex", "reddit-subscriptions"]
full_refresh_interval_seconds = 1800
full_refresh_on_start = true

[[tasks]]
id = "codex"
kind = "codex"
enabled = true

[tasks.collection]
interval_seconds = 60
timeout_seconds = 20
run_on_start = true

[tasks.display]
block_seconds = 120
min_page_seconds = 15
max_pages = 8
weight = 1

[[tasks]]
id = "reddit-subscriptions"
kind = "reddit_subscriptions"
enabled = true

[tasks.collection]
interval_seconds = 300
timeout_seconds = 90
run_on_start = true

[tasks.display]
block_seconds = 30
min_page_seconds = 15
max_pages = 2
weight = 1

[tasks.source]
type = "command_json"
cwd = "/Users/liubin/Projects/AlphaDecisionTaskManager"
argv = [
  "/opt/anaconda3/envs/college/bin/python",
  "scripts/show_reddit_subscription_status.py",
  "--recent-runs", "30",
  "--recent-tasks", "30",
  "--format", "json",
]
max_stdout_bytes = 5242880

[tasks.options]
rows_per_page = 12
max_subscriptions = 24
timezone = "Asia/Shanghai"
```

该示例使用已经真机验证的 `clean` 普通换页和 `flash_clean` 周期完整刷新。

配置加载规则：

1. 对路径执行 `os.path.expandvars` 和 `os.path.expanduser`；
2. 未识别字段直接报错，避免拼写错误被静默忽略；
3. `task_order` 中的 ID 必须存在且启用；
4. 每个启用任务必须且只能在 `task_order` 中出现一次，重复频率由 `weight` 表达；
5. 不把私钥内容或 API token 写入 TOML；
6. 外部命令需要的秘密通过启动进程环境继承，日志不得打印环境值；
7. `argv` 必须是字符串数组，禁止使用 `shell=True`；
8. `argv[0]`、`cwd` 和 SSH key 路径展开后必须是绝对路径；
9. collection interval/timeout、设备 connect/display timeout、完整刷新周期均必须为正数；
10. refresh profile 必须来自 KindleSink 白名单；
11. Reddit 必须满足 `rows_per_page * max_pages >= max_subscriptions`；
12. 配置错误在服务启动前一次性报告，不能带病进入后台。

## 9. PageStore：采集器与播放器的交互边界

### 9.1 内存状态

PageStore 是采集器与播放器之间唯一的正式交互接口。建议保存：

```python
@dataclass(frozen=True)
class TaskRuntimeState:
    page_set: PageSet | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_source_generated_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    collecting: bool
    active_run_id: int | None
```

需要提供以下原子操作：

```python
get_task_state(task_id) -> TaskRuntimeState
snapshot_all() -> dict[str, TaskRuntimeState]
mark_collecting(task_id, now) -> CollectionLease | None
publish(lease, pages, source_generated_at, now) -> PageSet
record_failure(lease, error, now, release: bool = True) -> None
release_collection(lease) -> None
```

`CollectionLease` 至少包含 `task_id` 和单调递增的 `run_id`。`mark_collecting()` 在任务已经执行时返回 `None`，否则设置 `active_run_id` 并返回 lease。`publish()`、`record_failure()` 和 `release_collection()` 必须核对 lease 仍是当前 run；过期 run 的晚到结果只能丢弃，不能覆盖新状态。

这里使用“每个任务一个最新状态槽位”，不使用消息队列。播放需要的是进入任务块时的最新完整页面，而不是逐个消费所有历史采集事件；若采集比播放快，消息队列只会积压已经过时的 PageSet。

`publish()` 分为锁外准备和锁内提交：

1. 锁外校验页面数量和 PageSpec，并计算内容 hash；
2. 进入锁后核对 CollectionLease；
3. 如果显示内容没有变化，只更新 `last_success_at` 和 `last_source_generated_at`，不递增 generation；
4. 如果内容变化，生成下一代不可变 PageSet；
5. 一次性替换任务当前 PageSet，清除 `active_run_id` 和 `collecting`；
6. 退出锁后写可选磁盘缓存。

PlaylistScheduler 每次进入任务块时只取得一次 PageSet 引用。因为 PageSet 不可变，即使 PageStore 随后发布新版本，本轮播放仍然一致。

锁只保护 lease 核对、状态读取和原子替换。数据采集、JSON 解析、页面渲染、hash 计算、磁盘缓存和 Kindle SSH 都不能在持有 PageStore 锁时执行。磁盘缓存失败只记录错误，不回滚已经成功发布的内存 PageSet。

### 9.2 可选磁盘缓存

主交互必须走内存，不通过临时文件轮询。为了进程重启和排障，可以把最后一代成功页面缓存到：

```text
/tmp/kindle-display/cache/<task-id>.json
```

写入必须使用同目录临时文件加 `os.replace()`，避免服务崩溃留下半个 JSON。启动时可以加载并校验缓存，让 Kindle 在首次慢速采集完成前先恢复旧页面。

缓存只保存 PageSet 和必要时间戳，不默认保存外部命令完整原始 JSON。`/tmp` 在系统重启后可能被清理，因此它是恢复优化，不是业务数据存储。

## 10. CollectorScheduler 详细行为

每个任务有独立的下一次执行时间。`interval_seconds` 表示计划启动时间之间的固定节拍，而不是“上次完成后再等待多久”。调度周期使用 monotonic clock，业务时间戳使用 timezone-aware wall clock。

### 10.1 正常流程

```text
任务到期
  -> mark_collecting，取得 CollectionLease
  -> 在独立 asyncio task 中执行 build_pages
  -> timeout 限制
  -> 校验 PageSpec 和 DisplayPolicy
  -> PageStore.publish
  -> 推进到下一个尚未错过的计划 tick
```

调度器不能等待一个任务完成后才检查其他任务。可使用 `asyncio.create_task()` 管理每个采集任务；同步的内置采集器使用 `asyncio.to_thread()`，外部命令使用 `asyncio.create_subprocess_exec()`。

### 10.2 防重入

任务启动时先执行：

```text
next_due = scheduled_due + interval
```

任务完成时，如果 `next_due <= completion_time`，持续增加 interval，直到 `next_due > completion_time`。这样保持固定节拍、跳过已经错过的 tick，并且不会为了追赶历史任务而立即连续执行。

若一个任务执行时间超过采集周期：

- 不启动第二个相同任务；
- 记录一次 `collection_skipped_running`；
- 完成后按照上述规则跳过所有已错过 tick；不从完成时间重新建立一套新的周期。

### 10.3 失败语义

以下都属于采集失败：

- 内置 Source 抛出异常；
- 外部命令退出码非零；
- 外部命令超时；
- stdout 超过上限；
- stdout 不是 UTF-8 或合法 JSON；
- JSON schema 不满足任务要求；
- Renderer 产生零页、页数超限或非法尺寸；
- PageSet 内容无法序列化。

失败时：

1. `record_failure()` 保存精简错误；
2. 不替换最后成功的 PageSet；
3. 不让异常退出 CollectorScheduler；
4. 下次按照正常 interval 重试；
5. stderr 日志最多保留末尾 8 KiB，避免日志失控；
6. 错误中不包含环境变量、密钥或完整业务 JSON。

成功、失败和可完全取消的外部命令都必须在 `finally` 路径通过当前 lease 复位 `collecting`。仍在后台运行的 `to_thread()` 是唯一例外：超时时以 `release=false` 记录失败，保持 lease 有效，等底层 Future 真正完成后调用 `release_collection(lease)`；该 Future 的业务结果必须丢弃。失败和超时也按照同一固定节拍计算下一次执行时间。

第一版不需要复杂指数退避。固定采集周期已经限制请求频率；Kindle 断线属于 Sink 错误，与数据采集无关，不能停止采集。

## 11. 外部 JSON 命令数据源

`CommandJsonSource` 是通用基础设施，只负责执行命令并返回解析后的 JSON，不理解 Reddit 字段。

建议接口：

```python
class CommandJsonSource:
    async def collect(self) -> object:
        ...
```

执行要求：

1. 使用 `asyncio.create_subprocess_exec(*argv, cwd=...)`；
2. 禁止 `create_subprocess_shell()`；
3. 并发、分块读取 stdout 和 stderr，防止任一管道阻塞；
4. 使用任务的 `timeout_seconds`；
5. 超时后先 terminate，短暂等待后再 kill；
6. 检查退出码后才解析 stdout；
7. 在读取过程中限制 stdout 累计字节数，不能先 `communicate()` 读入全部内容再检查；
8. 使用 UTF-8 严格解码；
9. 使用 `json.loads()`；
10. 返回 Python 对象，由具体任务验证 schema。

子进程生命周期必须由 `CommandJsonSource.collect()` 自己负责。推荐结构：

```text
create subprocess
try:
    并发读取 stdout 和 stderr
    等待退出或 timeout
except CancelledError / TimeoutError / OutputLimitError:
    重新抛出
finally:
    若进程仍存活：terminate
    最多等待 2 秒
    仍存活：kill
    await process.wait()
```

stderr 使用固定 8 KiB 的尾部 ring buffer。stdout 超过上限后立即终止子进程。

`asyncio.to_thread()` 无法强制终止底层线程。实现时必须保存 `worker = asyncio.create_task(asyncio.to_thread(...))`，再通过 `asyncio.wait_for(asyncio.shield(worker), timeout)` 等待，确保超时后仍持有 worker 引用。完成回调只调用 `release_collection(lease)`，不能再发布已经超时的结果。需要强制取消的耗时采集器必须改为子进程或原生异步实现；`to_thread()` 只允许包装已知有界的本地操作，例如当前 Codex 文件读取。服务关闭时等待一个有限 grace period，仍未结束则记录明确警告；实现者必须注意默认线程池可能延迟 Python 进程真正退出。

正式运行不执行：

```sh
... --format json > tmp.json
```

等价数据直接来自子进程 stdout。`tmp.json` 可以由开发者手工生成用于 fixture，但不能成为服务运行依赖。

## 12. PlaylistScheduler 详细算法

### 12.1 基本顺序

播放器在任务块边界使用平滑加权轮询（smooth weighted round robin）选择任务，不把任务内部页面打散。`task_order` 只用于稳定的同权重 tie-break，`weight` 决定任务块的相对出现次数。

平滑加权轮询状态为每个任务一个 `current_weight`，初始为 0。每次选择任务块：

```text
eligible = 当前拥有 PageSet 的任务
对每个 eligible task:
    current_weight += configured weight
选择 current_weight 最大的任务；相同则按 task_order
chosen.current_weight -= sum(eligible weights)
连续播放 chosen 的整个 PageSet
```

任务暂时没有 PageSet 时不参与本次计算，并把其 `current_weight` 重置为 0，避免恢复后一次性补播历史权重。PageSet 更新不重置权重或全局播放进度。

当 Codex `weight=2`、Reddit `weight=1` 时，任务块顺序为：

```text
Codex page 1
Reddit page 1
Reddit page 2
Codex page 1
...
```

当两个任务的 `weight` 都为 1 时，顺序为 `Codex block -> Reddit block -> Codex block`。无论权重如何，同一 Reddit PageSet 的所有页面始终连续。

加权结果可能连续两次选择同一任务。这仍然是两个独立任务块：第二个块开始前重新读取最新 PageSet 并重新计算页数和停留时间；若页面内容未变，内容去重可以避免重复发送，但两个块的时间预算不能被隐式合并。

`block_seconds` 和 `weight` 的语义不同：

- `block_seconds` 决定每次进入任务后占用多久，并据实际页数分配每页停留时间；
- `weight` 决定该任务块在长期播放中的相对出现次数；
- 长期理论占屏比例约为 `weight * block_seconds` 占所有任务该值之和。

某任务尚无成功 PageSet 时直接跳过。所有任务都没有页面时不刷新 Kindle，每隔 `offline_retry_seconds` 重新检查。

### 12.2 页面停留时间

进入任务块时读取固定的一代 PageSet：

```text
N = 实际页数
budget = block_seconds
base = budget // N
remainder = budget % N
```

前 `remainder` 页各停留 `base + 1` 秒，其余页面停留 `base` 秒。这样总时间精确等于 `block_seconds`。

示例：Reddit 2 页，预算 30 秒：

```text
page 1: 15s
page 2: 15s
```

发布前已经保证 `base >= min_page_seconds`。

### 12.3 页面代际固定

进入 Reddit 页面块时若读到 generation 5，本轮所有页面必须来自 generation 5。即使播放 page 1 时 PageStore 发布 generation 6，本轮 page 2～4 仍然使用 generation 5。

完成整个 Reddit 块、下次重新进入 Reddit 时，才重新读取 PageStore 并使用 generation 6。

这是保证多页语义一致性的必要条件。

### 12.4 更新不重置播放位置

采集成功不能主动调用播放器，也不能把任务顺序重置到第一项。播放游标只由 PlaylistScheduler 自己推进。

否则 Codex 每分钟更新一次时可能不断重置全局播放列表，导致 Reddit 后续页面长期无法显示。

### 12.5 内容去重

每个 PageSpec 计算内容 hash。准备显示下一页时：

- 页面与当前屏幕内容不同：发送；
- 页面相同且未到完整刷新时间：不发送，只正常计算停留时间；
- 页面相同但已到完整刷新时间：以完整刷新模式重新发送；
- KindleSink 上一次发送失败：不能认为该页面已显示。

## 13. 普通刷新与周期完整刷新

### 13.1 刷新模式

定义：

```python
class RefreshMode(Enum):
    NORMAL = "normal"
    FULL = "full"
```

`RefreshMode` 是播放器使用的设备无关语义。KindleSink 再把它映射到设备配置中的刷新 profile。当前真机验证通过的映射为：

```text
NORMAL: fbink -q -c    -t ... -- <whole page>
FULL:   fbink -q -f -c -t ... -- <whole page>
```

其中：

```text
clean       -> -c
flash_clean -> -f -c
```

配置只能选择代码中声明并验证过的 profile，不能从 TOML 注入任意 FBInk 参数。

`-c` 用于清理 framebuffer 中的上一页，避免文字直接叠加；普通模式移除造成明显黑白闪烁的 `-f`，允许逐渐积累少量电子墨水残影。

2026-07-14 真机验证结果：`clean` 换页没有全屏黑闪，表现为可接受的淡入淡出，旧页面残影很轻；`flash_clean` 有预期黑闪并能作为周期清残影的完整刷新。两个 profile 均已通过本机 Kindle 4 验证。

### 13.2 全刷状态机

PlaylistScheduler 保存：

```text
last_successful_full_refresh_monotonic
force_full_refresh
```

规则：

1. `full_refresh_on_start = true` 时，服务首次成功显示使用 FULL；
2. 距离上次成功 FULL 超过配置周期时，下一次实际发送使用 FULL；
3. FULL 发送失败时不更新时间，下一次继续尝试 FULL；
4. 页面因内容相同而跳过时，如果已经到期，不能继续跳过，必须重发并 FULL；
5. Kindle 断线后恢复连接，第一次成功发送使用 FULL；
6. 周期到期不会打断当前页面停留；在下一次页面发送边界执行；
7. 全刷属于设备级策略，不由某个任务控制。

建议初始值：

```text
普通页面停留：20～60 秒
完整刷新周期：30 分钟
启动首次显示：完整刷新
```

## 14. KindleSink 与发送器契约

### 14.1 KindleSink

建议接口：

```python
class KindleSink:
    async def display(self, page: PageSpec, refresh_mode: RefreshMode) -> None:
        ...
```

第一版继续复用 `scripts/kindle-display.sh`，避免在 Python 中重新实现已经真机验证的 SSH 引号和 FBInk 调用。KindleSink 负责：

1. 把 PageSpec 序列化为一条 `ttf_page` layout record；
2. 根据 RefreshMode 查找设备配置中的 profile，并调用 `kindle-display.sh --layout --refresh-profile <name>`；
3. 通过 stdin 写入页面；
4. 检查退出码；
5. 限制调用超时；
6. 不在日志中输出 SSH key。

需要扩展 `scripts/kindle-display.sh`，并在 Shell 内使用严格 `case` 白名单：

```text
--refresh-profile clean       -> ttf_page 使用 -q -c -t
--refresh-profile flash_clean -> ttf_page 使用 -q -f -c -t
```

未知 profile 必须退出并返回非零状态，禁止把配置内容直接拼接为 FBInk 参数。未指定 `--refresh-profile` 时，迁移期默认保持 `flash_clean`，避免改变现有 `codex-dashboard.sh once` 行为。统一服务必须显式传入经过配置校验的 profile。

### 14.2 单页单次绘制约束

每个 PageSpec 必须继续满足：

- 一条 `ttf_page` 记录；
- 一次 SSH 调用；
- 一次 FBInk TrueType 调用；
- 字体常驻 Kindle；
- 页面内容整体传输；
- 不按字段、行或中英文拆分绘制。

字体、显示单位、CJK 截断和 FIGURE SPACE 对齐规则见 `wiki/04-cjk-table-rendering.md`。

### 14.3 必须保留的现有渲染基线

为了让本文可以独立指导开发，下面列出运行时迁移时不可改变的设备级渲染行为：

- Kindle 常驻完整的 `/mnt/us/fonts/SarasaMonoSC-Regular.ttf`；
- 主页面统一使用 Sarasa Mono SC，不混用 IBM 点阵字体；
- ASCII、数字和半角空格按 1 个显示单位计算，东亚全角字符按 2 个显示单位计算；
- 表格填充使用 `U+2007 FIGURE SPACE`，不使用连续 ASCII 空格或 NBSP；
- Codex 使用真机验证过的固定 `24px`；不能仅凭偶数字号假设中英文半格不会产生累计像素误差；
- 截断标题必须精确填满字段宽度，奇数宽度空位用 `.` 补足；
- 当前边距为 `top=20`、`left=20`、`right=15`、`bottom=20`；
- layout record 内部用 `U+001E` 暂存逻辑换行，Shell 发送前恢复为真实换行；
- FBInk 使用 `notrunc`，越界应在开发验证阶段暴露，不能静默切掉右侧字段。

具体列宽、字段、状态表示、字号回落和任务内间距属于 TaskRenderer 自己的版本化契约，不属于通用运行时。Codex 的当前功能演进以 `wiki/06-codex-daily-token-usage-design.md` 为准；其中可以调整状态缩写、token 字段和列宽，但必须继续遵守完整 CJK 字体、显示单位、精确字段宽度、单页单次绘制和页面宽度验算规则。Reddit Renderer 同样自行决定列宽、字号和边距。

## 15. Codex 任务迁移

现有链路为：

```text
CodexLocalSource
  -> CodexStatusDashboard
  -> KindleTextRenderer.render_layout()
```

第一阶段新增 `CodexDashboardTask`，内部复用这三个类：

```python
class CodexDashboardTask:
    async def build_pages(self, now: datetime) -> TaskBuildResult:
        snapshot = await asyncio.to_thread(...collect...)
        pages = renderer.render_pages(snapshot)
        return TaskBuildResult(snapshot.generated_at, pages)
```

需要把 `KindleTextRenderer.render_layout()` 的核心输出重构为 `render_pages() -> tuple[PageSpec, ...]`。原 `render_layout()` 保留为单页兼容方法，通过序列化第一页产生原来的 TSV，保证：

- `scripts/preview_codex_status.py --layout` 继续工作；
- `wiki/06-codex-daily-token-usage-design.md` 完成后的 Codex 页面字段、字号、列宽和 CJK 对齐不因运行时接入再次变化；
- 原有单元测试继续通过；
- 新运行时不需要反向解析 TSV。

Codex 每日 token 改动和多看板运行时的边界如下：

- `CodexLocalSource`、Codex 业务模型和 `KindleTextRenderer` 按 `wiki/06` 演进；
- `CodexDashboardTask` 只调用这些最新业务接口并包装为 TaskBuildResult；
- PageStore 和 PlaylistScheduler 不导入 `SessionMetrics`、`daily_model_tokens` 或任何 Codex 字段；
- `wiki/06` 增加顶部汇总行后仍保持已验证的 24px；内容超高时由 Codex Renderer 限制行数或次要汇总，而不是回落到未验证字号；
- Codex 完整 rollout 解析若接近 `timeout_seconds`，先实测并调整 Codex 任务 timeout；通用调度器不针对 Codex 增加特殊分支。

Codex 推荐初始策略：

```text
collect interval: 60s
timeout: 20s
block: 60s
min page: 30s
max pages: 1
```

## 16. Reddit 订阅任务设计

### 16.1 数据源

外部命令：

```sh
/opt/anaconda3/envs/college/bin/python \
  scripts/show_reddit_subscription_status.py \
  --recent-runs 30 \
  --recent-tasks 30 \
  --format json
```

任务只关注根对象的：

```text
generated_at
summary
subscriptions
```

`subscriptions` 必须是数组。单条记录允许 `last_run = null`，不能因为一个订阅缺少最近运行而让整页失败。

### 16.2 归一化模型

建议保留：

```python
@dataclass(frozen=True)
class RedditSubscription:
    subscription_id: str
    source_key: str
    enabled: bool
    interval_seconds: int
    next_run_at: datetime | None
    last_successful_run_at: datetime | None
    last_run_status: str
    new_document_count: int
    updated_document_count: int
    failed_item_count: int
    cumulative_post_count: int
    error: str | None
```

看板总览建议保留：

```text
subscription_count
enabled_subscription_count
due_subscription_count
active_task_count
subscribed_community_post_count
```

所有输入时间统一解析为 timezone-aware UTC，Renderer 再根据任务配置转换到本地时区。不能混用 naive datetime。

### 16.3 排序

监控看板优先暴露异常，建议稳定排序：

1. 有 error 或 `failed_item_count > 0`；
2. 最近运行状态为 `failed` 或 `partial`；
3. `running`；
4. 已到期但未运行；
5. 距上次成功时间最久；
6. `source_key` 字典序。

排序必须完全由 Reddit 任务实现，PlaylistScheduler 不接触这些字段。

行内 `RESULT` 表示该订阅 `last_run.status`，使用固定映射：

```text
completed -> DONE
running   -> RUN
failed    -> FAIL
partial   -> PART
null      -> NONE
```

顶部 `ACTIVE` 必须直接使用根对象 `summary.active_task_count`，不能通过 `subscriptions[].last_run.status == running` 推导。两者语义不同：前者表示当前活动任务，后者只表示订阅记录中的最后一次 Run 仍标记为 running。

`NEXT` 和 `LAST` 分别使用 `next_run_at`、`last_successful_run_at` 转为本地绝对时间 `DD-HH:MM`；没有记录时显示 `--`。不要在持久 PageSpec 中保存 `7h` 这样的相对时间，否则采集失败后旧页面会持续显示错误的相对年龄。

`NEW/UPD` 来自最近一次 `last_run`；`TOTAL` 来自 `cumulative_post_count`。错误数由订阅中的 `error` 和 `failed_item_count` 计算，不能假设根对象 `summary` 一定提供该字段。

### 16.4 页面格式

当前每页最多 12 条，完整页面示意：

```text
REDDIT SUBSCRIPTIONS / DATA 07-14 10:23  1/2
19 ON / 0 ACTIVE / 0 ERR / 5380 POSTS
SOURCE          RESULT  FREQ  NEXT      LAST      N/U  TOTAL
------------------------------------------------------------------
AMD_Stock       DONE      8h  14-18:44  14-10:44  1/3    329
Biotechplays    DONE      8h  14-18:40  14-10:40  0/3     59
Daytrading      RUN       4h  10-18:49  10-01:20  0/0    501
...
```

第一版优先显示：

- 社区名称；
- 最近一次 Run 的结果；
- 执行频率与下次计划运行时间；
- 上次成功的绝对时间；
- 最近新增/更新数量；
- 累计帖子数；
- 错误标记。

订阅 ID、来源类型、排序模式、最早帖子时间默认不显示。字段取舍和列宽只能由 Reddit Renderer 根据真机宽度决定，不能由通用播放器拼接。

每页都必须包含标题、源数据生成时间、页码和摘要，使单独看到任意一页时仍然可理解。页头必须写 `DATA`，明确这是数据时间而不是当前播放时间；采集失败继续播放旧 PageSet 时，旧时间仍然真实表达页面新鲜度。

当前样例有 19 个订阅，`rows_per_page = 12` 时生成 2 页，符合 `max_pages = 2`。若未来超过 24 条，Renderer 按排序只展示前 24 条，并在页头标记 `+N HIDDEN`。

### 16.5 建议策略

```text
collect interval: 300s
timeout: 90s
block: 30s
min page: 15s
max pages: 2
rows per page: 6
```

四页时每页停留 30 秒；两页时每页停留 60 秒；一页时停留 120 秒。

## 17. 设备断线与恢复

USBNetwork 断开不能影响采集：

- CollectorScheduler 继续按照周期更新 PageStore；
- PlaylistScheduler 调用 KindleSink 失败后停止推进已显示时间；
- 每隔 `offline_retry_seconds` 尝试恢复；
- 断线期间不把页面标记为已显示；
- 首次失败时记住当前任务 ID、放弃断线前固定的旧 PageSet，并设置 `force_full_refresh = true`；
- 每次重试都从 PageStore 重新读取该任务最新 PageSet，并从 page 1 开始，不能从旧 page 2/4 接着播放；
- 恢复后的第一次成功发送使用 FULL；
- 恢复后先连续完成这个最新任务块，再回到正常加权轮询；任务第一次被选中时已经结算权重，失败重试期间不能再次增加或扣减权重；
- 一次 SSH 失败不能退出主服务。

这样重新插入 Kindle 后不会先播放断线前缓存的旧 Reddit 第 2 页，而是从最新有效页面块重新开始。

## 18. 服务生命周期与 CLI

正式入口：

```sh
./scripts/kindle-dashboard.sh start
./scripts/kindle-dashboard.sh status
./scripts/kindle-dashboard.sh stop
./scripts/kindle-dashboard.sh once
```

建议行为：

### `start`

- 校验配置、SSH key 和任务工厂；
- 在后台启动 `python -m kindle_display.cli run --config ...`；
- 写 PID 和日志到 `run_dir`；
- 若 PID 对应进程仍存活则拒绝重复启动。

### `status`

- 检查 PID；
- 读取 `run_dir/status.json`；
- 输出当前任务/页、最近成功显示、上次全刷、每个任务最后采集成功和错误。

### `stop`

- 发送 SIGTERM；
- 服务停止接受新采集；
- 取消或终止外部子进程；
- 等待当前状态写入后退出；
- 超时才由 Shell 报告，不默认使用 SIGKILL。

### `once`

- 默认采集所有启用任务；
- 生成 PageStore；
- 按配置播放列表选择第一个可用任务的第一页；
- 使用 FULL 发送一次后退出；
- 支持后续参数 `--task` 和 `--page`，便于真机验证指定页面。

开发预览建议由 Python CLI 提供：

```sh
python -m kindle_display.cli preview --task codex --format text
python -m kindle_display.cli preview --task reddit-subscriptions --format text
python -m kindle_display.cli preview --task reddit-subscriptions --format json
```

## 19. 可观测性

日志至少包含以下结构化信息：

```text
collector_started task=reddit-subscriptions
collector_succeeded task=reddit-subscriptions pages=4 changed=true duration_ms=...
collector_failed task=reddit-subscriptions error_type=timeout
display_started task=reddit-subscriptions page=2/4 refresh=normal
display_succeeded task=reddit-subscriptions page=2/4 duration_ms=...
display_failed task=reddit-subscriptions page=2/4 error_type=ssh
full_refresh_due elapsed_seconds=...
```

`status.json` 建议使用原子写，包含：

```json
{
  "service_started_at": "...",
  "current_display": {
    "task_id": "reddit-subscriptions",
    "page_number": 2,
    "page_count": 4,
    "generation": 5,
    "displayed_at": "...",
    "refresh_mode": "normal"
  },
  "last_full_refresh_at": "...",
  "tasks": {}
}
```

日志和状态文件不能记录 SSH 私钥、环境变量内容或完整外部 JSON。

## 20. 实施顺序

必须按以下顺序开发，保持每一步可运行：

### 阶段零：刷新 profile 真机探针

1. 先为现有发送器增加一个只用于诊断的 NORMAL 候选模式；
2. 连续发送两个差异明显的整页测试内容；
3. 验证 `clean -> -c` 是否没有明显黑白全闪；
4. 验证第二页能够覆盖第一页面，不发生不可接受的文字叠加；
5. 再用 `flash_clean -> -f -c` 确认残影可以清除；
6. 把通过真机验证的映射固化为 KindleSink profile 和测试说明；
7. 如果 `clean` 不通过，暂停 NORMAL 功能实现，先单独寻找可用 FBInk profile，不能在主运行时里试错。

### 阶段一：运行时模型与配置

1. 新增 PageSpec、PageSet、策略 dataclass；
2. 新增 TOML 加载和严格校验；
3. 新增 PageStore；
4. 完成纯单元测试，不连接 Kindle。

### 阶段二：播放器与刷新模式

1. 实现带 fake clock 的 PlaylistScheduler；
2. 实现平滑加权轮询、连续任务块和页面时间分配；
3. 实现代际固定；
4. 实现普通/完整刷新状态机；
5. 把阶段零通过的 profile 接入 `kindle-display.sh --refresh-profile`；
6. 用 FakeSink 验证调度状态，不用 FakeSink 替代阶段零的真机结论。

### 阶段三：Codex 接入

1. 先完成或合并 `wiki/06-codex-daily-token-usage-design.md` 对 Source、业务模型和 Renderer 的修改；
2. KindleTextRenderer 增加 `render_page()`；
3. 保留 `render_layout()` 兼容输出；
4. 新增 CodexDashboardTask；
5. 确认预览、单次发送、每日 token 统计及最新 Renderer 测试不回归；
6. 实测完整 rollout 解析耗时低于 Codex timeout，并记录样本规模；
7. 用统一服务只启用 Codex，完成真机普通/全刷测试。

### 阶段四：采集调度与外部命令

1. 实现 CollectorScheduler；
2. 实现 CommandJsonSource；
3. 完成超时、非零退出、非法 JSON、输出上限测试；
4. 确认慢命令不阻塞 FakeSink 页面播放。

### 阶段五：Reddit 任务

1. 建立归一化模型和 schema 校验；
2. 实现异常优先排序；
3. 实现 6 行分页及页码；
4. 用固定 JSON fixture 做快照测试；
5. 用真实外部命令做本机集成测试；
6. 两个任务一起完成真机连续轮播。

### 阶段六：统一入口

1. 新增 `kindle-dashboard.sh`；
2. 实现 `start / stop / status / once`；
3. 保留 `codex-dashboard.sh` 作为兼容入口；
4. 更新 README 和新 Mac 部署文档；
5. 稳定运行后再决定是否移除旧 Shell 循环。

## 21. 自动化验证方案

### 21.1 模型与配置测试

必须覆盖：

- 合法 TOML 能构建两个任务；
- 缺失 task ID、重复 ID、未知 kind 报错；
- task_order 引用不存在任务时报错；
- `max_pages * min_page_seconds > block_seconds` 报错；
- `weight` 不在 1～10 内时报错；
- Shell 字符串而不是 argv 数组时报错；
- `${HOME}` 和 `~` 路径正确展开；
- 未知 refresh profile 报错；
- 缺少或非法 `display_timeout_seconds` 报错；
- 相对 cwd、相对 argv[0] 和非正周期/timeout 报错；
- Reddit 页面容量小于 max_subscriptions 报错；
- 未知字段报错。

### 21.2 PageStore 测试

必须覆盖：

- 首次 publish 得到 generation 1；
- 内容变化递增 generation；
- 内容不变不递增 generation，但更新最后成功时间；
- 采集失败不替换 PageSet；
- 两个任务互不影响；
- 并发 publish/read 不暴露半成品；
- 过期 CollectionLease 的晚到成功结果不能发布；
- `to_thread()` 超时期间保持 collecting，新任务不能取得 lease；
- release_collection 只释放匹配的 active_run_id；
- 磁盘缓存使用原子替换并能重新加载；
- 非法页数拒绝发布。
- 重复 page_id、未知 font_role、奇数字号、TAB、NUL、`U+001E` 和超大文本均拒绝发布；

### 21.3 PlaylistScheduler 测试

使用 FakeClock 和 RecordingSink，禁止依赖真实 sleep。必须覆盖：

1. `Codex(weight=2, 1页) + Reddit(weight=1, 4页)` 顺序为 `C, R1, R2, R3, R4, C`；
2. Reddit 两页时在 120 秒预算下各 60 秒；
3. 121 秒四页分配为 `31, 30, 30, 30`；
4. Reddit 播放中途发布新 generation，本轮仍播放旧 generation；
5. 下一轮 Reddit 使用新 generation；
6. Codex 每分钟更新不会重置 Reddit 页码；
7. 未采集成功的任务被跳过；
8. 所有任务无页面时不调用 Sink；
9. 相同页面且未到全刷时间时不重复发送；
10. 相同页面但全刷到期时重新发送；
11. FULL 失败后下次仍然请求 FULL；
12. 断线恢复后从失败任务最新 PageSet 的 page 1 开始并执行 FULL；
13. 相同权重时按 task_order 稳定轮询；
14. `weight=3/1/1` 长期选择次数符合 3:1:1，任务内部页面始终连续；
15. 暂无 PageSet 的任务不累积权重，恢复后不会连续补播。
16. 加权算法连续选择同一任务时，两个任务块分别重新固定 generation，但权重只各结算一次。

### 21.4 CollectorScheduler 测试

必须覆盖：

- 不同采集周期独立触发；
- 正常任务按固定计划 tick 启动；
- 慢任务跳过错过的 tick，但不重置整个周期或立即追赶；
- 一个慢任务不阻塞另一个任务；
- 同一任务不会重叠执行；
- 超时后子进程被清理；
- 外部命令被取消时仍执行 terminate/kill/wait；
- `to_thread()` 超时后结果被废弃，且底层 Future 完成前不启动同任务；
- 失败保留最后成功页面；
- 非法 JSON、非零退出码和流式 stdout 超限被正确记录；
- stderr 被截断且不泄露环境变量；
- 停止服务时正在运行的子进程被回收。

### 21.5 任务 Renderer 测试

Codex 必须保留现有断言：

- 中文/英文宽度计算；
- CJK 奇数宽度标题补 `.`；
- `wiki/06` 定义的 TASK、MODEL、STA、CTX、TOK、C L/T 等列对齐；
- 一页一条 ttf_page；
- Renderer 使用固定 24px，并保证最大逻辑行数能完整容纳页面；
- 每日 token、lifetime token 和顶部模型汇总的新增测试全部通过。

Reddit 必须覆盖：

- `subscriptions` 为 0、1、6、7、19、24、25 条；
- 19 条生成 2 页；
- 每页都包含页码和摘要；
- `last_run = null`；
- error/failed/running/due 排序；
- 顶部 ACTIVE 只来自 `summary.active_task_count`；
- 行内 RESULT 只来自 `last_run.status`；
- LAST 使用绝对时间，旧 PageSet 不包含会冻结的相对年龄；
- UTC 转 Asia/Shanghai；
- 超过最大条数显示 `+N HIDDEN`；
- 中文或长 subreddit 名称截断后列仍对齐；
- 每页只产生一个 PageSpec。

### 21.6 本机集成命令

实现完成后至少执行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
bash -n scripts/*.sh
git diff --check
```

再执行不连接 Kindle 的预览：

```sh
PYTHONPATH=src python3 -m kindle_display.cli preview \
  --config config/dashboard.toml --task codex --format text

PYTHONPATH=src python3 -m kindle_display.cli preview \
  --config config/dashboard.toml --task reddit-subscriptions --format text
```

真实 Reddit 命令集成检查：

```sh
cd /Users/liubin/Projects/AlphaDecisionTaskManager
/opt/anaconda3/envs/college/bin/python \
  scripts/show_reddit_subscription_status.py \
  --recent-runs 30 --recent-tasks 30 --format json
```

检查退出码为 0、stdout 是 JSON，并确认任务能在不创建 `tmp.json` 的情况下生成 PageSet。

## 22. Kindle 真机验证方案

自动化测试通过后，按顺序进行以下真机测试。

### 22.1 单页渲染回归

1. 只启用 Codex；
2. `once` 使用 FULL；
3. 确认字体、字号、中文、列宽和当前已验收效果一致；
4. 用 verbose 日志确认只有一次 SSH 和一次 FBInk TrueType 调用。

### 22.2 普通刷新视觉验证

1. 连续发送两个内容不同的测试页面；
2. 两次都使用 NORMAL；
3. 确认没有明显黑白全屏闪烁；
4. 确认旧文字没有直接叠加到新页面；
5. 记录可接受的轻微残影程度。

本节是阶段零结论在完整运行时中的回归测试，不是第一次验证 NORMAL。若 `-c` 在该 FBInk/K4 组合上仍产生明显闪烁，不要直接删除 `-c`。先单独验证 framebuffer 清理和波形参数，再修改正式 profile；无清理绘制会造成页面内容严重重叠。

### 22.3 周期全刷验证

临时将完整刷新周期设为 3 分钟：

1. 前几次换页均为 NORMAL；
2. 第一次超过 3 分钟后的页面边界使用 FULL；
3. FULL 有预期黑闪；
4. 累积残影被明显清除；
5. 后续重新回到 NORMAL；
6. FULL 计时从成功完成时重新开始。

### 22.4 连续任务块验证

配置 Codex 一页、Reddit 两页，确认实际顺序严格为：

```text
Codex -> Reddit 1/2 -> Reddit 2/2 -> Codex
```

不得出现：

```text
Codex -> Reddit 1/2 -> Codex -> Reddit 2/2
```

### 22.5 代际一致性验证

在 Reddit 1/2 显示期间触发一次新采集：

- 当前 2/2 仍显示旧 generation；
- 下一轮 1/2 才切换新 generation；
- 日志明确打印 generation。

### 22.6 断线恢复验证

1. 服务持续运行时拔下 Kindle；
2. 等待至少一个 Codex 和 Reddit 采集周期；
3. 确认服务仍运行且 PageStore 继续更新；
4. 重新连接并恢复 USBNetwork；
5. 第一次成功显示使用最新 PageSet 和 FULL；
6. 后续恢复正常连续轮播。

## 23. 完成验收标准

只有同时满足以下条件，才算多看板运行时完成：

- Codex 与 Reddit 按各自周期独立采集；
- 慢速或失败的 Reddit 命令不影响 Codex 页面播放；
- 两个任务通过统一 Shell 启停；
- Reddit 多页连续显示，页内数据来自同一 generation；
- 实际页面停留时间符合配置计算；
- 不同任务块的长期出现次数符合 weight；
- 数据更新不重置播放游标；
- 采集失败继续显示最后成功结果；
- 普通换页不再出现当前每页一次的明显黑闪；
- 周期 FULL 能清除累积残影；
- Kindle 断线不会停止采集，重连后自动恢复；
- 每个页面仍然只使用一次 TrueType 绘制；
- Codex 当前字体、中文、宽度和对齐效果无回归；
- 单元测试、Shell 语法检查和真机测试全部通过。

## 24. 后续扩展约束

新增第三个看板时，只允许：

1. 新增一个 DashboardTask；
2. 新增其业务 Snapshot 和 TaskRenderer；
3. 在 TOML 注册任务和播放顺序。

不应修改 PlaylistScheduler、PageStore 或 KindleSink。若新增任务必须在这些通用模块里增加业务类型判断，说明抽象边界已经被破坏，应先修正接口。

第一版已经通过 `weight` 支持不同任务块的相对出现频率。若未来需要按精确墙钟时间播放，可以在不打断任务块的前提下增加 `revisit_interval_seconds`；它只能在任务块边界参与选择，不能抢占正在播放的 PageSet。

例如配置权重后可以产生：

```text
codex -> reddit -> codex -> build-monitor
```

但权重只影响“下一个任务块是谁”，不能把其他主题插入一个尚未播放完成的 PageSet。
