# 实证：resolve/ipv4_only 在本机 100% 生效，出口仍出现 IPv6 ⇒ 责任在服务端

- **日期**：2026-10-12
- **环境**：sing-box `1.14.3`（Windows amd64），本机测试配置（由 `local/android-usai.json` 派生，不入库：
  tun 入站换 mixed `127.0.0.1:12095`，`log.level = debug`）
- **节点**：用户真实 hysteria2 节点（`local/` 内，不入库）
- **目的**：判定用户 m03448/m03531 报的「配置了 `resolve`+`ipv4_only` 仍看到 IPv6 出口」到底出在哪一段

> ⚠️ 本记录的作用是**把「已经证实」和「还没证实」分开**。本机不能用来验「能不能上网」（AGENTS.md 铁律 11），
> 但**能**用来验「本机往出站递了什么」—— 这就是本文记录的东西。

---

## 1. 本机递给出站的是什么：**100% IPv4 字面量**

`log.level = debug` 下，`router: resolved [...]` 与 `outbound connection to ...` 成对出现，同一次请求可一一对应：

| 域名 | `router: resolved` | `outbound connection to` |
|---|---|---|
| `ifconfig.me` | `resolved [34.160.111.145]` | `outbound connection to 34.160.111.145:443` |
| `ip.sb` | `resolved [172.67.75.172 104.26.12.31 104.26.13.31]` | `outbound connection to 172.67.75.172:443` |
| `claude.ai` | `resolved [160.79.104.10]` | `outbound connection to 160.79.104.10:443` |

**日志里的形态本身就能区分两件事**：

- `outbound connection to 162.159.141.147:443` ← 目标是 IP 字面量 = `resolve` 生效，已 `DialSerialNetwork`
- `outbound connection to www.gstatic.com:80` ← 目标是域名 = `DestinationAddresses` 为空，域名原样交给服务端

同一批日志里两类形态同时存在，说明日志能如实反映差异，**没有出现「目标写 IPv4、实际却发出 IPv6」的情况**。

## 2. 同一时刻，出口观察到的 IP

用 `https://<域名>/cdn-cgi/trace` 读 `ip=`（即 `ip.net.coffee` 首页表格用的同一个字段）：

| 域名 | 本机拨出目标 | 网站看到的出口 |
|---|---|---|
| `ifconfig.me` | `34.160.111.145:443` | `2001:db8::a` ← **IPv6**（已脱敏） |
| `ip.sb` | `172.67.75.172:443` | `2001:db8::a` ← **IPv6**（已脱敏） |
| `claude.ai` | `160.79.104.10:443` | `203.0.113.7`（已脱敏） |
| 其余 21 个域名（`chatgpt.com` / `grok.com` / `perplexity.ai` / `notion.so` / `gitlab.com` …） | 全为 IPv4 字面量 | 全为 `203.0.113.7`（已脱敏） |

**关键**：本地递出去的是 `34.160.111.145` 这种 IPv4 字面量，服务端**不可能**把它当成 IPv6 发出去。
⇒ 第 2 段（服务端出网）的地址族**不在本地配置的控制范围内**。

## 3. 出口那个 IPv6 是谁

```
<节点域名>   A    = <IPv4>   ← 表中「走 IPv4」的出口
<节点域名>   AAAA = <IPv6>   ← 表中「走 IPv6」的出口
```

> 🔒 **本文件不记录真实域名与真实 IP**（AGENTS.md 铁律 7）。
> 上面两行的真实值只存在于 `local/`（已 gitignore）。判断所需的信息是「两者相等」这个关系，
> 与具体数值无关 —— 所以脱敏不影响本记录的证据效力。

节点自己的 AAAA 记录，与表中 IPv6 出口**完全一致**。
⇒ 网站看到的 IP 就是这台 VPS 自身；既不是本机泄漏，也不是本机 DNS 泄漏。

## 4. 出口地址族是**随时间变化**的，不是随连接随机

- 首轮（本文件记录前约 2 小时）：18 个域名**全部**显示 IPv6
- 本轮：23 个域名里只有 2 个显示 IPv6，其余全 IPv4
- `anthropic.com` 同一域名**连测 20 次**：`IPv4=20 / IPv6=0 / 失败=0`（本轮），但首轮该域名是 IPv6

⇒ 属于服务端侧出网策略/路由的变化（NAT64、或服务端 `sniff` 后自行重解析域名），**不是每连接随机选择**。

## 5. 结论与边界

**已证实**：

1. `resolve` + `strategy: ipv4_only` 在本机**确实生效** —— 出站拿到的是 IPv4 字面量，日志可证。
2. 本机侧没有任何 IPv6 流量进入隧道（SFA `VPNService.kt` 只在存在 IPv6 地址时才 `addRoute("::", 0)`；本机也没拿到全局 IPv6）。
3. 出口出现 IPv6 时，那个地址 = VPS 自己的 IPv6 ⇒ **该段由服务端决定，客户端配置改不了**。

**未证实（不要写成结论）**：

4. 服务端**为什么**在某些时刻选 IPv6（NAT64 / 服务端 sniff 重解析 / 上游路由）—— **未取得服务端配置或日志，属于推断**。
5. 「禁用服务端 IPv6 即可解决」—— 未在真实 VPS 上验证过；这是**建议**，不是已验证的修法。

## 6. 对仓库的影响

- `tools/audit.py` 的 `resolve_not_ipv4_only` / `resolve_missing_ipv4_only` / `resolve_not_first` 门禁**保持不变** ——
  它们守的是「本机递出去必须是 IPv4 字面量」，本文证明这一步是必要且有效的。
- `docs/LESSONS.md` L18 的「服务端**不可能**再选 IPv6」逐字与本文第 2 节冲突，已改为**分段表述**。
