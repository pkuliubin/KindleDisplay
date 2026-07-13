# Kindle 4 看板推送与显示规范

## 适用范围

本规范定义 Mac 如何向已配置完成的 Kindle 4 推送低频状态内容。当前实现只传输 UTF-8 文字，使用 USBNetwork 上的 SSH 和 Kindle 上的 FBInk 直接刷新电子墨水屏。

它不是 VNC、AirPlay 或视频副屏。刷新一次是完整清屏后绘制一次，适合一分钟或更慢的节奏。

本文的 `./kindle-display.sh` 和 `./kindle-dashboard-example.sh` 命令假设当前目录为：

```sh
cd /Users/liubin/Projects/DailyAI/kindle_k4_mod
```

## 当前运行链路

```text
data collector / dashboard formatter (Mac)
    -> stdin or command argument
kindle-display.sh
    -> SSH with dedicated Ed25519 key
Kindle /mnt/us/fbink
    -> /proc/eink_fb/update_display (landscape)
    -> E-Ink screen
```

涉及文件：

| 文件 | 职责 |
| --- | --- |
| `kindle-display.sh` | 单次发送器；设置横屏、清屏并渲染文本 |
| `kindle-dashboard-example.sh` | 每 60 秒生成一份 Mac 状态并调用发送器 |
| `kindle_ed25519` | SSH 私钥；不允许提交到项目仓库 |

## 前置状态

发送前必须全部成立：

1. Kindle 在 `KUAL -> USBNetwork` 中已启用，并重新插过 USB。
2. Mac 识别到 RNDIS 网卡，并配置为 `192.168.15.201/24`。
3. Kindle 地址为 `192.168.15.244`，SSH 可用。
4. Kindle 上存在可执行的 `/mnt/us/fbink`。

快速检查：

```sh
ping -c 1 192.168.15.244
ssh -i kindle_ed25519 -o BatchMode=yes root@192.168.15.244 'test -x /mnt/us/fbink && echo ready'
```

若 Mac 网卡被重置为 `169.254.*`，需要把实际 RNDIS 接口重新设置为固定地址：

```sh
sudo ifconfig en7 inet 192.168.15.201 netmask 255.255.255.0 up
```

`en7` 不是固定名称，必须以 `ifconfig` 或 macOS 网络设置看到的接口为准。

## 单次推送 API

`kindle-display.sh` 支持两种输入形式。

### 管道传入多行内容

```sh
printf 'BUILD\nStatus  PASS\nVersion  1.2.3\n' | ./kindle-display.sh
```

这是正式项目的推荐形式。实际换行会由 FBInk 渲染为多行。

### 传入单个参数

```sh
./kindle-display.sh 'Build: PASS'
```

不要在普通引号字符串中写 `\n` 并期待换行：它会被当成两个可见字符 `\` 和 `n`。多行内容使用 `printf`、heredoc 或文件管道。

### 环境变量覆盖

脚本默认读取同目录 `kindle_ed25519` 并连接 `192.168.15.244`。在正式项目中可显式指定环境变量；它们必须作用于脚本进程：

```sh
printf 'hello\n' | KINDLE_HOST=192.168.15.244 KINDLE_SSH_KEY=/absolute/path/to/kindle_ed25519 ./kindle-display.sh
```

## 当前渲染参数与含义

发送器的远端核心命令等价于：

```sh
echo '14 2' > /proc/eink_fb/update_display
/mnt/us/fbink -q -c -S 3 -x 1 -y 1 "$(cat /tmp/kindle-display.txt)"
```

| 项目 | 当前值 | 说明 |
| --- | --- | --- |
| 方向 | `14 2` | K4 驱动横屏。`0` 是竖屏，`2` 是已验证的正向横屏。 |
| 清屏 | `-c` | 每次完整清屏，消除残影，最适合完整状态页。 |
| 字号 | `-S 3` | 本机实际诊断为 `24 x 24` 点阵字。`-S 2` 在此 FBInk/K4 组合上仍接近默认大小。 |
| 起点 | `-x 1 -y 1` | 给边框留出一列边距。 |
| 日志 | `-q` | 安静模式，避免常驻任务写出大量无用日志。 |

切换方向属于设备显示状态而不是永久系统偏好。当前 `kindle-display.sh` 每次渲染前都显式设为横屏，因此重启或被 Kindle UI 改回竖屏后，下一次推送仍会恢复横屏。

## 字体、布局和方向的最佳实践

### 字体

- 当前 `-S 3` 是状态文字的基线，横屏约 25 列、33 行，适合标题加 6 到 12 行数据。
- `-S 4` 或更大只适合少量关键数字；先在真机试排，不能假定桌面终端宽度。
- FBInk 当前二进制默认 IBM 点阵字体。英文、数字和短状态非常清晰；正式项目若必须大量显示中文，应先单独验证字体覆盖和字形质量，不能直接假设点阵字体完整支持中文。
- 固定字段名和数值列，避免每分钟内容宽度变化造成视觉跳动。长字符串在 Mac 端截断或换行，不要把整个日志直接推到 Kindle。

### 横屏

- 横屏是本项目的默认方向，阅读距离和信息密度更合适。
- 不要仅把字符串旋转或传递文字 `\n`，必须先切换 K4 的 E-Ink 驱动方向；当前脚本已经处理。
- 如果屏幕物理摆放方向变化，可通过 `echo '14 0' > /proc/eink_fb/update_display` 临时回到竖屏并测试其他驱动方向。不要把未经真机验证的方向值写入正式脚本。

### 刷新节奏

- 60 秒是当前已验证的默认周期。状态无变化时不刷新是更好的正式策略。
- CPU、构建、日历、Agent 状态可 1 到 5 分钟更新；行情或告警建议采用“数据变化/阈值触发 + 最小间隔”，而不是秒级轮询。
- `-c` 会带来一次完整刷新。优先保证可读和无残影；只有在确实需要局部更新时，才对 FBInk 的局部刷新/波形参数做单独真机实验。

### 可靠性

- 写入内容前在 Mac 端完成全部数据聚合和格式化。Kindle 只应接收最终字符串，避免在其低性能系统上运行业务逻辑。
- 把 SSH 连接失败视为可恢复状态，不要因一次 USB 重连就终止长期采集程序。
- 保留最后一份已成功渲染的内容和时间。下一次内容相同则跳过发送，既省电也减少闪烁。
- 不要将私钥、实时凭证或完整错误日志显示在看板上；屏幕和 `ps`/日志都可能被看到。

## 当前示例看板

`kindle-dashboard-example.sh` 是长期循环脚本：启动时立即发送一次，然后每 60 秒刷新。它显示 Mac 时间、运行时间、根分区占用和当前项目 Git 是否有变更。

前台运行：

```sh
./kindle-dashboard-example.sh
```

后台运行：

```sh
nohup ./kindle-dashboard-example.sh > /tmp/kindle-dashboard.log 2>&1 &
```

停止：

```sh
pkill -f kindle-dashboard-example.sh
```

脚本对一次 SSH/显示失败使用 `|| true`，所以 Kindle 断线后不会退出，会在下一分钟重试。正式项目应替换 `{ ... }` 中的内容生成块，保留发送器和失败恢复语义。

## 正式项目的推荐架构

```text
collectors (Git / calendar / servers / market data)
    -> normalized dashboard state
    -> deterministic text formatter
    -> content hash and rate limiter
    -> kindle-display.sh
```

建议将采集、状态归一化、排版和传输分开：

1. **采集器**只负责获取数据，并为每项给出时间戳和健康状态。
2. **格式化器**生成限定行数和列宽的纯文本，不直接调用 SSH。
3. **发送器**复用 `kindle-display.sh`，只负责网络、横屏和 FBInk 渲染。
4. **调度器**以 60 秒为最短周期，同时按内容 hash 去重和对错误做退避。

不要把所有功能堆进一个无限循环 shell 脚本；它适合作为验证和最小可用版本，不适合复杂数据源、凭证管理和可观测性。

## 排障表

| 现象 | 首先检查 | 处理 |
| --- | --- | --- |
| Kindle 显示旧内容 | USBNetwork 是否启用，`ping` 是否成功 | 在 KUAL 启用后拔插 USB，修复 Mac 网卡地址。 |
| SSH 超时 | Mac 是否为 `192.168.15.201/24` | 修正 RNDIS 接口地址，避免 `169.254.*`。 |
| 显示成一行 `\\n` | 输入方式 | 改用 `printf 'a\\nb\\n' | ./kindle-display.sh`。 |
| 字体没有变大 | FBInk 缩放值 | K4 已验证用 `-S 3`，不要使用未验证的 `-S 2`。 |
| 文字方向不对 | 显示驱动方向 | 发送前执行 `14 2`；脚本当前已内置。 |
| 有残影或布局混乱 | 是否完整清屏 | 保留 `-c`，不要在未测试前改局部刷新。 |
| 看板循环停止 | 查看 `/tmp/kindle-dashboard.log` | 检查 SSH key、USBNetwork 状态和 Mac 网卡地址。 |

## 部署验收

在新项目接入前，至少验证：

```sh
printf 'DISPLAY TEST\nLine 2\n' | ./kindle-display.sh
```

屏幕应为正向横屏、两行实际换行、24px 级别的可读字体，并在下一次同样调用后正常覆盖旧内容。通过后再接入真实数据源和后台调度。
