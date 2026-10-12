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

## 附：怎么加一条新教训

1. 在 `tools/audit.py` 里把能拦住这次事故的**门禁 code** 实现出来（不能只写文档）。
2. 在本文件追加 `## L<n> <标题>` 条目，内容必须含 **现象 / 根因（带源码路径）/ 为什么没被拦住 / 修法 / 门禁**。
3. 在 `**门禁**：` 行里写上第 1 步的 code（反引号包裹）。
4. `python tools/audit.py` 应当能过 —— `audit_lessons()` 会替你检查两边对得上。
5. 跑负向测试：把配置改坏，确认新门禁真能报 ERROR。
