# Kindle 4 改造与接入手册

## 目标与已验证结果

本手册记录把一台 Kindle 4 Non-Touch 改造成 Mac 可通过 USB 推送低频文字看板的完整设备侧配置。

除非命令明确使用绝对路径，文中的 Mac 命令均假设当前目录为本目录：

```sh
cd /Users/liubin/Projects/DailyAI/kindle_k4_mod
```

已验证设备：

| 项目 | 值 |
| --- | --- |
| 设备 | Kindle 4 Non-Touch (K4) |
| 固件 | 4.1.3 |
| 屏幕 | 600 x 800, 167 dpi, 8-bit E-Ink |
| Kindle USB 网络地址 | `192.168.15.244` |
| Mac USB 网络地址 | `192.168.15.201/24` |
| SSH 用户 | `root` |
| 显示工具 | FBInk v1.24.0, `/mnt/us/fbink` |

最终设备具备：Jailbreak、KUAL、MRPI、USBNetwork、SSH、FBInk 和 KOReader。KOReader 是阅读器，不参与看板运行；KUAL 仅用于设备维护和启用 USBNetwork；正式看板通过 SSH + FBInk 工作。

## 前提和边界

- 这是老 Kindle 的系统修改，不是官方功能。不要对仍有重要阅读数据或需要官方保修的设备直接操作。
- Kindle 只能在两种 USB 模式间切换：USB 存储模式或 USBNetwork 网络模式。网络模式下 Mac 不会挂载 Kindle 磁盘；存储模式下 SSH 不可用。
- 它适合 1 到 10 分钟一次的状态文字或简单图形，不是高刷新率的副屏或视频屏。
- 所有安装包必须匹配 K4 和固件世代。不要把 Paperwhite、Touch 或新 Kindle 的 `.bin` 更新包用于 K4。

## 组件关系

```text
Mac status source
       |
       | USB RNDIS, SSH (root@192.168.15.244)
       v
USBNetwork -> /mnt/us/fbink -> E-Ink framebuffer

KUAL -> USBNetwork extension / MRPI maintenance
KOReader -> standalone reader, optional
```

## 本机交付物

本目录保留了本次使用的包、提取内容和恢复材料。正式项目应只依赖下面的运行资产，且不要把私钥提交进版本库：

| 路径 | 用途 |
| --- | --- |
| `kindle-k4-jailbreak-1.8.N-r18977.tar.xz` | K4 Jailbreak 包 |
| `kindle-mkk-20141129-r18833.tar.xz` | MKK / Kindlet 开发者信任包 |
| `kual-mrinstaller-1.7.N-r19303.tar.xz` | MRPI 安装器 |
| `kindle-usbnetwork-0.57.N-r18979.tar.xz` | USBNetwork 安装包 |
| `KUAL-v2.7.37-gfcb45b5-20250419.tar.xz` | KUAL 本体 |
| `koreader-kindle-v2026.03.tar.gz` | KOReader，可选 |
| `kindle_ed25519` | Mac 到 Kindle 的 SSH 私钥，必须保密 |
| `kindle_ed25519.pub` | 已写入 Kindle 的 SSH 公钥 |
| `repaired-developer.keystore` | 本机 KUAL 签名兼容修复产物，仅用于该问题的恢复 |
| `runme.sh` | 一次性 keystore 修复脚本；不要常驻留在 Kindle 根目录 |

## 从原始设备到可用设备的顺序

### 1. 充电、确认型号和清理空间

1. 用可靠的充电器充到能正常开机；仅看到 USB 充电图标或长按电源闪烁通常是电池过放，不要在这个阶段刷机。
2. 在 Settings 中确认设备是 K4、固件为 4.1.3，并设好时间。K4 设置页只有时间而没有日期是正常现象。
3. 以 USB 存储模式连接 Mac，确保 Kindle 用户分区至少有数百 MB 空闲。更新文件消失不代表更新一定成功，空间不足会造成安装包解压/安装失败。
4. 若旧书和文档不需要，可以清空挂载卷的 `documents/`。不要删除 `system/`。

本次设备最初只有约 14 MiB 可用空间，USBNetwork 更新因此失败；清掉旧 `documents/` 和一次失败的 `usbnet/` 目录后才恢复到超过 1 GiB 可用，安装成功。

### 2. Jailbreak

1. 从 K4 Jailbreak 压缩包提取对应安装文件，复制到 Kindle 根目录。
2. 在 Kindle 执行 `Home -> Menu -> Settings -> Menu -> Update Your Kindle`。
3. 等待自动重启完成，不要断电。
4. 以 Jailbreak 包说明中的验证方式检查结果。Jailbreak 是后续 MKK、KUAL、MRPI 和 USBNetwork 的前提。

如果 `Update Your Kindle` 置灰，通常是包不匹配、文件不在根目录、USB 未安全弹出，或系统版本不符合包要求。先停止，不要反复用不同机型的包尝试。

### 3. MKK、KUAL 与 MRPI

1. 安装 K4 对应 MKK 更新包，再重启。
2. 将 K4 的旧设备版 `KUAL-KDK-1.0.azw2` 放到 `documents/`，从 Home 打开它。
3. 按 KUAL/MRPI 包说明安装 MRPI；本次实际通过 Home 搜索框输入 `;log mrpi` 后执行 MRPI 安装流程。
4. KUAL 正常时应该能看到至少 `KUAL`、`HELPER`、`USBNetwork` 和 `Quit`。`HELPER -> Install MR Packages` 是安装后续 MRPI 包的入口。

### 4. 安装 USBNetwork

1. 用 `KUAL -> HELPER -> Install MR Packages` 安装匹配 K4 的 USBNetwork 包。
2. 设备重启/返回首页后，打开 `KUAL -> USBNetwork`，使 Enable 项显示对号。
3. 拔插 USB 线。Mac 应将设备识别成 `RNDIS/Ethernet Gadget`，而不是 Kindle 存储盘。

此设备的 USBNetwork 配置已验证为：

```text
Kindle: 192.168.15.244
Host:   192.168.15.201
```

在 Mac 上检查接口，通常是 `en7`，但接口号会随机器和连接顺序变化：

```sh
ifconfig en7
sudo ifconfig en7 inet 192.168.15.201 netmask 255.255.255.0 up
ping -c 1 192.168.15.244
```

最后一条可通后再尝试 SSH。macOS 有时把 RNDIS 接口自动设为 `169.254.x.x` 的自分配地址；这不是 Kindle 损坏，只需重新设为 `192.168.15.201/24`。正式项目应在系统网络设置中给该 RNDIS 服务配置固定 IPv4，或由启动脚本检测对应接口后设置地址。

### 5. 启用 SSH 并部署 FBInk

USBNetwork 安装后，在 Kindle 存储模式下向 `/mnt/us/usbnet/etc/authorized_keys` 写入专用公钥，然后切回 USBNetwork 模式。连接测试：

```sh
ssh -i kindle_ed25519 -o BatchMode=yes root@192.168.15.244 'uname -a'
```

本机私钥为 `kindle_ed25519`。保持权限为 `0600`，不要上传或提交。FBInk 二进制已部署到 Kindle 的 `/mnt/us/fbink`；先确认它可执行：

```sh
ssh -i kindle_ed25519 root@192.168.15.244 'test -x /mnt/us/fbink && echo FBInk-ready'
```

本次确认 `/usr/sbin/eips` 也存在，但正式看板使用 FBInk。它的文字渲染、清屏和布局控制更适合脚本调用。

### 6. 可选安装 KOReader

KOReader 解压到 Kindle 用户分区后，目录为 `/mnt/us/koreader` 和 `/mnt/us/extensions/koreader`，KUAL 中出现 `KOReader` 项即表示安装成功。它与看板流程独立；不要把 KOReader 当成 FBInk 的依赖。

## 本次关键故障与解决方式

### KUAL 报 `This item is not signed by an authorized developer`

**表现**：打开 KUAL 文档后只有关闭按钮，重装 KUAL、重新设置时间、普通重启都不能解决。

**根因**：K4 需要 MKK 提供 Kindlet 开发者证书信任。当前 KUAL 2025 包使用已续期的 `ditest`、`dktest`、`dntest` 证书，而旧 MKK 的 Java developer keystore 含有不兼容的证书条目。因此系统把 KUAL 当作未授权 Kindlet。

**已验证修复**：在 Mac 用 `repair_keystore.py` 从当前 KUAL 的签名中提取三个证书，并替换旧 MKK keystore 中同名条目，得到 `repaired-developer.keystore`。一次性 `runme.sh` 通过 Jailbreak 的诊断执行入口以 root 权限完成：

```text
/mnt/us/kual-keystore-repair/developer.keystore
    -> /var/local/java/keystore/developer.keystore
```

脚本会先备份为 `/mnt/us/developer.keystore.before-2026-repair`，再把根文件系统重新挂回只读。修复后 KUAL 已成功启动。

**注意**：这是针对 K4 + 旧 MKK + 当前 KUAL 的兼容修复，不是常规安装步骤。执行前必须确认 payload 和备份路径，执行后必须把 Kindle 根目录上的 `runme.sh` 删除，避免每次诊断意外重复覆盖系统 keystore。

### USBNetwork 更新显示 `Update was not successful`

首先检查空间，而不是立即换包或重刷。该设备 99% 满时的失败在清理用户分区后消失。然后确认：包是 K4 版本、放在根目录、已安全弹出、`Update Your Kindle` 可以点击。

### Mac 能识别 RNDIS，但 SSH / ping 超时

检查 Mac 接口是否仍为自分配 `169.254.*`。将它改为 `192.168.15.201/24`，然后测试：

```sh
ping -c 1 192.168.15.244
ssh -i kindle_ed25519 -o BatchMode=yes root@192.168.15.244
```

### 看板不显示或仅显示 Kindle 首页

确认 KUAL 中 USBNetwork 是启用状态，拔插 USB 后 Mac 不再把 Kindle 挂为磁盘；再确认 `ping` 和 SSH。网络模式下 FBInk 直接绘制 framebuffer，Kindle UI 本身不需要停在特定页面。

## 日常维护与恢复

- 进入网络模式：`KUAL -> USBNetwork` 打对号，拔插 USB。
- 回到存储模式：SSH 中执行 `/mnt/us/usbnet/bin/usbnetwork`，该命令会立即断开 SSH；随后重新插线。
- 每次系统重启后，先人工从 KUAL 启用 USBNetwork。不要在稳定性未验证前启用 `/mnt/us/usbnet/auto` 自动网络模式，否则排查时会失去方便的 USB 存储通道。
- 若新项目需要开机自动看板，先做单独的恢复测试和物理 USB 存储回退方案，再启用自动网络。
- 避免官方 OTA 更新；它可能破坏 Jailbreak、MKK 或扩展。若 KUAL 再次出现签名问题，优先检查 developer keystore/MKK，而非重装 KOReader。

## 最小验收清单

```sh
# Mac: RNDIS 接口已配置为 192.168.15.201/24
ping -c 1 192.168.15.244

# SSH: 能执行远端命令
ssh -i kindle_ed25519 -o BatchMode=yes root@192.168.15.244 'id'

# 显示: 由后续显示协议文档中的脚本实际渲染一段文本
printf 'Kindle link OK\n' | ./kindle-display.sh
```

三项都通过，设备侧改造即可视为完成。
