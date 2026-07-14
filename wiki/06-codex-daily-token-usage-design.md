# Codex 当日 Token 与模型归属设计

## 1. 目标与口径

在现有 Codex 状态页中增加两类数据：

1. 每个 session 的 `今日 token / lifetime token`；
2. 顶部按模型汇总的今日 token 消耗。

顶部模型汇总固定为全局总计：统计所有当天有 token 事件的 rollout，不受 Kindle 页面最多展示 3 个项目、每个项目最多展示 3 个 session 的限制。

`total_token_usage` 是 session 创建以来的累计计数器，`last_token_usage` 是上下文窗口相关数据，不能用于日消耗统计。日消耗唯一以相邻两条 `token_count` 的 `total_token_usage` 差分计算。

时间统一按 `Asia/Shanghai` 归属。一个 delta 归属到后一条 `token_count.timestamp` 所在的本地日期。这样跨日 session 会使用日界线前的累计值作为基线，不需要在零点另存快照。

模型归属是日志推断，不是服务端账单数据：解析 rollout 时维护当前模型，模型来自 `thread_settings_applied.thread_settings.model`，并以 `turn_context.model` 兜底；每个 token delta 归属给产生该 token 事件时的当前模型。没有已知模型的 delta 记为 `unknown`，不猜测。模型在两个 token 事件之间切换时，delta 仍归给切换后模型；这是当前可获得数据下接受的近似，页面和 JSON 都应保留 `inferred` 语义。

## 2. 数据源与解析边界

继续以 `~/.codex/sessions/**/rollout-*.jsonl` 为唯一规范数据源。现有 `CodexLocalSource` 已从这里读取 session 元信息、生命周期和最新 token 记录。虽然同目录的 `token_count.jsonl` 更小，但其中没有模型设置事件；不能把两个文件的 token 记录同时相加，也不能只依赖它完成按模型统计。

当前按文件 mtime 选取“今天仍有更新的 rollout”的策略可以保留，因而能够找到创建于旧日期、今天继续使用的 session。对每个候选 rollout，日统计必须完整顺序解析，而不是复用现有的 512 KiB tail：tail 无法取得零点前的累计基线，也可能漏掉早先的模型设置事件。

解析器应容忍活跃 JSONL 最后一行写到一半，跳过该行；出现非单调的累计值时，不做负数 delta，记录诊断并把该区间作为新的基线。这避免日志重置或损坏使日合计变成负数。

## 3. 计算流程

每个 rollout 文件按日志顺序执行以下状态机：

```text
current_model = unknown
previous_total = none

for event in rollout:
  if event is thread_settings_applied with a model:
      current_model = model
  elif event is turn_context with a model:
      current_model = model
  elif event is token_count:
      current_total = event.total_token_usage
      delta = current_total - previous_total
      if previous_total is absent:
          delta = current_total                 # session 的第一条累计记录
      if delta is valid and event timestamp is today:
          session.today += delta
          daily_by_model[current_model] += delta
      previous_total = current_total
```

`delta` 应保留 input、cached input、output、reasoning output 和 total 五个原始维度；展示中的 token 数默认使用 `total_tokens`。`cached_input_tokens` 是 input 的子集，绝不能与 input 或 total 再相加。

同一 session 的 latest/lifetime 数据仍取最后一个有效 `token_count`。其 latest model 优先用 rollout 状态机的最后模型，不再把 SQLite `threads.model` 当作历史归属依据；SQLite 只继续提供标题和 cwd 等可变元数据。

## 4. 代码改动

第一版保持现有三层分工，不新增显示层读取文件的捷径：

| 位置 | 改动 |
| --- | --- |
| `sources/codex_local.py` | 增加完整 rollout 解析器，返回全量 session 列表和全局 `daily_model_tokens`；现有 tail parser 仅可保留给不需要日统计的快速状态读取。 |
| `models.py` | `SessionMetrics` 增加 `today_tokens`；新增 source 返回对象（包含 `sessions` 与全局模型汇总）；`CodexStatusSnapshot` 增加不可变的 `daily_model_tokens`。`as_dict()` 同时暴露这两项。 |
| `dashboards/codex_status.py` | 仅对 session 做项目分组和数量限制；把 source 给出的全局模型汇总原样放入 snapshot，禁止对已截断的展示 session 重算。 |
| `renderers/kindle_text.py` | 只格式化新字段，不解析 rollout，也不判断模型归属。 |
| `tests/` | 使用跨日、模型切换、未知模型、累计倒退和活跃文件半行等固定 JSONL fixture 验证统计。 |

初版可以在每次采集时完整读取候选 rollout，先保证统计正确性。若实测一分钟一次的读取成为瓶颈，再以 `path + inode + byte offset + parser state` 做追加式缓存；缓存必须能在文件截断、inode 改变和进程重启时退化为完整重建，不能成为统计真相的唯一来源。

## 5. Kindle 展示

表格列仍保持单行 session 信息，但压缩 task/model/state 区域，为每日 token 腾出宽度：

```text
TASK  MODEL  STA CTX    TOK   C L/T
> task  5.6-terra  R  72%  2.1M/117.6M  94/93
```

具体规则：

1. `TASK_MODEL_GAP` 与 `MODEL_STATE_GAP` 都从 4 缩为 2；
2. 状态列宽改为 3，表头为 `STA`；行内通过已有 `_state_label()` 显示 `R`、`D`、`I`、`S`、`A`，不再显示 `RUN`、`DONE` 等完整状态；
3. `TOK` 保持一个字段，值为 `today/total`，例如 `2.1M/117.6M`；字段宽度按最长可显示值设置，溢出时采用现有单位缩写而不是截掉右侧总量；
4. `C L/T` 继续表示 `last cache percent / lifetime cache percent`，与 token 字段无关；
5. 标题行后接状态缩写汇总，例如 `CODEX STATUS / 11:19 / 1 R / 1 D`；下一行专门显示模型今日 token，例如 `gpt-5.6-terra 2.1M / gpt-5.6-sol 0.7M`。模型按今日 token 降序，使用完整的稳定模型名。若模型太多而一行放不下，继续拆分模型行，不能静默裁剪模型名或金额。

现有简版 `render()` 同样应把状态显示为缩写；它不必强行展示完整模型汇总，以免破坏 25 列的简页布局。完整 `render_layout()` 是本次指标展示的正式载体。

## 6. 验证标准

完成后至少验证：

1. 跨日 session：7 月 14 日的结果等于该日最后 total 减去 7 月 13 日最后 total；
2. 日内多个 token 事件：按每条相邻差分求和，与当天首尾累计差一致；
3. 已知模型切换：切换后的 token delta 出现在新模型汇总；
4. 无模型事件：总 token 仍正确，模型汇总进入 `unknown`；
5. 全局所有模型当日合计等于 source 解析出的全部 session 当日 token 合计，而不是等于 Kindle 当前展示 session 的合计；
6. 渲染断言覆盖 `STA`、`R/D/I`、`today/total` 与顶部模型汇总，并检查一页的字号和行数仍满足 Kindle 布局约束。

完成前用真实 `~/.codex/sessions` 样本做一次只读核对：同一日的 session 合计应等于按模型合计；对模型切换前后分别抽查一段 rollout 的 `thread_settings_applied`、`turn_context` 和 `token_count` 时间序列。
