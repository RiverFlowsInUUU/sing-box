# PLATFORM-MATRIX.md — 三平台能力差异（仅正式版）

> 来源：官方 `clients/{apple,android,desktop}/features/` 页面 + 本机 `sing-box check` 实测。
> **重要**：`sing-box check` **不校验平台能力**——iOS 写了 `strict_route` 照样 exit=0，
> 但客户端跑起来会忽略或报错。所以平台差异必须靠本表人工/脚本把关。

## 0. 客户端标识

| 代号 | 平台 | 安装包 / 形态 | 最低系统 |
|---|---|---|---|
| SFA | Android | `io.nekohasekai.sfa` | Android 5.0+ |
| SFI | iOS / iPadOS | App Store `id6785326793`（名 "sing-box mt"） | iOS 15.0+ |
| SFM | macOS | 同上（独立版 / App Store） | macOS 13.0+ |
| SFT | tvOS | 同上 | tvOS 17.0+ |
| SFW | Windows / Linux | 官方 GitHub release，可执行文件 | Windows 10+ (x64/x86/arm64) |

**本仓库只覆盖 SFI(SFI) / SFA(SFA) / SFW** 三个目标：`ios` / `android` / `desktop`。

## 1. TUN inbound 选项可用性

| 选项 | Android (SFA) | Apple (SFI/SFM/SFT) | Desktop (SFW) |
|---|---|---|---|
| `interface_name` | 由 Android 托管 | 由 Darwin 托管 | ✅ |
| `address` / `inet4_address` / `inet6_address` | ✅ | ✅ | ✅ |
| `mtu` | ✅ | ✅ | ✅ |
| `gso` | 无权限 | ❌ 未实现 | ✅（仅 Linux，且需 sing-tun 自带栈） |
| `auto_route` | ✅ | ✅ | ✅ |
| **`strict_route`** | ❌ **未实现** | ❌ **未实现** | ✅ |
| `route_address` / `route_exclude_address` 系列 | ✅ | ✅ | ✅ |
| `stack` | ✅（1.15.0 起废弃，1.17.0 移除） | ✅（同上） | ✅（同上） |
| `include_interface` / `exclude_interface` | 无权限 | ❌ 未实现 | ✅（仅 Linux + auto_route） |
| `include_uid` / `exclude_uid` | 无权限 | ❌ 未实现 | ✅（仅 Linux + auto_route） |
| `include_android_user` | 无权限 | ❌ 未实现 | — |
| `include_package` / `exclude_package` | ✅ | ❌ 未实现 | — |
| `platform` | ✅ | ✅ | ✅ |
| `dns_mode` / `dns_address`（1.15.0+） | 待官方确认 | 待官方确认 | 待官方确认 |

## 1b. 防回环：`route.auto_detect_interface`

| 防回环手段 | Android (SFA) | Apple (SFI) | Desktop (SFW) |
|---|---|---|---|
| `route.auto_detect_interface: true` | ✅ **唯一可行** | ✅ **唯一可行** | ✅ |
| `route.default_interface` | ❌ 无可用网卡名 | ❌ | ✅ |
| `outbound[].bind_interface` | ❌ 同上 | ❌ | ✅（仅 Linux） |
| `outbound[].inet4_bind_address` | ✅ 可作为补充 | ✅ | ✅ |

**三个平台都必须写 `route.auto_detect_interface: true`。**

- Android 上它不是文档里说的"仅 Linux/Windows/macOS"：`constant/os.go` 里
  `IsLinux = goos.IsLinux == 1 || goos.IsAndroid == 1`，平台检查因此放行；
  实际走 `ProtectFunc()` → `VpnService.protect(fd)`（Android VPNService 的 socket 豁免机制）。
- **不写的后果**：出站 socket 一个 Control 也不挂 → 自己 App 的流量被 VpnService 抓回隧道 →
  回环。症状：能启动但没网、节点全无延迟、只有上传没下载、连接数上万、内存飙到 1GB。
- `sing-box check` 对此**完全静默**，只能靠 `tools/audit.py` 的 `tun_without_auto_detect_interface` 拦。
- `route.override_android_vpn` 在图形客户端**无效**（`experimental/libbox/monitor.go` 的
  `OverrideAndroidVPN()` 恒返回 `false`），写了也没副作用，但不要指望它。
- `network_strategy` / `network_type` / `fallback_network_type` / `fallback_delay`
  官方标注「仅 Android 与 Apple 图形客户端，且需要 `auto_detect_interface` 开启」。

### 结论（写配置时）
- **`ios-lazy.json` / `android-lazy.json` 里不要写 `strict_route`。** 写了不报错但无意义，且会让用户误以为已生效。
- `stack` 在 1.14 正式版仍合法（1.15.0 才废弃），三个平台都可以写；一旦升到 1.15+ 就删掉。
- Android 想按应用分流，用 `package_name` / `include_package`；iOS 做不到，只能整机。

## 2. 路由 / DNS 规则项可用性

| 规则项 | Android | Apple | Desktop |
|---|---|---|---|
| `process_name` / `process_path` / `process_path_regex` | ❌ 无权限 | 仅 macOS 独立版与 iOS 越狱版 | ✅ |
| `process_name` 替代 | 用 `package_name` | — | — |
| `package_name` / `package_name_regex` | ✅ | ❌ | — |
| `user` / `user_id` | 用 `package_name` 代替 | 仅 macOS 独立版与 iOS 越狱版 | ✅ |
| `wifi_ssid` / `wifi_bssid` | 需精确位置权限 | 仅 iOS | ✅ |
| `rule_set` 引用 | ✅ | ✅ | ✅ |
| `clash_mode` | ✅ | ✅ | ✅ |

## 3. 工作目录与日志（排障用）

| 平台 | 工作目录 | 崩溃日志 |
|---|---|---|
| Android | `/sdcard/Android/data/io.nekohasekai.sfa/files` | `$working_directory/stderr.log` |
| Apple | 客户端内部容器（App 内 "View Service Log"） | Settings → View Service Log |
| Windows | `C:\ProgramData\sing-box-daemon` | 终端输出 / 服务日志 |

**结论**：配置里 `experimental.cache_file.path` 一律写**相对路径** `cache.db`，
不要写 `../cache/cache.db` 这类带父目录的路径（sing-box **不会自动建父目录**，
父目录不存在就 FATAL 启动失败）。

## 4. 三平台配置差异速查（本仓库实际做法）

| 项 | desktop-lazy.json | android-lazy.json | ios-lazy.json |
|---|---|---|---|
| `strict_route` | `true` | **删除** | **删除** |
| tun `address` | `172.19.0.1/30` | `172.19.0.1/30` | `172.19.0.1/30` + `fdfe:dcba:9876::1/126` |
| `clash_api` | 保留（外部控制器） | **删除** | **删除** |
| `route.auto_detect_interface` | `true` | `true` | `true` |
| `cache_file.cache_id` | `sb-template-1.14` | `sb-template-1.14-android` | `sb-template-1.14-ios` |
| 其余（dns/route/outbounds/http_clients） | 三平台完全一致 | 同左 | 同左 |

**为什么 Android/iOS 去掉 `clash_api`**：移动端由图形客户端自行管理内部 API，
手写 `external_controller` 通常用不上，还可能端口冲突。需要时再加。
