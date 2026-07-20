# KindleDisplay

KindleDisplay 把闲置的 Kindle 变成一块低刷新率信息看板。程序在 Mac 上采集状态、生成完整中文页面，再通过 USBNetwork 发送到 Kindle 循环显示。

目前内置两类看板：

- **Codex 状态**：近期活跃项目与 Session、模型、运行状态、上下文占用、Token、Cache 和费用估算；
- **Reddit 订阅**：订阅源运行结果、执行周期、下次运行、上次成功、新增/更新数量和累计帖子数。

数据采集和页面轮播彼此独立。某次采集失败时，Kindle 会继续显示上一次成功结果；USB 暂时断开也不会终止服务，重新连接后会自动恢复发送。

## 使用前准备

你需要：

- 一台已安装 KUAL、USBNetwork 和 FBInk 的 Kindle；
- macOS 与 Kindle 之间可以通过 SSH 连接；
- Mac 上安装 Python 3.11 或更高版本；
- Kindle 中已安装项目使用的 Sarasa Mono SC 中文字体。

第一次连接 Kindle 或更换 Mac，请先完成 [新 Mac 安装与连接指南](wiki/03-new-mac-setup.md)。

如果会频繁插拔 Kindle，建议在首次配置后安装 USBNetwork 地址修复服务：

```sh
./scripts/install-kindle-usbnetwork-repair.sh
```

它会在 Mac 开机后自动运行，并每 5 分钟检查一次 Kindle 的 RNDIS 接口；需要时恢复为 `192.168.15.201/24`。它不启动 Dashboard；Dashboard 仍按需使用 `start` 启动。

## 快速开始

在项目根目录创建本机配置：

```sh
cp config/dashboard.example.toml config/dashboard.toml
```

如果 Reddit 项目或 Python 环境位于其他路径，修改 `config/dashboard.toml` 中 Reddit 任务的 `cwd` 和 `argv`。

设置 Kindle 地址和 SSH 私钥：

```sh
export KINDLE_HOST=192.168.15.244
export KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519"
```

先检查配置和数据采集。该命令不会修改 Kindle 屏幕：

```sh
./scripts/kindle-dashboard.sh check
```

检查成功后启动常驻看板：

```sh
./scripts/kindle-dashboard.sh start
```

正常情况下终端会返回：

```text
Dashboard started (PID 12345, log: /tmp/kindle-display/kindle-dashboard.log).
```

程序随后进入后台运行，关闭当前终端不会停止看板。

## 日常操作

查看运行状态：

```sh
./scripts/kindle-dashboard.sh status
```

停止看板：

```sh
./scripts/kindle-dashboard.sh stop
```

查看实时日志：

```sh
tail -f /tmp/kindle-display/kindle-dashboard.log
```

只在终端预览页面，不发送到 Kindle：

```sh
./scripts/kindle-dashboard.sh preview --task codex --format text
./scripts/kindle-dashboard.sh preview --task reddit-subscriptions --format text
```

向 Kindle 一次性发送指定页面：

```sh
./scripts/kindle-dashboard.sh once --task codex
./scripts/kindle-dashboard.sh once --task reddit-subscriptions --page 1
```

`once` 发送完成后退出；`start` 才是持续采集和轮播模式。

## 默认显示效果

默认配置下：

```text
Codex          120 秒（最多 8 页）
Reddit 第 1 页 15 秒
Reddit 第 2 页 15 秒
然后继续循环
```

Codex 每 60 秒重新采集，Reddit 每 5 分钟重新采集。采集周期不会影响当前页面的停留和播放顺序。

普通换页采用淡入淡出的局部清理方式；每 30 分钟进行一次完整刷新，以清除可能累积的电子墨水残影。

实际周期、任务顺序和每页行数都可以在 `config/dashboard.toml` 中调整。

## 配置说明

本机配置文件 `config/dashboard.toml` 不会提交到 Git。常用配置包括：

- `[kindle]`：Kindle 地址、SSH 超时和刷新方式；
- `[playlist]`：任务播放顺序与完整刷新周期；
- `[tasks.collection]`：任务的数据采集周期和超时；
- `[tasks.display]`：任务块时长、最短页面停留时间、最大页数和播放权重；
- `[tasks.source]`：外部数据命令的工作目录和参数；
- `[tasks.options]`：每种看板自己的显示选项。

设备相关配置也可以通过环境变量覆盖：

```sh
export KINDLE_HOST=192.168.15.244
export KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519"
export KINDLE_DISPLAY_RUN_DIR=/tmp/kindle-display
export KINDLE_DISPLAY_CONFIG=/absolute/path/to/dashboard.toml
```

## Kindle 暂时断开

拔下 Kindle 后不需要停止服务。采集器仍会更新本机数据；重新连接并恢复相同的 USBNetwork 地址后，播放器会自动重试并从最新任务页面恢复。

如果长时间没有恢复，可依次检查：

```sh
ping -c 1 192.168.15.244
./scripts/kindle-dashboard.sh status
tail -n 50 /tmp/kindle-display/kindle-dashboard.log
```

## 常见问题

### `Kindle SSH key is not readable`

确认 `KINDLE_SSH_KEY` 指向存在且可读的私钥：

```sh
export KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519"
```

### Kindle 没有显示内容

先测试网络和单页发送：

```sh
ping -c 1 "$KINDLE_HOST"
./scripts/kindle-dashboard.sh once --task codex
```

如果仍然失败，按照 [新 Mac 安装与连接指南](wiki/03-new-mac-setup.md) 检查 USBNetwork、SSH、FBInk 和中文字体。

频繁插拔时，确认已安装自动地址修复服务：

```sh
sudo launchctl print system/com.kindle-display.usbnetwork-repair
```

### Reddit 数据采集失败

检查 `config/dashboard.toml` 中的工作目录、Python 可执行文件和脚本路径，然后运行：

```sh
./scripts/kindle-dashboard.sh preview --task reddit-subscriptions --format text
```

### 可以同时运行旧的 Codex 脚本吗？

不可以。`scripts/codex-dashboard.sh` 是兼容旧版本的入口，不能与 `scripts/kindle-dashboard.sh` 同时运行。

## 更多文档

- [Kindle K4 初始化](wiki/01-kindle-k4-provisioning.md)
- [Kindle 页面发送协议](wiki/02-kindle-display-protocol.md)
- [新 Mac 安装与连接](wiki/03-new-mac-setup.md)
- [中文表格渲染实践](wiki/04-cjk-table-rendering.md)
- [多看板运行时设计](wiki/05-multi-dashboard-runtime-design.md)
- [Codex 每日 Token 与费用统计](wiki/06-codex-daily-token-usage-design.md)
- [接入新的数据看板](wiki/07-adding-a-dashboard-task.md)
