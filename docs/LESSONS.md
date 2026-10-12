# 事故台账（LESSONS）

> **这份文件是给 AI 读的。**每次生成/修改配置之前先扫一遍本文件，逐条对照自检。
> 每条教训都必须有：现象 → 根因（含源码位置）→ 为什么没被拦住 → 修法 → 已加的门禁 code。
>
> **格式是机读的**：`### L<n> <标题>` 开头，`门禁：` 行列出该教训对应的 `audit.py` 门禁 code
> （多个用 `,` 分隔，没有就写 `无`）。`tools/audit.py` 的 `audit_lessons()` 会校验这些 code
> 在代码里真实存在 —— 防止"文档写了门禁、代码里根本没实现"。
>
> 加新教训时：**先写 L 条目，再把门禁 code 实现出来**，或者反过来，但两边必须对得上。

---

## L1 空 direct 出站导致远程规则集下载 FATAL

**现象**（用户真机报错原文）

```
start or reload service: start router:
(initialize rule-set[4]: initial rule-set: geoip-cn: Get "https://cdn.jsdelivr.net/gh/...": detour to an empty direct outbound makes no sense
 | initialize rule-set[1]: initial rule-set: geosite-cn: Get "...": detour to an empty direct outbound makes no sense)
```

**根因**

- `common/dialer/detour.go`：`DetourDialer.init()` 里
  `if !d.defaultOutbound && !d.disableEmptyDirectCheck { if directDialer, isDirect := dialer.(DirectDialer); isDirect && directDialer.IsEmpty() { d.initErr = E.New("detour to an empty direct outbound makes no sense") } }`
- `protocol/direct/outbound.go`：`isEmpty` 用 `reflect.DeepEqual(options.DialerOptions, ...)` 判定 ——
  **DialerOptions 里一个非默认字段都没有**就是"空 direct"。
- `route/rule/rule_set_remote.go` 的 `resolveTransport()`：走显式 `http_client` 时**不设**
  `DisableEmptyDirectCheck`；只有已废弃的 `download_detour` 路径才设。
- 所以"规则集下载走的 direct 出站"如果是个裸 `{"type":"direct","tag":"direct"}`，必然炸。

**为什么没被拦住**

`sing-box check` **完全静默（exit=0）**。空 direct 的检查发生在 `run` 阶段初始化规则集时。
当时我们的门禁只跑 `check`，没有真启动。

**修法**

给规则集下载配专用的非空 direct 出站：

```jsonc
{ "type": "direct", "tag": "direct-download", "domain_resolver": { "server": "dns-bootstrap" } }
```

`http_clients[].detour` 指向 `direct-download`（不是裸 `direct`）。
⚠️ `domain_strategy` **不算**非空字段（`option/outbound.go` 已标 `Deprecated: migrated to domain resolver` + `schema:"omit"`），
1.14 下写了还会直接 FATAL。可用字段见 `audit.py` 的 `NON_EMPTY` 常量。

**门禁**：`download_detour_empty_direct`, `dangling_download_detour`, `no_download_direct`, `download_uses_main_direct`, `singbox_run`

**同时新增的能力**：`tools/audit.py --run --run-seconds 20` ——
把 tun 入站临时换成 mixed、`cache_file.path` 指向临时目录，真启动一次，只筛 `FATAL` 行。
`check` 过 ≠ 能启动，这条是那次事故换来的。

**涉及**：`profiles/1.14/*.json`、`templates/groups.json`、`tools/audit.py`、`.github/workflows/audit.yml`
**commit**：`c07abfd`

---

## L2 缺 `route.auto_detect_interface` 导致「能启动但没网」

**现象**（用户真机原话）

> 「新配置在安卓设备上可以启动，仅仅是可以启动。但是没网，存在内存泄漏，首页显示的内存占用高达一个GB，
> 瞬间爆发了上万个入站跟出站的请求。同时所有的节点都没有延迟数据，意味着所有节点都不可用，
> 仅有上传流量，没有下载流量。」

**根因**

- `common/dialer/default.go` 的 `NewDefault`：只有
  `networkManager.AutoDetectInterface() && !disableDefaultBind` 成立，
  才会给 `dialer.Control` / `listener.Control` 挂上 `ProtectFunc()`。
- `route/network.go`：`func (r *NetworkManager) AutoDetectInterface() bool { return r.autoDetectInterface }`，
  而 `autoDetectInterface` 直接来自 `route.auto_detect_interface`。
- 没写 ⇒ 出站 socket **一个 Control 也不挂** ⇒ Android VpnService 把 sing-box 自己的流量
  也抓进隧道（SFA 的 `Settings.allowBypass` 默认 `false`）⇒ 出站回灌 tun。
- 回灌后果：节点测速全部失败（无延迟数据）→ 流量只进不出（只有上传）→
  urltest 每 3 分钟一轮反复重试（连接数上万、内存飙到 1GB）。
- 官方原文（`docs/configuration/inbound/tun.md`）：
  *To avoid traffic loopback, set `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`*
  Android 图形客户端上后两个都需要真实网卡名，**唯一可行的是 `auto_detect_interface`**。
- Android 上能过平台检查是因为 `constant/os.go`：`IsLinux = goos.IsLinux == 1 || goos.IsAndroid == 1`。

**为什么没被拦住**

**`sing-box check` 对此完全静默**，`run` 也能正常启动并"存活"——
这个字段只在拨号时生效，不影响启动。

**修法**

`route` 里加 `"auto_detect_interface": true`。

**门禁**：`tun_without_auto_detect_interface`, `android_override_vpn_no_adi`

**涉及**：`profiles/1.14/*.json`、`local/android.json`、`templates/groups.json`、`tools/audit.py`、`AGENTS.md`、`docs/*`
**commit**：`8977f21`

---

## L3 拿本机脏环境的连通性结论当证据

**现象**

我给用户的上一版配置出错后，声称"实测能上网、curl 返回 204 正常"。
实际本机有 **OpenClash 网关**在劫持 DNS。

**证据（本机实测）**

一份**完全不含 fakeip 配置**的最小配置（只有 udp `223.5.5.5` + mixed 入站 + direct 出站），
查 `testingcf.jsdelivr.net` 时 `223.5.5.5` 仍然返回 `198.18.0.70`（fakeip 网段）——
证明本机另有带 TUN + fakeip 的进程在劫持 DNS。**这个环境里跑出来的任何连通性结论都是假的。**

**修法（铁律 11）**

排查问题只允许三种手段：**读配置、读官方文档、读 sing-box 源码**。
`sing-box check` 与 `audit.py --run` 只用来验「**能不能启动**」，**不准用来验「能不能上网」**。
给用户的交付说明里必须明确写：只证明能启动，联网结论只能由用户在真机给出。

**门禁**：无（这是流程约束，不是配置约束；由 `AGENTS.md` 铁律 11 与 `docs/WORKFLOW.md` 约束）

---

## L4 凭印象增删字段，不跟用户原始配置做差异比对

**现象**

用户给的第一份配置里**本来就有** `"auto_detect_interface": true`。
我生成 `sb-template/profiles/1.14/*.json` 时凭印象重写，把它删掉了，
直接导致 L2 的整起事故。

**根因**

生成流程里**没有"差异比对"这一步**。我按自己的模板从头写配置，
没有把"用户原始配置"当作基线逐键对比，于是丢字段、加字段都不自知。

**修法（写流程，不靠自觉）**

生成或修改配置前/后**必做**：

```bash
python - <<'EOF'
import json
# 逐键比对「用户给的原始配置」与「我生成的配置」
a = json.load(open("用户原始配置.json", encoding="utf-8"))
b = json.load(open("我生成的配置.json", encoding="utf-8"))
def walk(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from walk(v, f"{p}.{k}" if p else k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{p}[{i}]")
    else: yield p, o
A, B = dict(walk(a)), dict(walk(b))
print("只在原始配置里（可能被我删了）:", sorted(set(A) - set(B)))
print("只在生成配置里（可能是我加的）:", sorted(set(B) - set(A)))
for k in sorted(set(A) & set(B)):
    if A[k] != B[k]: print(f"改了: {k}: {A[k]!r} -> {B[k]!r}")
EOF
```

**每一个差异都必须能说出为什么**。说不出原因的，就按原始配置保留。

**门禁**：无（流程约束，由 `AGENTS.md` 第 0 节与 `docs/WORKFLOW.md` A0 节约束）

---

## L5 Jinx 广告规则集的顺序铁律

**现象**

广告规则集换成 Jinx 后，必须保证 `jinx-direct`（放行）在 `jinx-ads`（拦截）**之前**。

**根因**

国内广告域名大多同时属于 `geosite-cn`。如果先把 `geosite-cn` 判给 `direct`，
广告域名就永远不会走到拦截规则 → 广告拦截失效。

**修法（顺序铁律）**

```
jinx-direct → direct
jinx-ads    → AD
awanue-ads  → AD
geosite-cn  → direct
```

前三条必须紧邻且顺序固定，且都必须排在 `geosite-cn` **之前**。

**门禁**：`jinx_incomplete`, `jinx_order`, `jinx_url`, `jinx_format`, `jinx_ads_target`

---

## L7 仓库里出现真实节点

**现象/风险**

`profiles/` 是公开仓库的一部分。一旦把带真实 server / 密码 / uuid 的节点写进去并提交，凭据就永久泄露到 git 历史。

**修法（铁律 7）**

- `profiles/` 下 `outbounds[].server` 只能是占位域名（`.example.com` 等）。
- 含真实凭据的配置一律放仓库外的 `local/`（已在 `.gitignore`）。
- 给用户的成品放仓库外（如桌面）。

**门禁**：`placeholder_server`

---

## L8 平台能力差异

**现象/风险**

iOS / Android 客户端未实现的字段写了不一定报错，但真机上行为异常或完全不生效。

**已确认的坑**

- `inbounds[type=tun].strict_route`：Android / Apple 未实现（桌面可用）
- `outbound.domain_resolver` 指向 `local` 类型 DNS：Android 上不总能工作
- `route.override_android_vpn`：必须同时开 `auto_detect_interface` 才有意义

依据 `docs/PLATFORM-MATRIX.md` + 官方 `docs/clients/*/features.md`。

**门禁**：`platform_strict_route`, `android_resolver`, `android_override_vpn_no_adi`

---

## L9 出站骨架与引用完整性

**现象/风险**

分流组骨架被改错（Proxy 不是 urltest、AI 被改成 selector、AD 被塞代理节点），
组里嵌组（`AI.outbounds` 里放 `Proxy`，两个 urltest 串联测速），
或引用了不存在的 tag —— 这类错误 `check` 不会报，运行时才炸或静默失效。

**背景（m02132 用户要求）**

用户原话：「ai 分流组不要 proxy 作为子节点，直接就是 urltest +台湾节点」。
原因：`AI` 若只是指向 `Proxy` 的 selector，它与 `Proxy` 完全同源，AI 组形同虚设；
而 `urltest` 套 `urltest` 会串联两次测速（外层只拿到内层已选中的那一个节点）。

**修法**

骨架固定在 `templates/groups.json`；每个 profile 的出站必须与它一致，只往 `outbounds` 数组里加节点 tag。
- `Proxy` 与 `AI` **都是 urltest**，各自在组内节点间独立优选；`AI` 只放用户指定给 AI 的节点（如全部台湾节点）。
- `Proxy` / `AI` / `AD` 的 `outbounds` 里**只允许出现真实节点 tag**，不得引用其它组。
- 骨架模板 `templates/groups.json` 里 `Proxy` / `AI` 的 `outbounds` 允许为空（占位），
  自行生成的 profile 里为空则报 WARN `empty_group_skeleton`。

**门禁**：`dup_tag`, `empty_group`, `empty_group_skeleton`, `urltest_no_url`, `final_missing`, `dangling_ref`, `group_wrong_type`, `group_nesting`, `rule_outbound_missing`, `rule_ruleset_missing`, `ad_group_polluted`, `template_missing`, `template_json`, `template_group_missing`, `template_legacy_auto`, `template_proxy_not_urltest`, `template_proxy_no_url`, `template_ai_not_urltest`, `template_ai_no_url`, `template_ad_polluted`

---

## L10 规则集 URL 与下载方式

**现象/风险**

- 用 `raw.githubusercontent.com`：国内经常连不上，规则集下载失败 → 启动 FATAL
- 不写 `http_client` / 写已废弃的 `download_detour`：1.14 起前者是唯一正确写法
- URL 不以 `.srs` / `.json` 结尾又不写 `format`：无法推断格式

**门禁**：`ruleset_url`, `ruleset_url_raw`, `ruleset_http_client`, `ruleset_download_detour`, `ruleset_format`

---

## L11 缓存文件路径

**现象/风险**

`experimental.cache_file.path` 指向的**父目录不存在**时，`CacheFile.start()` 直接 ENOENT，**启动失败**。
sing-box 的 cachefile 包**不会创建父目录**（全包无 `Mkdir`/`MkdirAll`），`os.O_CREATE` 只能建文件。
含 `..` 的相对路径还依赖工作目录，跨平台不可靠。

**修法**：用工作目录内的相对文件名（`cache.db`）。

**门禁**：`cache_path_abs`, `cache_path_parent`

---

## L12 DNS 引用完整性

**现象/风险**

`dns.rules[].server` / `rule_set` / `dns.final` / `route.default_domain_resolver.server`
指向不存在的 tag 时，启动期才报错。

**门禁**：`dns_final_missing`, `dns_rule_server_missing`, `dns_rule_ruleset_missing`, `ddr_missing`

---

## L13 新旧写法并存

**现象/风险**

`http_clients` 与已废弃的 `download_detour` 同时出现 → 直接 `FATAL http_client is conflict with deprecated download_detour field`。

**门禁**：`http_client_conflict`

---

## L14 反向：门禁自身出错（`UnboundLocalError`）

**现象**

`tools/audit.py` 曾经把 `route = cfg.get("route", {})` 写在首次用到它**之后**，
导致 `UnboundLocalError`，整个门禁直接崩掉——**门禁崩了比没有门禁更危险**（会让人以为检查过了）。

**修法**

- 所有 `cfg.get(...)` 的局部变量绑定必须放在 `audit_repo_rules()` 函数最前面。
- 门禁本身跑不通时，`main()` 必须返回非 0（CI 才会红）。
- 每次改完 `audit.py`，**必须跑一次负向测试**：故意把配置改坏，确认能报出预期的 ERROR。

**门禁**：无（这是对门禁自身的约束，见 `AGENTS.md` 第 4 节校验命令）

---

## L15 文档写了门禁、代码里没有（或反过来）

**现象/风险**

本文件声称某个门禁存在，而 `tools/audit.py` 里根本没这个 code —— 等于**假装有防护**；
反过来，代码里新加了门禁却没人知道它拦的是什么事故，下次有人觉得碍事就删了。

**修法（双向可追溯）**

`tools/audit.py` 的 `audit_lessons()` 对此做机器校验（并已接入 `main()`，不经 `--lessons`）：

1. **方向一（本文件 → 代码）**：本文件每条 `**门禁**：` 行里以反引号包裹的 code
   （形如 `xxx_yyy`），必须在 `tools/audit.py` 源码里以 `rep.error("xxx_yyy"` 或
   `rep.warn("xxx_yyy"` 真实出现，否则报 ERROR `lessons_missing_gate`。
2. **方向二（代码 → 本文件）**：`tools/audit.py` 里每个非框架 code 都必须在
   某个 `docs/*.md` 里出现过，或在 `tools/audit.py` 内的已知白名单里，
   否则报 ERROR `gate_without_lesson`。

**白名单（框架性/非配置类，不要求有教训条目）**：
`json`, `no_singbox`, `run_skipped`, `singbox_check`, `singbox_run`, `singbox_run_tun`, `singbox_timeout`

**门禁**：`lessons_missing_gate`, `gate_without_lesson`, `lessons_missing`

---

## L16 「AD 分流组有错/拦截失效」的日志噪音与误报

**现象**（用户真机原话，m02378）

> 「好像日志里面总是报这个 ad 分流组有错，你看看这是问题吗
> ERROR[0011] [449027481 5ms] connection: open connection to 142.250.198.40:443 using outbound/selector[AD]: operation not permitted」

**结论：这是拦截成功的正常日志，不是故障，也不是配置错误。**

**根因**

- `protocol/block/outbound.go`：
  `func (h *Outbound) DialContext(...) (net.Conn, error) { h.logger.InfoContext(ctx, "blocked connection to ", destination); return nil, syscall.EPERM }`
- `route/conn.go:105-123` 的 `NewConnection`：拨号出错就把 err 包一层 `E.Cause(err, "open connection to ", remoteString, " using outbound/", outbound.Type(), "[", outbound.Tag(), "]")`，
  然后 `m.logger.ErrorContext(ctx, err)` —— **拦截走的就是这条“拨号失败”路径**。
- 所以拦一次广告 = 一行 `INFO outbound/block[block]: blocked connection to ...`
  + 一行 `ERROR connection: open connection to ... using outbound/selector[AD]: operation not permitted`。
- 本机实测（`C:/Users/Administrator/_probe/ademo/ad.json`，mixed 入站 + AD selector(default block)）：
  日志输出与用户手机完全一致，`curl` 返回 SSL 错误（rc=35），即连接被切断。

**为什么容易误判**

- 日志写的是 `outbound/selector[AD]` 而不是 `block` —— 因为它打印的是**本连接被选中**的那层出站；
  `AD` 是 selector，真正拨号的是它当前选中的 `block`。
- 同一个 `142.250.198.0/24` 段（Google）反复出现，因为 Android 后台反复重试推送/统计接口、
  而这些域名确实在 `jinx-ads`（`firebaselogging-pa.googleapis.com`、`crashlyticsreports-pa.googleapis.com`、
  `adservice.google.com` 等，共 3751 条 `domain_suffix`）/`awanue-ads` 里。
- 本机解析 `firebaselogging-pa.googleapis.com` → `172.217.112.4` 等，`crashlyticsreports-pa.googleapis.com` → `142.251.210.142` ——
  与用户日志同属 Google。

**修法**

1. **不需要改任何配置**。`AD` selector 的 `default: "block"` 正确，广告确实被拦住了。
2. 嫌日志刷屏（手机上会持续写盘、耗电），把日志压到静音：
   `"log": { "level": "panic", "timestamp": true }` 或 `"log": { "disabled": true }`
   （`option/options.go:69-75` 的 `LogOptions`：`disabled` / `level` / `output` / `timestamp`）。
3. 若想让广告**真的失败而不是被切断**也可以，那是 `action: "reject"` 而**不是** `block` 出站，
   但**不建议**：`reject` 支持不了 AD 分组的运行时切换，而 `AD` selector 是骨架的一部分。

**对比：`block` 出站 vs `action: reject`（本机实测）**

| | 日志 | 客户端看到 | 能否被 selector 切换 |
|---|---|---|---|
| `AD` → `block` 出站 | INFO + **ERROR** 各一行 | TCP RST（SSL error） | 能 |
| `action: "reject"` | 仅 DEBUG `router: connection closed: rejected` | TCP RST（SSL error） | 不能 |

**门禁**：`ads_block_log_noise`, `ad_group_default_not_block`

**涉及**：`tools/audit.py`（4b 节 INFO + 4 节 default 校验；不要改成 WARN，否则自检恒不干净）

---

## L17 「只走 IPv4」写了 dns.strategy 却没用 —— 域名被原样交给代理服务端

**现象**（用户真机反馈，m02566 → m02616）

> 「访问境外网站只走 IPv4，不走 IPv6」
> 「不对哦，访问境外网站，我看他们还是说有 IPV6 的请求 我用 https://ip.net.coffee/测的」

**结论：这多半不是配置漏了，而是「本地能控制的 IPv4 强制」有边界。**

**根因（源码路径）**

1. `dns.strategy: "ipv4_only"` 只管**本地 DNS 解析**（`dns/client.go:451-486` 的 `Lookup` 遇 `ipv4_only` 只查 `TypeA`；`dns/client.go:270` 对 AAAA 直接返回空 NOERROR）。
   配置里 `dns.rules[0] = {"query_type":["AAAA","HTTPS","SVCB"],"action":"predefined","rcode":"NOERROR"}`
   （`dns/router.go:750-755`）也只掐死「本地发起的 AAAA 查询」。
2. 但代理出站默认拿到的是**域名**：`route/conn.go:103-104` 只有
   `len(metadata.DestinationAddresses) > 0 || metadata.Destination.IsIP()` 时才走 `dialer.DialSerialNetwork(...)`，
   否则走 `this.DialContext(ctx, N.NetworkTCP, metadata.Destination)` —— 域名原样发给服务端。
3. 服务端（VPS）自己去解析这个域名，**它可能选 IPv6**。本地无从约束。
   `ip.net.coffee` 首页的「分流出口 IP 汇总」用 `compactIp()` 压缩 IPv6 显示，
   所以这里看到 IPv6 地址 = 该站点真的以 IPv6 出口出去了。
4. `{"ip_version":6,"action":"reject"}` **挡不住这种情况**：`route/rule/rule_item_ipversion.go` 的
   `IPVersionItem.Match` = `metadata.IPVersion != 0 && metadata.IPVersion == 6 == r.isIPv6 ||
   metadata.Destination.IsIP() && metadata.Destination.IsIPv6() == r.isIPv6` —— 只认 IP 字面量或 DNS 侧写的 IPVersion，
   域名连接在没 resolve 前一律不匹配。

**修法：在 `route.rules` 里加 `{"action": "resolve", "strategy": "ipv4_only"}`**

- `route/route.go:893-922` 的 `actionResolve()` 解析后写 `metadata.DestinationAddresses`；
  `route/conn.go:103-104` 随即改走 `DialSerialNetwork`，
  `common/dialer/default_parallel_network.go:16-45` 最终 `dialer.DialContext(ctx, network, M.SocksaddrFrom(address, destination.Port))`
  → **拨号目标是 IPv4 字面量，代理收到的就是 IP，服务端没有选择余地。**
- 放**在 `{"protocol":"dns","action":"hijack-dns"}` 之后、`{"ip_version":6,"action":"reject"}` 之前**。
  ⚠️ **本条目最初写的“放在最后一条规则”是错的，已由 L18 推翻** —— `resolve` 是继续匹配的中间动作，
  但 `route`/`reject`/`bypass` 一命中就 `break match`，放在末尾只会作用于“落到 final 的那部分流量”，
  命中 `route(AI)` / `route(AD)` / `route(direct)` 的域名仍然走不到它。具体复现见 L18。
- 位置要求：必须排在所有 `route`/`reject`/`bypass` 之前（详见 L18）。
- `strategy` 必须**显式写 `ipv4_only`**：不写就继承 `dns.strategy`，哪天有人把 `dns.strategy` 改成 `prefer_ipv4`
  就会静默退化成「优先 IPv4 但允许 IPv6」。

**为什么以前没被拦住**

- `sing-box check` 完全通过；`audit.py --run` 也能存活 —— 这两个只证明「配置合法、能启动」，不证明「端到端 IPv4」。
- 「IPv6 从哪来」有很长一段时间被误归因为「本地 tun 没配 IPv6 就不该有 IPv6 流量」。
  实际上本地确实进不来 IPv6（SFA `VPNService.kt` 只在存在 IPv6 地址时才 `addRoute("::", 0)`），
  **漏点在 VPS 侧出网**。
- 也误信过 `ip.net.coffee` 会「报 IPv6 请求」——查遍该站五个页面（`/`、`/dns/`、`/webrtc/`、`/claude/`、`/claude/ipv6.html`）
  **没有任何这种判定输出**；`/dns/` 页的「原因三：IPv6 DNS 绕过代理」只是静态科普段落。

**门禁**：`resolve_not_ipv4_only`, `resolve_missing_ipv4_only`

**涉及**：`tools/audit.py`（6 节）；`profiles/1.14/{android,desktop,ios}-lazy.json`、`local/android-usai.json` 的 `route.rules` 末尾

**边界（必须如实告知用户）**：本手段能保证**代理连接的目标地址是 IPv4**。
若服务端自己还要再解析一层（例如它按域名二次请求），那一段仍不受本地控制。
⚠️ **但“放在 `route.rules` 末尾”这个位置本身是错的，L17 当时没看出来 —— 见 L18。**

---

## L18 `resolve` 放末尾等于没放 —— 首个 route/reject 一命中就 break match

**现象**（用户真机追问，m03112）

> 「刚才 A 也漏 ipv6 是不是没法解决？」
> 即：已经按 L17 加了 `{"action":"resolve","strategy":"ipv4_only"}`（放 `route.rules` 末尾），
> `ip.net.coffee` 首页的「分流出口 IP 汇总」里那 18 个域名**仍然显示 IPv6 出口**。

**根因（源码路径 + 本机复现）**

- `route/route.go:688-705` 的 `matchRule` 循环里，`resolve` 是「继续匹配」的中间动作；
  只有 `route` / `reject` / `hijack-dns` / `bypass` 会 `break match`（`actionType == C.RuleActionTypeRoute || Reject || HijackDNS`，
  以及 `RuleActionTypeBypass` 且带 `outbound`）。
- 因此 **落在末尾的 `resolve` 只对“前面所有规则都没命中”的流量生效** —— 也就是最终走到 `final` 的那部分。
  任何被 `route(AI)` / `route(AD)` / `route(direct)` 命中的域名连接，
  在命中那一刻就 `break match` 了，**根本走不到末尾那条 resolve**，域名原样交给代理服务端。
- 而 `dns.rules` 里的 `geosite-ai` / `geosite-cn` 是 **DNS 规则集**（只决定用哪个 DNS server 查），
  不代表这条解析结果会写进 `metadata.DestinationAddresses`；
  `route/conn.go:103-104` 仍因 `DestinationAddresses` 为空而走 `this.DialContext(...)`，把域名发给服务端。

**本机决定性复现**（`sing-box 1.14.3`，tun 换 mixed，`log.level=debug`）

| 顺序 | 访问 `claude.ai` | 访问 `example.org` | `resolved [` 条数 |
|---|---|---|---|
| resolve 在**末尾**（= L17 的做法） | `match[7] rule_set=geosite-ai => route(AI)`，**无 resolve 行** | `match[11] => resolve(ipv4_only)` | 1（仅 example.org） |
| resolve 在 **hijack-dns 之后**（修法） | `match[2] => resolve(ipv4_only)` → `match[8] rule_set=geosite-ai => route(AI)` | 同样先 resolve | 4（含 `claude.ai` → `160.79.104.10`） |

修后 `claude.ai` 被解析成 `160.79.104.10`（Anthropic IPv4）、`api.openai.com` 同理，
而 `www.qq.com` 也先 resolve 一次（`121.14.77.221`）再被 `geosite-cn → direct` 命中 —— 国内直连多一次本地查询，代价可接受。

**真实节点端到端实证**（用用户真实 hysteria2 节点，非 direct 仿真）：

```
$ curl -x http://127.0.0.1:12090 https://claude.ai/   →  HTTP 403（可达）
$ grep "outbound connection to" real-A.log
outbound connection to 160.79.104.10:443      ← hy2 出站拿到的是 IPv4 字面量
```

即：**第一段（本地 → 服务端）已被证实锁定在 IPv4**：hy2 出站拿到的是 IPv4 字面量。

**同一配置下仍出现 IPv6 出口的实测（2026-10-12，完整记录见
[`docs/evidence/2026-10-12-resolve-ipv4-vs-vps-egress.md`](evidence/2026-10-12-resolve-ipv4-vs-vps-egress.md)）**：

| 域名 | 本机 debug 日志的拨出目标 | `/cdn-cgi/trace` 看到的出口 |
|---|---|---|
| `ifconfig.me` | `outbound connection to 34.160.111.145:443` | `2001:db8::a` ← IPv6（示意） |
| `ip.sb` | `outbound connection to 172.67.75.172:443` | `2001:db8::a` ← IPv6（示意） |
| `claude.ai` | `outbound connection to 160.79.104.10:443` | `203.0.113.7`（示意） |

（**本文件不记录真实节点信息**，见铁律 7。上表两个 IPv4 是公开 DNS 解析结果、不是节点地址；
出口列的 IPv4/IPv6 已替换为 [`RFC 5737`](https://www.rfc-editor.org/rfc/rfc5737)/`RFC 3849` 文档保留地址，
真实值只存 `docs/evidence/` 且同样已脱敏。）

节点的 **A 记录与 AAAA 记录**分别等于表中「走 IPv4」与「走 IPv6」的出口 ——
**两个出口 IP 都等于节点自己的记录**，即网站看到的就是这台 VPS 本身。

⚠️ **结论必须分段说，不要写「服务端不可能再选 IPv6」**（本文件早前版本的那句话是**错的**）：

- **第一段（本地 → 服务端）**：已证实锁定 IPv4，`resolve` 生效，日志可证。
- **第二段（服务端 → 目标站）**：地址族**完全由服务端决定**，本地配置无从约束（NAT64、服务端 `sniff` 后自行重解析域名等）。
  可观测到的变化：首轮 23 个域名全走 IPv6，2 小时后只剩 2 个走 IPv6；同一域名 `anthropic.com` 连测 20 次全 IPv4。
  ⇒ 是**服务端侧的时段性行为**，不是每连接随机。
- **原因未证实**：为何服务端在某些时刻选 IPv6，未取得服务端配置/日志，属推断。
  「禁用服务端 IPv6 即可解决」是**建议**，未在真实 VPS 上验证过。

**关于用户报的 `ip.net.coffee`**：首页「分流出口 IP 汇总」表格的 `IP` 列是**真实测量**（对该站发请求、显示对方看到的出口 IP），
所以那里出现 IPv6 = 当时出口真的走了 IPv6。但 `ip.net.coffee/claude/ipv6.html` 那篇
《为什么不建议用 IPv6 访问 Claude Code》是 SEO 文案 —— 它的「关闭 IPv6 的 6 个实际好处」是通用论述，
**不对你的连接做任何检测**（页面里只有一个静态示例表头）。两者必须分开看待。

**修法**

把 `{"action": "resolve", "strategy": "ipv4_only"}` 从 `route.rules` **末尾**前移到
**紧跟 `{"protocol":"dns","action":"hijack-dns"}` 之后、`{"ip_version":6,"action":"reject"}` 之前**：

```jsonc
"rules": [
  { "action": "sniff" },
  { "protocol": "dns", "action": "hijack-dns" },
  { "action": "resolve", "strategy": "ipv4_only" },   // 必须在这里
  { "ip_version": 6, "action": "reject" },
  { "ip_is_private": true, "action": "route", "outbound": "direct" },
  // ... 其余 rule_set 规则 ...
]
```

⚠️ 两个副作用（已实测，如实告知）：

1. `{"ip_version":6,"action":"reject"}` 原本靠 `metadata.Destination.IsIPv6()` 兜一层；
   resolve 前移后 `DestinationAddresses` 非空，`rule_item_ipversion.go` 的 `Match` 只读 `metadata.IPVersion`
   **和 `Destination.IsIP()`**，不读 `DestinationAddresses` —— 域名连接的 IPv6 不再被这条 reject 拦（IPv4-only 由 resolve 保证，不靠它）。
2. 国内域名也会先走一次本地解析，`geoip-cn` 因此能按「解析出的 IP」判定，命中面反而更准。

**为什么没被拦住**

- `sing-box check` 与 `run` **都不会报任何错**；resolve 位置错只是“静默不生效”。
- L17 当时把「放在末尾只对落到 final 的流量多做一次查询」当成优点写进了文档 —— **结论写反了**，
  这是「拿源码推理代替真机 debug 日志验证」的代价。

**门禁**：`resolve_not_first`

**涉及**：`tools/audit.py`（6b 节）；`profiles/1.14/{android,desktop,ios}-lazy.json`、
`local/{android-usai,android-A-dns-ipv4only,android-B-full-ipv4}.json`

---

## L19 上游加了新功能，仓库里没有「启用 / 不启用」这个答案

**现象**

这不是一次真机事故，是流程里的一个空洞（由用户 m03708 提出“升级清单”时被指出来）：

1. 1.15 上线了 10 个新能力（sing-tun 自带栈、MASQUE、Tailcat、HTTPS 证书固定…），
   仓库里 `docs/version-matrix.json` 只有 `deprecated` / `removed` / `platform` / `semantic`
   四类 kind —— **新功能这类根本没有对应字段**。
2. 于是“要不要启用”这件事**没有任何地方会问、也没有任何地方会答**。
   实际后果是**默认全部不启用**，但这个“默认”是**隐式**的：没写进任何文档、没有理由、
   机器也不拦。下一个接手的人（或下一个 AI）只能靠猜。
3. 危险的不是“不启用”，而是**不启用的理由是“没注意到”**。例如 sing-tun 自带栈删除
   `stack` 字段：1.15/1.16 上删不删都能跑，拖到 **1.17.0 仍保留 `stack` 就是 FATAL** ——
   如果没人把“必须在 1.17 前删掉”写下来，这就是一颗定时炸弹。

**根因**

- `docs/version-matrix.json` 的 `_schema.kind` 白名单只有四类，**没有“新功能”一类**；
- `tools/audit.py` 的 `audit_matrix()` 只对四种 kind 分派（`deprecated`/`removed` 归一路、
  `platform` 一路、`semantic` 一路），**没有任何分支处理“新功能未被决策”**；
- `tools/upgrade-check.py` 的 4 节报告全部围绕**废弃字段**（版本比对 / 文档 diff / 矩阵对账 /
  移除风险评估），**从不解析 changelog 的新功能条目**。

即：整套工具链只回答“**旧写法什么时候死**”，不回答“**新能力要不要用**”。

**为什么没被拦住**

`sing-box check` 对“少写一个可选字段”天然静默（不写就是默认关），所以“漏决策”在
语法层、启动层都不会留下任何痕迹。这是**纯流程漏洞**，只能靠台账 + 门禁兜。

**修法（三条）**

1. 矩阵里新增 `kind: "new"`，每条必须写全：

```json
{
  "id": "new_xxx",
  "kind": "new",
  "since": "1.15.0",
  "title": "中文说明",
  "path": "字段路径（可检测时才有）",
  "expect": "present | absent",
  "adopt": "yes | no | must",
  "reason": "为什么这么决策",
  "decide_by": "必须做完决策的版本（可选）",
  "keywords": ["用于与 changelog 做覆盖比对的小写子串"]
}
```

   `adopt` 三个值的含义：`yes`=启用、`no`=明确不启用、`must`=必须跟随（旧写法被取代，
   通常配套一条 `removed` 条目）。
2. 门禁 `audit_new_features()`：
   - `adopt` 缺失/非法、`reason` 为空 → ERROR；
   - 有 `path` 但 `expect` 缺失/非法 → ERROR；`adopt=no` 却写 `expect=present` → ERROR（自相矛盾）；
   - `decide_by` 已到而仍未决策 → ERROR（**不能靠“忘了”默认不启用**）。
3. 配置层门禁（`audit_matrix` 的 `kind == "new"` 分支）反向验证：
   `expect=absent` 而配置里**出现了**该字段 → ERROR；`expect=present` 而配置里**没有** → ERROR。

**门禁**：`new_feature_without_adoption`, `new_feature_expect_invalid`, `new_feature_decision_overdue`

**涉及**：`docs/version-matrix.json`（新增 10 条 `kind=new`）、`tools/audit.py`
（`ADOPT_VALUES` / `NEW_WITH_PATH_EXPECT` / `audit_new_features()` / `main()` 单独调用一次）、
`docs/DECISIONS.md`（人读的决策记录）、`docs/VERSION-MATRIX.md` 第二节

---

## L20 上游新增的功能条目进了 changelog，但没人看

**现象**

`tools/upgrade-check.py` 的巡检报告只有四节（版本比对 / 文档 diff / 矩阵对账 / 升级风险），
**全部围绕“存量字段的命运”**。上游 changelog 里明明写着“Add MASQUE client and server support”
这类新能力，报告里一个字都不提。

后果：升级时只会处理“要删什么”，永远不会被提醒“上游多了什么、要不要用”——
即“漏决策”这件事**连发现渠道都没有**。

**根因**

- `upgrade-check.py` 的 `TRACKED_DOCS` 确实包含 `docs/changelog.md`（会下载、会 diff），
  但**全文没有任何解析函数** —— diff 完之后 changelog 的内容就被丢掉了。
- 更细节的一个坑：changelog 里的脚注定义体（`**1**:` 这种行）以 `*` 开头，
  会被“收集 `*` 开头的行”的逻辑当成功能条目。第一版解析器因此把 `1**:`、`2**:`、`3**:`
  当成了 3 个新功能，报出“3 条未覆盖”的假错。根因是 `lstrip("*")` 先把前导 `*` 去掉了，
  噪音正则要匹配的 `\*\*\d+\*\*\s*:` 再也匹配不上 —— 必须补一条 `\d+\*\*\s*:` 兜住变形后的形态。

**为什么没被拦住**

报告本身“看起来是完整的”（有 4 个章节、有结论、退出码也有），人不会怀疑它漏了一整类信息。
**报告缺一类内容，比报告报错更难发现。**

**修法**

1. `tools/audit.py` 新增 `_changelog_features(floor_version)`：从 `docs/upstream-changelog.md`
   抽「版本 ≥ 锁定版本」的功能条目。
   **故意包含 alpha/beta/rc 段**（版本号归一化：`1.15.0-alpha.7` → `1.15.0`）——
   这是提前看到未来新功能的唯一途径；正式版发布时条目会再出现一次，按归一化文本去重。
2. 用每条 `kind=new` 的 `keywords` 做覆盖比对：上游有、矩阵没有 → ERROR `new_feature_uncovered`；
   全覆盖 → INFO `new_feature_covered`（**故意是 INFO 不是 WARN** —— 它是“体检通过”的凭证，
   做成 WARN 会让每次自检都不干净，反而让人麻木）。
3. 把同一套逻辑搬进 `upgrade-check.py` 变成报告**第 5 节「新功能清点」**：
   列出所有 `adopt` 决策表 + 还没做决策的上游功能，并计入 `problems`（报告退出码 1）。

**门禁**：`new_feature_uncovered`, `new_feature_covered`

**涉及**：`tools/audit.py`（`_changelog_features()` / `_CHANGELOG_NOISE`）、
`tools/upgrade-check.py`（第 5 节）、`docs/upstream-changelog.md`

---

## L21 决策只有结论、没有理由，半年后没人敢动

**现象**

矩阵里为 10 条新功能写上了 `adopt: "no"` 与一行 `reason`。但那一行 `reason` 塞不下背景、
备选方案、代价权衡。半年后有人看到 `new_masque_endpoints → no`，唯一能问的就是：

- 当初是真的评估过不要，还是根本没注意到？
- 现在想用了，要改动哪些地方？
- 当时是拿什么前提做的决定（那个前提现在成立吗）？

一行字回答不了任何一个问题，结果就是**没人敢改，或者盲目改了**。

**根因**

矩阵是**机读**的（门禁要解析它），所以字段必须短；一行 `reason` 是“给机器看的摘要”，
天生不适合承载“给人看的论证”（见 `docs/LESSONS.md` L19 的机制讨论）。
**如果只用矩阵，就等于只有结论、没有推理论证。**

**为什么没被拦住**

这属于“文档写得不够全”，**任何工具都不会报错**。而且矩阵看起来是完整的（每条都有 reason），
人不会怀疑它缺东西 —— 与 L20 同一种病：*报告/台账缺一类内容，比它报错更难发现。*

**修法**

新增 `docs/DECISIONS.md`（人读的决策记录，格式 `## D<n> <标题>` + 日期 / 触发 / 决策 /
矩阵 ID / 为什么 / 备选方案 / 前提风险），并加双向门禁 `audit_decisions()`：

- **方向一**（`decision_without_record`）：矩阵里每条 `kind=new` 必须在 DECISIONS.md 的某个
  D 小节里被引用，否则 ERROR —— 防止“机器有答案、人没理由”；
- **方向二**（`decision_references_unknown`）：DECISIONS.md 的 D 小节里引用的
  `` `new_xxx` `` 必须真实存在于矩阵，否则 ERROR —— 防止“矩阵改过、文档变谎言”；
- 文件不存在直接 ERROR（`decisions_missing`）；两边一致时报 INFO `decisions_ok`。

⚠️ 实现坑（已踩）：方向二最初扫的是**整个文件**，于是文首「记录格式」模板里的示例 id
`` `new_xxx` `` 被当成真实引用，一上线就报假错。**必须只扫 `## D<n>` 小节的正文。**

**门禁**：`decisions_missing`, `decision_without_record`, `decision_references_unknown`, `decisions_ok`

**涉及**：`docs/DECISIONS.md`（新建）、`tools/audit.py`（`audit_decisions()` / `DECISION_HEAD_RE`）

---

## L22 改了流程文档，忘记把新流程写进入口文件 —— 规则存不存在取决于读到哪一份

**现象**

升级流程从“只管废弃字段”扩到“新功能也必须做采纳决策”后，涉及 6 个文件：
`docs/DECISIONS.md`（新）、`docs/version-matrix.json`、`tools/audit.py`、
`tools/upgrade-check.py`、`docs/WORKFLOW.md`、`AGENTS.md`、`README.md`。

漏写其中任何一个的后果**不是报错，而是“因人而异”**：

- AI 只读 `AGENTS.md` 就开工（这是仓库自己规定的入口）⇒ 它会做新功能决策吗？没人知道。
- 人类只读 `README.md` ⇒ 他会看到“铁律 14 条”，其中**一个字都没提新功能**。
- 两个人都**不会**有任何“好像少了什么”的感觉 —— 文档里少一节，读起来依然通顺。

**根因**

`docs/WORKFLOW.md` 是详版的流程，`AGENTS.md` 是 AI 入口，`README.md` 是给人看的摘要 ——
三份内容**部分重叠但由人手维护**。新增流程时很容易只改其中一份（尤其是只改最“详细”的那份）。

**为什么没被拦住**

没有任何工具会检查“文档之间的内容一致”。`audit.py` 只校验配置与台账，不校验**文档内部自洽**。

**修法**

升级流程（流程 B）在四个地方必须同步到一致：

| 文件 | 必须含 |
|---|---|
| `AGENTS.md` | 任务 B 的步骤里出现 `upgrade-check.py` 第 5 节 / `DECISIONS.md`；铁律表里有一条“新功能必须显式决策” |
| `README.md` | 铁律摘要里有一条“新功能必须显式决策”；「体检命令」里出现新门禁 |
| `docs/WORKFLOW.md` | 流程 B 里插入「新功能清点 → 逐条讨论 → 写进 DECISIONS.md」步骤 |
| `docs/DECISIONS.md` | 每条新功能有对应 D 条目（由 L21 的门禁强制） |

另：由 `audit_lessons()` 的双向校验兜住“**新门禁没人知道**”这一半
（每个新 code 必须在 `docs/*.md` / `AGENTS.md` / `README.md` 出现过）；
但“**流程步骤漏写**”这一半**只能靠人**，因此本条目存在的意义就是提醒下一个改流程的人去对四个地方。

**门禁**：无（文档内部一致性无法机器校验）

**涉及**：`AGENTS.md`、`README.md`、`docs/WORKFLOW.md`、`docs/DECISIONS.md`

---

## L23 防泄漏：证据文档写了“实测”，把用户服务器的真实地址一起公开了

**现象**：为了解释「IPv6 出口从哪来」，我在 `docs/evidence/` 新建了一份证据文档，
写入了节点域名与它的两条 DNS 记录（A 与 AAAA），并推到了公开仓库。
**所有门禁都通过了** —— 包括专管泄漏的 `placeholder_server`。

**根因**：当时唯一防泄漏的门禁是 `placeholder_server`，它只做一件事：

```python
# tools/audit.py:424-437（修改前）
if rel.parts and rel.parts[0] == "profiles":          # ← 只管 profiles/ 目录
    for i, ob in enumerate(cfg.get("outbounds", [])):  # ← 且只看 JSON 的 server 字段
        ...
        if not srv.endswith(PLACEHOLDER_DOMAINS):
            rep.error("placeholder_server", ...)
```

即：**它审的是“字段”，范围是 `profiles/`**。而这次泄漏出现在 `docs/*.md` 的**散文里**，
既不是 JSON 也不在 `profiles/`。所有门禁都是“按字段”审的 ⇒ 看不见。

**为什么没被拦住**：
1. 铁律 7 的措辞是「仓库里不放**真实节点**」，而**节点的 IP 不在任何配置字段里**（只在证据叙述里）——
   字面上不归任何门禁管。
2. 修改前的 force-push 只重置分支指针，**不会立刻删除旧对象**；旧 commit 仍可按 SHA 直取。
3. 当时仍存在思路盲区：“这是实测数据、是证据、不写就不严谨” ——
   但**证据的严谨性不需要真实地址**（只需“两者相等”这个关系，见 `docs/evidence/` 里的 🔒 说明）。

**修法**：
- 内容：节点域名 → `<节点域名>`，节点出口 IP → RFC 5737/3849 文档地址（`203.0.113.7` / `2001:db8::a`）。
  **目标站 IP（如 `160.79.104.10`）与公共 DNS 保留** —— 它们不是我们的基础设施，不构成泄漏。
- 门禁（新建 `audit_redaction()`）：按 `git ls-files` 扫**全部被跟踪文件**，
  招出任何 **2000::/3 或非私有段**的公网 IP；豁免 RFC 私有/回环/文档专用/组播段
  与 `PUBLIC_IP_WHITELIST`（人工审阅过的公共 DNS 与目标站地址）。`local/` 跳过。
- 实例正则尾部需排除 `/`，否则 CIDR（`2000::/3`）会被当作地址误报；需把 `_IP6_SCAN_NET` 设成
  `2000::/3`（真实节点地址只会落在这里），否则上游文档里的 IETF 保留段示例（如 `8000::/1`）会误报。

**同类教训**：**门禁的作用域必须与铁律的作用域一致**。铁律 7 说的是“仓库”，
门禁却只查了 `profiles/` 的一个字段 —— 这就是缺口。加门禁时要回头对一遍：
这条铁律到底覆盖哪些文件、哪些载体（字段？散文？提交信息？），漏一个就是一个缺口。

**门禁**：`sensitive_ip_in_repo`、`redaction_clean`

---

## L24 内容脱敏了，指向它的「指针」还在 —— SHA 也是泄漏物

**现象**：节点地址脱敏（L23）之后，我在三处说明里写了事故那个 commit 的 **SHA 前缀**，
用来指代“就是那一次”：`AGENTS.md` 的「需用户同意的六个动作」表里一句“靠 force-push 补的”、
`docs/DECISIONS.md` 的 D9 触发栏、`docs/LESSONS.md` 的 L23 标题下。三处都已推到公开仓库。

**根因（实测，非推断）**：force-push 只把**分支指针**挪走，GitHub 上的旧对象仍可按 SHA 直取：

```bash
$ gh api repos/<owner>/<repo>/commits/<旧 SHA> --jq '.commit.committer.date'   # HTTP 200，返回 2026-10-12T08:29:54Z
$ curl -s https://github.com/<owner>/<repo>/commit/<旧 SHA>.patch | grep -c '<泄漏域名>'   # 3
```

同时还查了两件事：**全新 clone 里已经没有这个对象**（`git cat-file -e` 失败、`count-objects` 为 0），
但这不等于它不可取 —— REST API 与网页 commit 页是**另一条路径**，两条都实测 HTTP 200。

⇒ **脱敏文件内容只能挡住“直接搜内容”**；一旦有人在仓库里写下那个 SHA，
就等于给搜索者留了一把钥匙：搜到 SHA → 直接 `curl` 到原文，前面的脱敏全部作废。
**SHA 与它所指向的内容，泄漏等级相同。**

**为什么没被拦住**：
1. 建 `audit_redaction()` 时的口径是“扫**内容**”，压根没想到 commit message 与被跟踪的 **MD 文件**，
   也属于“会被写进仓库的文本”，且同样推不回来。
2. 心理上把 SHA 当成“一个编号”而不是“一条 URL” —— 但在这个场景下它就是 URL。

**修法**：分两步 —— 第二步推翻了我自己的第一步。
- 内容：三处 SHA 全部换成“日期 + 背景”（如「2026-10-12 的节点信息泄漏事故」）。
  这正是**信息足够、指针不必要**的又一个例子 —— 与 L23 里“只需两者相等这个关系”同一条思路。
- 门禁（第一步，错的）：给 `audit_redaction()` 加一份“已泄漏 SHA”的**黑名单常量**，
  并把扫查范围从「被跟踪文件」扩大到全部 commit message。
  写完立刻发现它自相矛盾：**要拦住某个 SHA，就必须把那个 SHA 明文写进仓库** ——
  而 SHA 恰恰是能在 GitHub 上直取旧对象的指针。黑名单自己成了新的一把钥匙，
  而且是**递归**的：拦住“写 SHA”这件事的清单，自己就得写 SHA。
- 门禁（第二步，改对的）：改用**不点名任何 commit 的单调时间切点** ——
  `LEAK_SCAN_START_DATE = "2026-10-12 20:30:00"`（`tools/audit.py`），
  commit message 只扫这个时刻之后的（`git log --since=...`），被跟踪文件仍全量扫。
  语义是「本门禁从此生效：之后的历史必须干净」，不需要知道之前漏过什么，因此无需任何名单。

**同类教训**：
1. 脱敏要分两层看 —— **内容层（真实地址）与指针层（指向内容的版本号/URL/SHA）**。
   只洗内容不洗指针，等于把钥匙留在锁旁边。约定：**写事故一律用「日期 + 背景」，不写 SHA**。
2. **给泄漏做黑名单是自败的**：黑名单要求你写出要拦的东西，而“要拦的东西”本身就是泄漏物。
   凡遇到「禁止出现 X」类门禁，先问一句：**判定 X 是否必须存下 X？**
   必须存 ⇒ 换成不依赖 X 判定的机制（时间切点、事后评审、只存哈希前缀且不可反查）。

**门禁**：`redaction_clean`（扫查范围扩到 commit message；黑名单设计已废弃）

**涉及**：`tools/audit.py`、`AGENTS.md`、`docs/DECISIONS.md`

---

## 附：怎么加一条新教训

1. 在 `tools/audit.py` 里把能拦住这次事故的**门禁 code** 实现出来（不能只写文档）。
2. 在本文件追加 `## L<n> <标题>` 条目，内容必须含 **现象 / 根因（带源码路径）/ 为什么没被拦住 / 修法 / 门禁**。
3. 在 `**门禁**：` 行里写上第 1 步的 code（反引号包裹）。
4. `python tools/audit.py` 应当能过 —— `audit_lessons()` 会替你检查两边对得上。
5. 跑负向测试：把配置改坏，确认新门禁真能报 ERROR。
