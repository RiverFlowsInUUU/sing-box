# CONFIG-ANATOMY — 当前配置长什么样

> **本文件面向 LLM**：只描述 `profiles/1.14/*-lazy.json` 的**当前实际状态**，
> 按执行顺序列，不讲故事、不重复踩坑史（那是 `LESSONS.md` 的活）。
>
> **唯一权威是配置文件本身。** 本文件若与 JSON 不一致，**以 JSON 为准**，并当场修本文件。
>
> 版本锚：`singbox_version.txt`（当前 `1.14.3`）。改配置前后各读一次本文件。

---

## 0. 一句话

```
嗅探域名 → 劫持 DNS → 本地解析成 IPv4 → 丢 IPv6
   → 局域网/白名单直连 → 广告拦截 → 智能组走专属出口 → 国内直连
   → 剩下的一律走 🚀 Proxy
```

---

## 1. 顶层结构（8 个键）

```
$schema · log · dns · inbounds · outbounds · route · http_clients · experimental
```

---

## 2. 出口层 `outbounds`（11 个，按数组顺序）

| # | tag | type | 说明 |
|---|---|---|---|
| 0–4 | `Node-01` … `Node-05` | vless / vmess / trojan / hysteria2 / shadowsocks | **占位节点**（`node-0X.example.com`），待替换 |
| 5 | `🚀 Proxy` | **urltest** | 默认出口。加入即可，自动测速 |
| 6 | `🤖 AI` | **urltest** | 智能组：AI 类站点专属优选，与代理组**独立** |
| 7 | `🚫 AD` | **selector** | `outbounds` 恒为 `["block"]`，`default` 恒为 `"block"` |
| 8 | `direct` | direct | 直连（非空，带 `domain_resolver`） |
| 9 | `direct-download` | direct | 规则集下载专用 |
| 10 | `block` | block | 黑洞 |

**两条硬约束**

- `🚀 Proxy` 与 `🤖 AI` 的 `outbounds` 里**只放真实节点，不嵌套组**
- 三个组的 tag **逐字带 emoji**（emoji + 一个 ASCII 空格 + 名字），写错一个字符 = 引用全落空

---

## 3. DNS 层（先于路由生效）

### 3.1 `dns.servers`（按顺序）

| # | tag | 协议 | 地址 | detour |
|---|---|---|---|---|
| 0 | `dns-bootstrap` | udp（**明文**） | `223.5.5.5` | 无（直连） |
| 1 | `dns-cn` | https | `223.5.5.5` | 无（直连） |
| 2 | `dns-proxy` | https | `8.8.8.8` | **`🚀 Proxy`** |

> `dns-bootstrap` 是明文，但**只用于解析「解析器自己的域名」**（鸡生蛋问题）。
> `final` 指向 `dns-proxy`，所以它不会成为常规查询的落点。

### 3.2 `dns.rules`（按顺序 —— **顺序是硬约束**）

| # | action | 匹配 | 结果 |
|---|---|---|---|
| 0 | `predefined` | `query_type: AAAA/HTTPS/SVCB` | `NOERROR`（空答案 = 禁 IPv6 查询） |
| 1 | `route` | `.lan` `.local` `.localdomain` `.home.arpa` | `dns-cn` |
| 2 | `route` | `geosite-private` | `dns-cn` |
| 3 | `route` | `jinx-direct` | `dns-cn` ← **必须最先于拦截** |
| 4 | `predefined` | `jinx-ads` + `awanue-ads` | **`NXDOMAIN`** ← 命中即"域名不存在" |
| 5 | `route` | `geosite-cn` | `dns-cn` |
| — | `final` | —— | **`dns-proxy`** |

> ⚠️ **顺序铁律**：`jinx-direct` → 拦截集 → `geosite-cn`。
> 国内广告域名多数也算大陆域名；`geosite-cn` 若排前面会先放行，广告再无机会拦。
>
> ⚠️ **`dns.rules` 与 `route.rules` 是两张独立的顺序表** —— 改一处必须同步另一处，否则静默失效。

**`dns` 顶层字段**：`final = dns-proxy` · `strategy = ipv4_only`（只管本地解析）

---

## 4. 路由层 `route.rules`（按顺序 —— **每条的位次都是硬约束**）

| # | action | 内容 | 说明 |
|---|---|---|---|
| 0 | `sniff` | —— | 嗅探真实域名，供后续规则匹配 |
| 1 | `hijack-dns` | `protocol: dns` | 把本机 DNS 查询交给上面的 DNS 层 |
| 2 | `resolve` | `strategy: ipv4_only` | **★ 必须在所有 route/reject 之前** |
| 3 | `reject` | `ip_version: 6` | 丢弃 IPv6 连接 |
| 4 | `reject` | `network: udp` + `port: 443` | **封 QUIC/HTTP3**：强制回落 TCP HTTPS |
| 5 | `route` | `ip_is_private` → `direct` | 局域网直连 |
| 6 | `route` | `jinx-direct` → `direct` | 白名单放行 |
| 7 | `route` | `jinx-ads` → `🚫 AD` | 拦截 |
| 8 | `route` | `awanue-ads` → `🚫 AD` | 拦截 |
| 9 | `route` | `geosite-ai` → `🤖 AI` | 智能组专用 |
| 10 | `route` | `geosite-private` → `direct` | 私有域名 |
| 11 | `route` | `geosite-cn` → `direct` | 大陆域名 |
| 12 | `route` | `geoip-cn` → `direct` | 大陆 IP |
| — | `final` | —— | **`🚀 Proxy`** |

> ⚠️ **[2] `resolve` 的位置是本仓踩过坑的地方**：它把域名在本地解析成 IPv4 字面量。
> **放末尾等于没放** —— 首个 route/reject 命中即 `break match`，后面根本不跑。
> 门禁：`resolve_not_first` / `resolve_not_ipv4_only` / `resolve_missing_ipv4_only`。

**关于 [4] 封 UDP 443（禁用 QUIC / HTTP3）**

两层配合，不是重复：

| 层 | 作用 | 覆盖什么 |
|---|---|---|
| DNS `rules[0]` 的 `HTTPS`/`SVCB` → `NOERROR` | 客户端**查不到** `alpn=h3`，多数不会尝试 QUIC | 依赖客户端尊重 DNS 发现机制 |
| route `rules[4]` 的 `udp/443` → `reject` | **连接层直接丢**，无论客户端怎么想的 | 兜底：DNS 被绕过 / 客户端硬编码 h3 也拦得住 |

> 两条 `reject`（[3] 地址族 / [4] 传输层）是**不同维度**，不能合并成一条。
> 位置固定在 `resolve` 之后、所有分流之前 —— UDP 443 **无论去哪都拦**，不需先判国内国外。

**`route` 顶层字段**

| 字段 | 值 | 为什么 |
|---|---|---|
| `final` | `🚀 Proxy` | 兜底出口 |
| `auto_detect_interface` | **`true`** | **缺了它：能启动、不报错，但真机完全没网**（出站回灌 tun） |
| `default_domain_resolver` | `{'server': 'dns-bootstrap'}` | |

---

## 5. 规则集 `route.rule_set`（7 个）

| tag | 用途 | 格式 | 来源 | interval |
|---|---|---|---|---|
| `jinx-direct` | 白名单放行（47 条） | source | `RiverFlowsInUUU/Jinx@main/sing-box-direct.json` | 1d |
| `jinx-ads` | 广告拦截（3901 条） | source | `RiverFlowsInUUU/Jinx@main/sing-box-ads.json` | 1d |
| `awanue-ads` | 广告补充（965 条） | source | `TG-Twilight/AWAvenue-Ads-Rule@main/...` | 1d |
| `geosite-private` | 局域网/私有域名 | binary | `MetaCubeX/meta-rules-dat@sing` | 7d |
| `geosite-ai` | AI 服务域名 | binary | 同上 | 7d |
| `geosite-cn` | 大陆域名 | binary | 同上 | 7d |
| `geoip-cn` | 大陆 IP | binary | 同上 | 7d |

**统一约定**

- URL 前缀一律 `https://testingcf.jsdelivr.net/gh/`（**不用** `raw.githubusercontent.com`）
- 每个都带 `"http_client": "ruleset-dl"`

> ⚠️ **定义顺序 ≠ 生效顺序。** 规则集在 `rule_set` 数组里的先后**不影响匹配**，
> 真正决定顺序的是它们在 `route.rules` 里的**首次出现位置**（见 §4）。
> 门禁 `jinx_order` 判的正是后者。

---

## 6. 其他顶层

| 块 | 内容 |
|---|---|
| `http_clients` | `ruleset-dl`（规则集下载用；其 `domain_resolver` 走 `dns-bootstrap`） |
| `experimental.cache_file` | `enabled: true` · `path: cache.db`（**相对路径**）· `store_dns: true` · `cache_id` 见 §7 |
| `log` | `level: warn` · `timestamp: true` |

---

## 7. 三端差异（**全部差异只有 3 处**）

对其余 75 个字段，三端逐字相同。

| JSON 路径 | desktop | android | ios |
|---|---|---|---|
| `inbounds[].address[]` | `172.19.0.1/30` | `172.19.0.1/30` | `fdfe:dcba:9876::1/126` |
| `inbounds[].strict_route` | `true` | **（删除）** | **（删除）** |
| `experimental.cache_file.cache_id` | `sb-template-1.14` | `sb-template-1.14-android` | `sb-template-1.14-ios` |

> ⚠️ **改任一处必须同时落三处**：① 对应 profile；② `PLATFORM-MATRIX.md` §4 一行；
> ③ 必要时加门禁。缺一即静默失效（门禁 `matrix_platform_stale` / `profile_drift` 逐格对账）。

---

## 8. 改配置时按这个查

| 想改什么 | 动哪 | 别忘了 |
|---|---|---|
| 加节点 | `outbounds` + 目标组的 `outbounds` 数组 | 用 `python tools/mknode.py`，别手抄 |
| 换分流落点 | `route.rules[].outbound` | 检查 `final` 与组 tag 拼写 |
| 调拦截 | `route.rules` **和** `dns.rules` **同步** | 两张顺序表，改一漏一即静默失效 |
| 动平台差异 | profile + `PLATFORM-MATRIX.md` §4 | 三端都要看 |
| 改任何文件 | —— | 用 `tools/patch-text.py`（见 `AGENTS.md` §0） |
| 改完 | `bash tools/check-all.sh --run` | 退出码 0 才交付 |

---

## 9. 本文件的维护规矩

- **只写当前状态**，不写历史与踩坑经过（那些在 `LESSONS.md` / `DECISIONS.md`）。
- **与 JSON 不符时以 JSON 为准**，并当场修本文件。
- 改配置导致结构变化时，**同一批改动里同步本文件**，否则它会变成第三种说法。
