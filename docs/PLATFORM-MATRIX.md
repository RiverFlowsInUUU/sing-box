# PLATFORM-MATRIX.md — 三平台能力差异（仅正式版）

> **权威来源**（按优先级）：① 官方 `docs/clients/{apple,android,desktop}/features/` 与配置文档；
> ② 官方客户端源码（`sing-box-for-apple` / `sing-box-for-android`）与内核源码（`protocol/tun/`）；
> ③ 本表。**官方文档 > 内核源码 > 本表**，三者冲突时以官方为准并立即修本表。
> 落到仓库层面见 `AGENTS.md` 铁律 18。
>
> **重要**：`sing-box check` **不校验平台能力**——iOS 写了 `strict_route` 照样 exit=0，
> 但客户端跑起来会忽略或报错（更坏的一种是**静默失效**，见 §1a）。所以平台差异必须靠本表把关。
>
> **本表中可机器核对的部分已上锁**：§4 速查表由 `tools/audit.py` 的
> `matrix_platform_stale` 门禁与三份 `profiles/1.14/*-lazy.json` 实际值逐项对账
> （值的写法 = 表格里的 `` `JSON 字面量` `` 或 `**删除**`）；
> 反向由 `profile_drift` 守着 —— §4 未登记的差异一律报 ERROR。
> §1/§1a/§2/§2a 的能力清单本身**无法机器核对**（没有可靠的官方机读源），
> 只能靠人工按来源一栏复核更新。

## 0. 客户端标识

| 代号 | 平台 | 安装包 / 形态 | 最低系统 |
|---|---|---|---|
| SFA | Android | `io.nekohasekai.sfa` | Android 5.0+ |
| SFI | iOS / iPadOS | App Store `id6785326793`（名 "sing-box mt"） | iOS 15.0+ |
| SFM | macOS | 同上（独立版 / App Store） | macOS 13.0+ |
| SFT | tvOS | 同上 | tvOS 17.0+ |
| SFW | Windows / Linux | 官方 GitHub release，可执行文件 | Windows 10+ (x64/x86/arm64) |

**本仓库只覆盖 SFI / SFA / SFW** 三个目标：`ios` / `android` / `desktop`。

## 1. TUN inbound 选项可用性

| 选项 | Android (SFA) | Apple (SFI/SFM/SFT) | Desktop (SFW) |
|---|---|---|---|
| `interface_name` | 由 Android 托管 | 由 Darwin 托管 | ✅ |
| `address` / `inet4_address` / `inet6_address` | ✅ | ✅ | ✅ |
| `mtu` | ✅ | ✅ | ✅ |
| `gso` | 无权限 | ❌ 未实现 | ✅ 仅 Linux。**随 `stack` 的移除而自动成为唯一形态**（`stack` 1.15.0 废弃、1.17.0 移除），届时不需要额外配置 |
| `auto_route` | ✅ | ✅ | ✅ |
| **`strict_route`** | ❌ **未实现** | ❌ **未实现** | ✅ |
| `route_address` | ✅ | ✅ | ✅ |
| `route_exclude_address` | ✅ | ✅ | ✅ |
| **`route_address_set`**（**Since 1.11.0**） | ❌ **静默失效**（见 §1a） | ✅ | ✅ |
| **`route_exclude_address_set`**（**Since 1.11.0**） | ❌ **静默失效**（见 §1a） | ✅ | ✅ |
| `stack` | ✅（1.15.0 起废弃，1.17.0 移除） | ✅（同上） | ✅（同上） |
| `include_interface` / `exclude_interface` | 无权限 | ❌ 未实现 | ✅（仅 Linux + auto_route） |
| `include_uid` / `exclude_uid` | 无权限 | ❌ 未实现 | ✅（仅 Linux + auto_route） |
| `include_android_user` | 无权限 | ❌ 未实现 | — |
| `include_package` / `exclude_package` | ✅ | ❌ 未实现 | — |
| `include_mac_address` / `exclude_mac_address`（**Since 1.14.0**） | ✅ 需精确位置权限 | ✅ 仅服务器版 / 越狱版 | ✅ 仅 Linux |
| `platform.http_proxy`（`enabled`/`server`/`server_port`/`bypass_domain`） | ✅ | ✅（`bypass_domain` 按 hostname **后缀**匹配） | ✅ |
| `platform.http_proxy.match_domain` | ❌ 未实现 | ✅ **仅 Apple 图形客户端** | ❌ |
| `dns_mode` / `dns_address`（**Since 1.14.0**） | ✅ 本仓库未用 | 同左 | 同左 |

> ℹ️ `dns_mode` 取值 `disabled` / `native` / `hijack`；`auto_route` 开启时默认 `hijack`，
> 否则默认 `disabled`。本仓库靠 `route.rules` 里的 `{"action": "hijack-dns"}` 拦 DNS，
> 不依赖这两个字段（它们属于 `tun` inbound 自己的 DNS 接管机制）。
>
> ℹ️ `platform` 本身三平台都有，差异全在**子键**上（见上表后三行）：
> `http_proxy` 的 `bypass_domain` 在 Apple 上按**后缀**匹配；`match_domain` 只有 Apple 图形客户端有；
> Android 侧的对应物是上面那行 `dns_address`。

### 1a. `route_*_address_set` 在 Android 图形客户端**静默失效**（重要）

**这不是「支持得差一点」，而是整段代码被跳过、一声不响。**

| 环节 | 依据 |
|---|---|
| 官方声明 | 官方 `tun.md` 的 `route_address_set` 与 `route_exclude_address_set` 两节都写着：*Note that it **doesn't work on the Android graphical client** due to the Android VpnService not being able to handle a large number of routes (DeadSystemException), but otherwise it works fine on all command line clients and Apple platforms.* |
| 内核闸门 ① | `protocol/tun/inbound.go:384` — `if t.platformInterface == nil \|\| C.IsWindows {` 包住「从规则集抽 IPSet 塞进 `t.routeAddressSet` / `t.routeExcludeAddressSet`」整段。Android 图形客户端必然提供 `PlatformInterface`（SFA 的 VpnService 实现，见同文件 `:354` 的 `if C.IsAndroid && t.platformInterface == nil`）⇒ **该块在 Android 上整段跳过**。 |
| 内核闸门 ② | `protocol/tun/inbound.go:418` — `if t.autoRedirect == nil && !(runtime.GOOS == "android" && t.platformInterface != nil) {` 包住「把 IPSet 展开进 tunOptions 的 `Inet4RouteAddress` / `Inet6RouteAddress` / `Inet4RouteExcludeAddress` / `Inet6RouteExcludeAddress`」⇒ Android 同样跳过。 |
| Apple 侧为何可用 | Apple 客户端**不提供** Android 那种 `PlatformInterface`（它的路由装配走 NetworkExtension 的 `NEPacketTunnelNetworkSettings`，见 `sing-box-for-apple` 的 `Library/Network/ExtensionPlatformInterface.swift`）⇒ 两个豁免条件都不成立 ⇒ IP 集正常注入 `NEIPv4Route` / `NEIPv6Route`。 |

**连带后果**：

- **想「bypass 中国大陆 IP」时，Android 走不通这条路。** `geoip-cn` 解包后是 **9609 条 `ip_cidr`**，
  靠手写 `route_exclude_address` 列完不现实；而 `route_exclude_address_set: ["geoip-cn"]` 在
  Android 上**不报错、不警告、也不生效**。桌面 / Linux 命令行 / Apple 平台可以正常用。
- 在 Android 上，大陆流量本来就已经被 `route.rules` 里的 `geoip-cn → direct` 直连了，
  `_set` 能省的只是「用户态转发」那一点开销 ⇒ **收益远小于踩坑成本，本仓库不做这件事**
  （决策见 `docs/DECISIONS.md`，论证见 `docs/evidence/2026-10-12-dns-layer-adblock-feasibility.md`）。
- 喂给 `_set` 的规则集**必须含 `ip_cidr`**：`ExtractIPSet()` 只抽 IP-CIDR 条目，
  纯域名规则集（`geosite-*`）会抽出空集并在启动时 Warn
  `route_address_set: no destination IP CIDR rules found in rule-set: …` ⇒ 要 bypass 大陆就得喂 `geoip-cn`，喂 `geosite-cn` 无效。
- 规则集**热更新只在 `auto_redirect` 模式生效**（`protocol/tun/inbound.go:507-518` 的
  `updateRouteAddressSet` 在 `t.autoRedirect == nil` 时把集合置 nil）⇒ 普通模式下启动后不再跟随。

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
  **字段本身是全平台有效的普通 Dial Fields**（`option/outbound.go` 里没有 `schema:"omit"`。
  实测 `network_strategy: "default"` 就能把裸 direct 变成非空出站）；
  它们只具有特殊意义的那部分是「需要 `auto_detect_interface` / 图形客户端才能发挥多网卡优选」——
  本仓库不写它们，是因为用不到，**不是因为写了无效**。

### 结论（写配置时）
- `ios-lazy.json` / `android-lazy.json` 里不要写 `strict_route`。**写了不报错但无意义，且会让用户误以为已生效。**前者是最坏的一种错：它不是不能写，而是写了等于没写。
- `stack` 在 1.14 正式版仍合法（1.15.0 才废弃），三个平台都可以写；一旦升到 1.15+ 就删掉。
- Android 想按应用分流，用 `package_name` / `include_package`；iOS 做不到，只能整机。

## 2. 路由 / DNS 规则项可用性

> 来源：官方 `docs/clients/{android,apple}/features.md` 的 *Route/DNS rule option* 表。

| 规则项 | Android | Apple | Desktop |
|---|---|---|---|
| `process_name` / `process_path` / `process_path_regex` | ❌ 无权限 | 仅 macOS 独立版与 iOS 越狱版 | ✅ |
| `process_name` 替代 | 用 `package_name` | — | — |
| `package_name` / `package_name_regex` | ✅ | ❌ | — |
| `user` / `user_id` | 用 `package_name` 代替 | 仅 macOS 独立版与 iOS 越狱版 | ✅ |
| `wifi_ssid` / `wifi_bssid` | 需精确位置权限 | 仅 iOS | ✅ |
| `rule_set` 引用 | ✅ | ✅ | ✅ |
| `clash_mode` | ✅ | ✅ | ✅ |
| `network_type` / `network_is_expensive` | ✅ 图形客户端 | ✅ 图形客户端 | ❌ |
| `network_is_constrained`（低数据模式） | ❌ | ✅ **仅 Apple 图形客户端** | ❌ |

### 2a. 两家移动客户端谁独占什么（**iOS 与 Android 互不能替代的部分**）

| 能力 | Android (SFA) | Apple (SFI/SFM/SFT) | 对本仓库的影响 |
|---|---|---|---|
| **按 App 分流**：`include_package` / `exclude_package`、规则项 `package_name` / `package_name_regex`，以及客户端 UI 里的「扫描中国大陆 App」 | ✅ **独有** | ❌ 未实现 | **这是两家移动端最大的实质差异。** iOS 上做不到按 App 分流，只能整机走同一套 `route.rules`；Android 可以顺手把国内 App 整体排掉，省掉它们的解析与路由开销 |
| `process_name` / `process_path` / `process_path_regex` / `user` / `user_id` | ❌ 无权限 | ⚠️ 仅**macOS 独立版**与 **iOS 越狱版** | 两家正式版都用不上；本仓库不写这些字段 |
| `wifi_ssid` / `wifi_bssid` | ✅ 需**精确位置权限** | ✅ **仅 iOS** | 两家都能用，条件不同；本仓库不用 |
| `platform.http_proxy.match_domain` | ❌ | ✅ **仅 Apple 图形客户端** | 本仓库不用 `platform.http_proxy` |
| `http_client.engine: "apple"`（走 NSURLSession） | ❌ | ✅ 仅 Apple | 本仓库不写 `engine`（默认引擎跨平台）；官方另注明 *Experimental only: do not use in hot paths on iOS and tvOS* |
| `local` 型 DNS 服务器 | ✅ | ✅ 但在 Apple 上**走 NetworkExtension 里的 `getaddrinfo`** | 本仓库 `dns.servers` 只有 `udp` 与 `https`，不受影响 |
| 通知栏实时网速 | ✅ 独有 | ❌ | 与配置无关 |
| Always On / Include All Networks / (tvOS) 从 iPhone 导入 profile | ❌ | ✅ 独有 | **与本仓库的一处冲突**：`Include All Networks` 开启时 sing-tun 的 `system` / `mixed` 栈会返回 `ErrIncludeAllNetworks` ⇒ 与 `stack: "system"` 互斥。`stack` 在 1.15.0 废弃、1.17.0 移除，移除后默认走用户态栈，该冲突自动消失 |

> **两条不属于「差异」的项**（别记错）：`strict_route` **两家都未实现**；
> `gso`、`interface_name`、`include_interface` / `exclude_interface`、
> `include_uid` / `exclude_uid`、`include_android_user` **两家都不可用**。

## 3. 工作目录与日志（排障用）

> 来源：官方 `docs/clients/{android,apple,desktop}/features.md` 的 *Chore* 节与本机实测。

| 平台 | 工作目录 | 崩溃日志 |
|---|---|---|
| Android | `/sdcard/Android/data/io.nekohasekai.sfa/files` | `$working_directory/stderr.log` |
| Apple | 客户端内部容器（App 内 "View Service Log"） | Settings → View Service Log |
| Windows | `C:\ProgramData\sing-box-daemon` | 终端输出 / 服务日志 |

**结论**：配置里 `experimental.cache_file.path` 一律写**相对路径** `cache.db`，
不要写 `../cache/cache.db` 这类带父目录的路径（sing-box **不会自动建父目录**，
父目录不存在就 FATAL 启动失败）。

## 4. 三平台配置差异速查（本仓库实际做法）

> ⚠️ **本表是机器校验的依据，格式不可随意改**。第一列必须是 `` `JSON 路径` ``（可加「条数」
> 后缀），其余三列必须是 `` `JSON 字面量` ``（比较时按值解析）或 `**删除**`（要求该路径不存在）。
> 写法的唯一出口是「让门禁读得懂」——普通说明文字请写在表外，不要塞进单元格。
>
> `tools/audit.py` 的 `matrix_platform_stale` 逐格对账，`profile_drift` 反向兜底：
> 三份配置里出现**任何**未登记的差异都会报 ERROR。所以新增一处平台差异 = 改配置 + 加一行本表。

| JSON 路径 | desktop-lazy.json | android-lazy.json | ios-lazy.json |
|---|---|---|---|
| `inbounds[0].strict_route` | `true` | **删除** | **删除** |
| `inbounds[0].address` | `["172.19.0.1/30"]` | `["172.19.0.1/30"]` | `["172.19.0.1/30", "fdfe:dcba:9876::1/126"]` |
| `experimental.cache_file.cache_id` | `sb-template-1.14` | `sb-template-1.14-android` | `sb-template-1.14-ios` |
| `route.auto_detect_interface` | `true` | `true` | `true` |
| `dns.rules` 条数 | `6` | `6` | `6` |

> 上表五行之外，**三份配置其余部分逐字节相同** —— 这条不变量由 `profile_drift` 门禁守着
> （§4 没登记的差异一律 ERROR）。`clash_api` 已从桌面端删除（见 D17），
> 所以连 `experimental` 都只剩 `cache_id` 这一处不同。

**三份配置的 `dns.rules` 顺序完全一致**（6 条，也是门禁的比对项，见 `_audit_dns_adblock`）：

1. `query_type: [AAAA, HTTPS, SVCB]` → `predefined` `rcode: NOERROR`（掐掉 IPv6/SVCB 查询）
2. `.lan/.local/.localdomain/.home.arpa` → `route` `dns-cn`
3. `geosite-private` → `route` `dns-cn`
4. **`jinx-direct` → `route` `dns-cn`**（白名单必须先放行 —— 它的域名几乎全被下面的拦截集覆盖）
5. **`jinx-ads` + `awanue-ads` → `predefined` `rcode: NXDOMAIN`**（DNS 层前置拦截）
6. `geosite-cn` → `route` `dns-cn`

第 4/5 条必须排在**第 6 条之前**，否则国内广告域名会先被 `geosite-cn` 放行到 `dns-cn`
而永远轮不到拦截；拦截动作只能写 `predefined`/`reject`，**写成 `route` 等于没拦**。
详见 `AGENTS.md` 铁律 9 与 `docs/LESSONS.md` L28。

**三份配置的 `route.rules` 顺序完全一致**（13 条）：
`sniff` → `hijack-dns` → **`resolve(ipv4_only)`** → `reject(ip_version:6)` →
**`reject(network:udp, port:443)`** → 8 条 route 规则。
`resolve` 的位置是硬性的（见 `docs/LESSONS.md` L18 / `AGENTS.md` 铁律 14）；
两条 `reject` 是**不同维度**的匹配（地址族 / 传输层），不能合并。

**为什么三份都不写 `clash_api`**（桌面端原来有个只有 `default_mode` 的壳，已删，见 D17）：

- **没有 `external_controller` 就没有入口**：`experimental/clashapi/server.go` 里只有
  `externalController = options.ExternalController != ""` 为真才监听端口；只写 `default_mode`
  不会开端口，等于配了个没人能调的控制器。
- **`default_mode: "Rule"` 本身就是空转**：`experimental/clashmode/manager.go` 里
  `if defaultMode == "" { defaultMode = "Rule" }` —— 不写也是它。
- **而它仍有代价**：`box.go:243` 的 `if needClashAPI || needAPIService || … {` 只要
  `clash_api` 这个键存在就为真，于是额外创建 Traffic Manager 与连接统计
  （`experimental/clashapi.TrafficManager`）。

⇒ 取舍：**用不上就别写**。将来要在桌面端用 Clash 面板时，按需补三样 ——
`external_controller`（如 `127.0.0.1:9090`）、`secret`、`external_ui`，
并同时更新本节这一行（铁律 19）。

### 4b. 出口 IPv6：本地配置管不到

`resolve(ipv4_only)` 只能保证「**本地 → 节点**这一段递出去的是 IPv4 字面量」
（日志形态：`outbound connection to 160.79.104.10:443`）。
**「节点 → 目标站」用哪个地址族由服务端决定**，客户端配置无从约束。

判据：把节点域名解析一次，看它的 AAAA 是否就是你在测速站看到的那个 IPv6。
是 ⇒ 那个 IPv6 就是节点自己的出口，**不是本地泄漏**，不要在本地配置里继续加固。
（源码与实测见 `docs/LESSONS.md` L18 与 `docs/evidence/`。）

### 4c. 为什么 iOS 的 tun `address` 比另外两家多一段 IPv6

**没有 Apple 专属理由。** 官方从未说 iOS 必须配 IPv6 地址——`docs/clients/apple/features.md`
的 TUN 表只写 `inet6_address: :material-check:`，那是「**可用**」不是「**必须**」。
来源是**照抄官方示例**：官方 `docs/manual/proxy/client.md` 的 "Basic TUN usage for Chinese users"
给了两个并列 tab，`IPv4 only` 用 `["172.19.0.1/30"]`，`IPv4 & IPv6` 用
`["172.19.0.1/30", "fdfe:dcba:9876::1/126"]`；`docs/configuration/inbound/tun.md` 的
*Structure* 示例同样把两段并列。本仓库建仓时 iOS 那份整段抄了后者，
三平台拆分统一成 `172.19.0.1/30` 时**只删了安卓与桌面**，iOS 那份留了下来。

**保留它的唯一理由**（同时是一个诚实的「未验证」）：Apple 客户端
`sing-box-for-apple` 的 `Library/Network/ExtensionPlatformInterface.swift` 里，IPv4 段有
`if inet4RouteAddressIterator.hasNext()` 之类的分支保护，而 IPv6 段是
`let ipv6Settings = NEIPv6Settings(addresses: ipv6Address, networkPrefixLengths: ipv6Prefixes)`
之后**无条件**赋给 `settings.ipv6Settings`——**传空 `inet6_address` 会走到哪条路径，官方文档没有保证，
本仓库也没有 iOS 实机验证过**。留着它是一份保险，不是要求。

⇒ **要删它，必须先在一台真 iPhone 上用空 `inet6_address` 跑通并确认**；
在那之前不要因为「看着多余」就删。
