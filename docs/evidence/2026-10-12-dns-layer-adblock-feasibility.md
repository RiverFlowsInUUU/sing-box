# 可行性分析：bypass 中国大陆 IP + 把广告拦截前置到 DNS 层

- 日期：2026-10-12
- 触发：用户提问「sing-box 有 bypass 中国大陆 IP 的功能吗」+「Jinx / 秋风广告规则能否前置到 DNS 层处理，规则集保留作兜底」
- 结论：**第 1 问不做**（用户已拍板）；**第 2 问可行，已在 Android 本地配置实装并验证**
- 依据：官方文档 + sing-box 1.14.3 源码（源码树 `~/Desktop/_probe/src/sing-box-1.14.3/`）

---

## 第 1 问：bypass 中国大陆 IP

### 先纠正概念：`bypass` 不是这个意思

sing-box 的 `bypass` 是 route 的**动作**（`docs/configuration/route/rule_action.md` 的 `### bypass`），语义是「流量根本不进 sing-box 路由」，
只在软路由 `auto_redirect`（Linux + nftables）场景成立。本仓库三份配置是 tun + `auto_route`，
**用不上这个动作**。

用户想要的效果对应 tun 的 `route_exclude_address_set`（Since 1.11.0）：

> Add the destination IP CIDR rules in the specified rule-sets to routes, equivalent to adding to
> `route_exclude_address`. Matched traffic will bypass the sing-box routes.

即：把规则集里的 IP 段**直接塞进内核路由表**，命中的流量由内核绕过 tun，
比「走 `direct` 出站」更彻底（连用户态转发都省了）。

### 平台可用性

| 平台 | 可用 | 依据 |
|---|---|---|
| 软路由 Linux + nftables（`auto_redirect`） | ✅ | 写进防火墙规则（官方文档 `With auto_redirect enabled` 分支） |
| 桌面 Windows / Linux / macOS | ✅ | 源码闸门 `protocol/tun/inbound.go:384` 的 `platformInterface == nil` 放行 |
| iOS / Apple 图形客户端 | ✅ | 官方文档明示可用 |
| **Android 图形客户端** | ❌ **完全无效且静默无报错** | 官方明示 *doesn't work on the Android graphical client*（DeadSystemException）；源码 `protocol/tun/inbound.go:384` 与 `:418` 两处直接跳过 |

Android 的源码机制（两处闸门）：

- `protocol/tun/inbound.go:384` — `if t.platformInterface == nil || C.IsWindows {` 包裹「从规则集抽 IPSet」的逻辑（384-416）。
  Android 图形客户端必然提供 `PlatformInterface`（SFA 的 VpnService 实现）⇒ 整段跳过。
- `protocol/tun/inbound.go:418` — `if t.autoRedirect == nil && !(runtime.GOOS == "android" && t.platformInterface != nil) {`
  包裹「把 IPSet 展开进 `tunOptions.Inet4RouteExcludeAddress`」的逻辑（418-437）⇒ 同样跳过。

原因：Android VpnService 扛不住几万条路由。`geoip-cn` 展开实测 **9609 条 `ip_cidr`**。

### 为什么 Android 上不值得做

- Android 只能用 `route_exclude_address`（手工列 CIDR）——适合几条，喂 9609 条就是上面那个崩溃。
- 更关键：**大陆流量本来就已经直连**。`route.rules` 最后一条 `geoip-cn → direct` 已让大陆 IP 走直连出站，
  只是流量仍经过 sing-box 的用户态转发。
- ⇒ 在 Android 上，bypass 的收益仅剩「省掉用户态转发的 CPU/耗电」，**不是「能不能访问」**。
  **结论：不做。**

### 若桌面/软路由将来要做，先知道这个坑

大陆 DNS 服务器 IP **全在 `geoip-cn` 里**（实测：`223.5.5.5`、`223.6.6.6`、`119.29.29.29`、
`114.114.114.114`、`180.76.76.76`、`117.50.10.10`、`180.184.1.1` 命中；`8.8.8.8`、`1.1.1.1` 不命中）。
⇒ `dns-cn`（223.5.5.5）会绕过 sing-box，`dns-proxy`（8.8.8.8）不会。
两者都是 DoH:443，绕过 tun 后 DoH 本身仍可用，但该 DNS 查询就脱离了 sing-box 管辖。

规则集必须是 **`geoip-cn.srs`**：`ExtractIPSet()`（`route/rule/rule_set_remote.go:147`）
只抽 IP-CIDR 条目，喂 `geosite-cn.srs` 抽出空集并 Warn。

---

## 第 2 问：广告拦截前置到 DNS 层

### AdGuard 格式：**必须预编译**，但不影响本案

官方文档 `docs/configuration/rule-set/adguard.md`：

> These formats are **not directly supported as source formats**, instead you need to convert them to
> binary rule-set.
> `sing-box rule-set convert --type adguard [--output <file-name>.srs] <file-name>.txt`

源码佐证：`option/rule_set.go:283-284` 的 `AdGuardDomain` 与 `AdGuardDomainMatcher`
**都是 `json:"-"`**，JSON 里没有任何字段名可写；唯一入口是 `cmd_rule_set_convert.go`。

**但这对本案不适用**：Jinx 与秋风发布的本来就是 sing-box 自己的 source 格式 JSON
（现配置里已是 `format: "source"`），**可以直接在 DNS 规则里引用**。

### DNS 规则能按 IP 拦吗

不能。`predefined` 没有任何 `ip_cidr` / `ip_version` 条件；而引用含 `ip_cidr` 的规则集会被
`route/rule/rule_dns.go:407` 的 `WithAddressLimit()` 标记为「地址过滤器」，
匹配推迟到拿到响应之后（`dns/router.go:1364` 的 `addressLimitResponseCheck`）。

**但本案不受影响**：Jinx 与秋风都是**纯域名列表、无 `ip_cidr`**（实测 Jinx 3735 条 `domain_suffix`、
秋风 949 条 `domain` + 12 条 `domain_suffix`）⇒ 走普通预匹配路径，安全。

### 方案（已实装到 Android 本地配置）

在 `dns.rules` 里插入两条，位置在 `.lan` / `geosite-private` 之后、`geosite-cn` 之前：

```json
{ "rule_set": ["jinx-direct"],            "action": "route",      "server": "dns-cn"   },
{ "rule_set": ["jinx-ads", "awanue-ads"], "action": "predefined", "rcode": "NXDOMAIN"  }
```

顺序是硬的（与 route 层同一套铁律）：

- `jinx-direct` 白名单**必须先放行**：实测 Jinx 白名单 47 条域**全部**被拦截集覆盖
  （例：`gm.mmstat.com` ← `mmstat.com`；`jpush.cn` 及其 9 个子域 ← `jpush.cn`）。
  顺序反了，微信/QQ/推送/统计类会集体解析失败。
- 必须排在 `geosite-cn → dns-cn` **之前**：国内广告域名多数也算大陆域名，
  排后面会被先放行、广告规则再无机会执行。

不需要新增任何 `rule_set` 条目 —— DNS 规则自 1.8.0 起支持 `rule_set`，直接复用 `route.rule_set` 里的 tag，
**不增加任何下载**，也不增加启动依赖。

### 本地验证记录（Android 配置，混合入站 + debug 日志）

| 域名 | 预期 | 实测 |
|---|---|---|
| `adservice.google.com`（在 jinx-ads） | 拦截 | ✅ `dns: lookup failed for adservice.google.com: NXDOMAIN` |
| `gm.mmstat.com`（白名单，被 `mmstat.com` 覆盖） | 放行 | ✅ `lookup succeed`（返回该域名的正常 A 记录） |
| `zlink.ugsdk.cn`（白名单，被 `ugsdk.cn` 覆盖） | 放行 | ✅ `lookup succeed`（返回该域名的正常 A 记录，16 条） |
| `www.gstatic.com`（不在任何广告集，不在白名单） | 正常 | ✅ `lookup succeed`（返回该域名的正常 A 记录）（走 dns-proxy） |
| `anthropic.com`（不在任何广告集） | 正常 | ✅ `lookup succeed`（返回该域名的正常 A 记录） |

⇒ 白名单放行 + 拦截生效 + 正常域名不受影响，三项全过。

### 必须接受的代价

1. **route 层规则不能删，也不只是「兜底」** —— 设备上任何**不经过 sing-box DNS** 的解析
   （应用自带 DoH/DoT、系统私有 DNS、明文 53 被 hijack 之外的路径）都能漏过 DNS 层。
   route 层是唯一兜得住的。
2. **拦截表现变了**：现在是「连接被拒」（`docs/LESSONS.md` L16 那条刷屏日志），
   改后是「域名解析不出来」。部分应用会重试更凶或弹错更明显。
   本次选 **NXDOMAIN**（最符合「这个域名不存在」的语义，应用通常直接放弃）。
3. **两处顺序得各自维护**：DNS 规则和 route 规则是两份独立的顺序表，改一处不能忘另一处。
4. `geoip-cn` 无法用于 DNS 规则（纯 IP 集只能是地址过滤器，见上）。

### 收益

- 广告域名在解析阶段就被拒，**不再产生连接** ⇒ `docs/LESSONS.md` L16 的拦截刷屏会明显减少。
- Android 后台反复重试的域名直接 NXDOMAIN，省掉一轮连接开销。

---

## 落地范围

- 本次只改**本地真节点配置**（`local/android-usai.json`）：`dns.rules` 4 → 6 条，其余字段零改动。
  三份 `profiles/1.14/*-lazy.json` **未改动**，等真机确认后再决定是否推广。
- 门禁见 `docs/LESSONS.md` L28。
