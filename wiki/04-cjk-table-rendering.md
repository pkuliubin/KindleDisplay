# Kindle CJK 单次表格渲染实践

## 目的与结论

本规范是后续 Kindle 模块的当前渲染基线。目标是在 Kindle 4 上同时满足：

- 完整中英文显示，不依赖 Mac 的系统字体或当前内容生成临时字库；
- 固定表格列稳定对齐；
- 每页只调用一次 FBInk TrueType 文本渲染；
- 每页只触发一次 E-Ink 刷新；
- 状态页具有足够大的字号，并能清除历史残影。

当前已验证的方案是：Kindle 常驻完整的 `Sarasa Mono SC` 等宽字体，Mac 生成一段定宽多行文本，发送器将整段文本交给一次 `fbink -t` 调用。

```text
collector / normalized state / table formatter (Mac)
    -> one ttf_page layout record
kindle-display.sh
    -> one SSH command
Kindle FBInk: one TrueType render + one E-Ink refresh
```

不要把每个字段、每个标题或每个中文字符拆成单独的 FBInk 调用。完整 CJK 字体会在每次 TrueType 调用中初始化；拆块会明显拖慢刷新，也会使页面逐块出现。

## 一次性部署

字体必须固定部署在 Kindle，而不是使用 macOS 的 `STHeiti` 等系统字体，也不要根据当前标题动态裁剪字库。动态字集虽然小，但会导致新字符缺字，不能作为正式能力。

在新 Mac 上执行一次：

```sh
KINDLE_SSH_KEY="$HOME/.ssh/kindle_display_ed25519" \
  ./scripts/install-kindle-font.sh
```

该脚本下载官方开源的 `Sarasa Mono SC`，并部署为：

```text
/mnt/us/fonts/SarasaMonoSC-Regular.ttf
```

发送器默认使用这个路径。可通过 `KINDLE_CJK_FONT` 覆盖，但替换字体必须同时满足：中文覆盖完整、英文半角与中文全角的 advance 比为 1:2、并且真机验证过。

## 当前表格契约

当前 Codex 看板由 `KindleTextRenderer` 生成。它使用“显示单位”而不是 Python 字符数：ASCII/空格为 1 单位，东亚宽字符为 2 单位。Sarasa Mono SC 在该 Kindle 上对应英文半格、中文整格。

| 区域 | 当前单位宽度 | 对齐方式 |
| --- | ---: | --- |
| `TASK` | 14 | 左对齐，包含 `> ` 前缀 |
| `MODEL` | 14 | 左对齐，完整显示 `gpt-5.6-terra` |
| `STA` | 3 | 左对齐，显示 `R/D/S/A/I` |
| `CTX` | 4 | 右对齐 |
| `TOK` | 12 | 右对齐，显示 `today/lifetime` |
| `C L/T` | 7 | 右对齐 |

`TASK -> MODEL` 与 `MODEL -> STA` 均使用 2 个半格间距；其余列使用 1 个半格间距。状态使用 `R`、`D`、`S`、`A`、`I`。顶部按模型分行显示今日 token、输出 token 比例和名义价格估算；具体业务字段以 `wiki/06-codex-daily-token-usage-design.md` 为准。

### 标题截断

`TASK` 的正文上限是 12 单位，`> ` 占用另外 2 单位。截断规则必须保证：

1. 长标题末尾有明确的截断标记；
2. 已截断的可见标题恰好填满 12 单位；
3. 后续 `MODEL` 列始终从同一位置开始。

中文标题存在奇偶问题。例如 `这篇文章讲.` 是 `5 * 2 + 1 = 11` 单位；若只补空白，视觉上会比 `先阅读 wiki.` 多一个空隙。当前实现对已截断标题用 `.` 补足剩余单位：

```text
> 先阅读 wiki.  gpt-5.6-terra
> 这篇文章讲..  gpt-5.6-terra
```

两行的 title 字段都恰好是 14 单位（包括 `> `），因此模型列物理起点一致。短但未截断的标题仍需要不可见填充，这是定宽表格的正常行为。

### 表格空白

FBInk 的 TrueType 文本流不应依赖连续 ASCII 空格或普通不换行空格来保持列宽；这些空白在排版时可能被折叠或产生不稳定视觉效果。当前字段填充使用 `U+2007 FIGURE SPACE`，它在 Sarasa Mono SC 中是一个固定半格字形。

不要把这种空白当成修复中文截断的手段；中文截断的奇偶空位由上面的标题截断规则解决。

### 字号与页面高度

字号必须保持偶数像素，避免英文半格在像素级出现累计舍入误差：

- 当前页总行数不超过 15 行：`26px`；
- 更多内容：回落到 `22px`，避免底部被截断。

当前文本区使用 `top=20`、`left=20`、`right=15`、`bottom=20`。新增字段或扩大列宽时，必须先按“显示单位 * 半格像素 + 左右边距”验算 800px 横屏宽度，再进行真机发送。

## 发送器契约

`render_layout()` 输出一条 `ttf_page` 记录：

```text
font_px<TAB>top<TAB>left<TAB>right<TAB>ttf_page<TAB>page_text
```

`page_text` 的逻辑换行用 ASCII `U+001E` 分隔，发送器在本机组装远端命令前将其还原为真实换行。这样 TSV 仍是一条完整记录，Kindle 上只执行一次：

```sh
/mnt/us/fbink -q <refresh-profile-flags> -t \
  regular=/mnt/us/fonts/SarasaMonoSC-Regular.ttf,px=26,... \
  -- "<whole page>"
```

- `clean -> -c`：已验证的普通换页 profile，无全屏黑闪，表现为淡入淡出并允许少量残影；
- `flash_clean -> -f -c`：已验证的黑闪式完整刷新，用于启动、重连和周期清残影；
- `-q`：避免无用日志；
- `notrunc`：内容越界应明确失败，不要静默截掉右侧列。

一个页面只有一次文本调用，因此不要再为这条路径附加 `-b` 或 `-s`。`-b` 只适用于确实需要多次绘制后再统一刷新的实验性布局。

## 已踩过的坑

| 失败路径 | 现象 | 当前结论 |
| --- | --- | --- |
| 默认 IBM 点阵字体显示中文 | 缺字 | 只适合英文/数字，正式中英文看板使用 Sarasa Mono SC。 |
| 每个中文标题单独加载完整字体 | 十几秒到数十秒、逐块出现 | 不采用；整页一次 TrueType 渲染。 |
| 按当前标题裁剪 18KB 字体 | 新 session 的新汉字会缺字 | 不采用；字体覆盖必须与展示内容无关。 |
| 比例字体配 ASCII 空格表格 | 列难以稳定对齐 | 不采用；使用 1:2 等宽 CJK 字体。 |
| 截断后只保证 `<=` 宽度 | 中文标题后多出可见空隙 | 已截断标题必须补到精确字段宽度。 |
| 只用 `-c` 清屏 | 可能保留少量残影 | 仅作为普通换页 profile；按照设备级周期使用 `-f -c` 清除。 |
| `-c -s` 当作纯清屏 | `-s` 改写行为，未真正清空 | 纯清屏诊断使用 `fbink -k`。 |
| 多次 SSH/远端循环传布局 | 曾出现画完又清空的空白页 | 在 Mac 端将命令安全引用后一次 SSH 发送。 |

## 新模块接入流程

1. 在 Mac 端完成采集、归一化、排序和字符串格式化；Kindle 不执行业务逻辑。
2. 复用 `KindleTextRenderer` 的显示单位、填充和截断规则，或基于它创建场景专属 renderer。
3. 一个完整页面只产生一条 `ttf_page` 记录。
4. 先运行 `./scripts/kindle-dashboard.sh preview --task <id> --format text` 检查逻辑文本；再运行 `once --task <id> --page <n>` 真机检查列对齐、底部边界和残影。
5. 内容量接近最大行数时，专门验证字号回落后的布局，不要只用少量 session 页面验收。

USBNetwork、SSH key、字体安装与重新连接后的 Mac RNDIS 地址修复，见 `wiki/03-new-mac-setup.md`。
