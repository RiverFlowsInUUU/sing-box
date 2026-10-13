# 事故台账（LESSONS）

> **这份文件是给 AI 读的。**每次生成/修改配置之前先扫一遍本文件，逐条对照自检。
>
> **每条教训必须有五要素**：`**现象**` → `**根因**`（含源码位置）→ `**为什么没被拦住**`
> → `**修法**` → `**门禁**`。缺哪一段，`tools/audit.py` 的 `audit_lessons()` 就报
> ERROR `lesson_missing_element` —— 头部这句话以前只是声明、没人验，L27 就是为此而加。
> （机器只能校「这一段在不在」，校不了「写得对不对」。）
>
> **格式是机读的**：`## L<n> <标题>` 开头（二级标题），`**门禁**：` 行列出该教训对应的
> `audit.py` 门禁 code（多个用 `,` 分隔，没有就写 `无`）。
> `audit_lessons()` 会校验这些 code 在代码里真实存在 —— 防止「文档写了门禁、代码里没实现」。
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

我给用户的上一版配置出错后，声称“实测能上网、curl 返回 204 正常”。
实际本机有 **OpenClash 网关**在劫持 DNS。

**根因**

本机不是一台干净机器：另有一个带 TUN + fakeip 的进程（OpenCLash 网关）在系统层劫持 DNS，
而 `sing-box check` 与 `audit.py --run` 都只验“进程能不能起来”，完全绕过网络路径。
所以我跑出来的“连得上/连不上”与 sing-box 配置**没有因果关系**，却被我当成了配置的验证结论。

**证据（本机实测）**

一份**完全不含 fakeip 配置**的最小配置（只有 udp `223.5.5.5` + mixed 入站 + direct 出站），
查 `testingcf.jsdelivr.net` 时 `223.5.5.5` 仍然返回 `198.18.0.70`（fakeip 网段）——
证明本机另有带 TUN + fakeip 的进程在劫持 DNS。**这个环境里跑出来的任何连通性结论都是假的。**

**为什么没被拦住**

“实测”这两个字被我当成了证据等级最高的一类，却没有先问一句“这台机器有资格做这个实验吗”。
门禁也拦不住：这是**方法论错误**，不是配置字段错误，`tools/audit.py` 只看 JSON。

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

生成流程里**没有“差异比对”这一步**。我按自己的模板从头写配置，
没有把“用户原始配置”当作基线逐键对比，于是丢字段、加字段都不自知。
更根本地说：LLM 重写 JSON 时，“我记得模板里有这一项”和“用户配置里有这一项”是两件不同的事，
而我把前者当成了后者。

**为什么没被拦住**

所有门禁都是“**在配置里找不该有的东西**”（废弃字段、裸 direct、缺 adi……），
没有一条是“**拿两份配置做差**”。丢字段属于“少了东西”，静态检查天然看不见 ——
而 `auto_detect_interface` 缺失恰好会让配置**看起来完全合法**（L2 的“能启动但没网”）。

**修法（写流程，不靠自觉）**

生成或修改配置前/后**必做**逐键比对，已固化成仓库工具（跨平台，Windows 上也能跑）：

```bash
python tools/diff_config.py 用户原始配置.json 我改完的配置.json
```

输出三段：`只在原始配置里（可能被我删了）` / `只在生成配置里（可能是我加的）` /
`两边都有但值变了`。**每一个差异都必须能说出为什么**；说不出原因的，就按原始配置保留。

**每一个差异都必须能说出为什么**

这不是“走个流程”，而是把“我改了什么”从记忆变成事实。说不出原因 = 不该改。

**门禁**：无（流程约束，由 `AGENTS.md` 铁律 0 与第 0.1 节约束；`tools/diff_config.py` 是执行工具）

---

## L5 Jinx 广告规则集的顺序铁律
**现象**

广告拦截一开始没生效，或拦了不该拦的（把国内站点也拦了）。
用户真机表现是“广告还在”或“某个正常站点打不开”。

**根因**

广告规则集与 `geosite-cn` 的匹配是**先命中者胜**，而国内广告域名**多半也属于 `geosite-cn`**。
把 `geosite-cn → direct` 放在广告规则之前，国内广告域名会先被直放，广告规则再无机会执行；
另一侧，秋风规则集（`awanue-ads`）会拦掉 Jinx 白名单里的 8 个域，
所以它必须排在 Jinx 之后 —— **两边顺序都是唯一解**。

**为什么没被拦住**

“顺序错了等于没加”这件事在配置里看不出来：JSON 数组顺序是合法的，字段名也全对，
`sing-box check` 与 `audit.py` 的结构检查一律通过。这是**语义顺序**问题，
只有把规则集的域名清单拿出来逐条模拟匹配才看得见。

**修法（顺序铁律）**

顺序固定，不得调换：

```
jinx-direct → direct          （白名单先放行，否则会被后面的秋风误拦）
jinx-ads    → AD
awanue-ads  → AD
geosite-cn  → direct          （必须排在最后一个，否则前面的广告规则全部失效）
```

前三组必须紧邻且整体排在 `geosite-cn` 之前。

**门禁**：`jinx_incomplete`, `jinx_order`, `jinx_url`, `jinx_format`, `jinx_ads_target`

---

## L7 仓库里出现真实节点
**现象/风险**

`profiles/` 是公开仓库的一部分。一旦把带真实 server / 密码 / uuid 的节点写进去并提交，凭据就永久泄露到 git 历史。

**根因**

“真实节点”这个词被理解得太窄：我最初只盯 `profiles/` 的 `server` 字段，
而**任何被跟踪文件里的散文同样是公开的**。范围没定清楚，所以防线只画在一处。
（这条根因在 L23 被完整验证：脱敏了 `profiles/`，却在 `docs/` 的证据文档里写了节点域名与它的 A/AAAA。）

**为什么没被拦住**

当时的唯一门禁 `placeholder_server` 只扫 `profiles/*.json` 的 `server` 字段；
`docs/` 里 800 行的 markdown **没有任何工具在看**。
“铁律写了”与“机器能拦”之间隔着一条 100% 的缝。

**修法（铁律 7）**

- `profiles/` 下 `outbounds[].server` 只能是占位域名（`.example.com` 等）。
- 含真实凭据的配置一律放仓库外的 `local/`（已在 `.gitignore`）。
- 给用户的成品放仓库外（如桌面）。
- **范围是“整个被跟踪仓库”**，不只 `profiles/`：`docs/`、`AGENTS.md`、commit message 都算。

**门禁**：`placeholder_server`, `sensitive_ip_in_repo`, `redaction_clean`

---

## L8 平台能力差异
**现象/风险**

iOS / Android 客户端未实现的字段写了不一定报错，但真机上行为异常或完全不生效。

**根因**

sing-box 的 JSON schema 是**全平台共用**的一份（`docs/schema.json`），
字段的合法性检查在**反序列化**这一层，而“这个平台的内核有没有实现它”是**另一层**。
于是 `check` 认为合法、内核也接受，但图形客户端根本不读这个字段。
（官方 `docs/clients/android/features.md`、`docs/clients/apple/features.md` 用
`:material-close: Not implemented` 标注，是唯一的权威来源。）

**为什么没被拦住**

`sing-box check` 只反序列化、不做任何初始化（铁律 4），平台能力更不在它的检查范围里；
`audit.py` 早期也没有“平台”维度 —— 每份 profile 都当成通用配置审。

**修法**

- 平台差异统一记录在 `docs/PLATFORM-MATRIX.md`，作为唯一真源。
- `audit.py` 增加 `audit_platform_caps()`，按 `--platform` 分别校验。
- 三个已确认的坑固定下来（见下）。

**已确认的坑**

- `inbounds[type=tun].strict_route`：Android / Apple 未实现（桌面可用）
- `route.override_android_vpn`：必须同时开 `auto_detect_interface` 才有意义
- `inbounds[type=tun].stack` 为 `system` / `mixed`：与 Apple 客户端的
  「Include All Networks」互斥（sing-tun 返回 `ErrIncludeAllNetworks`）—— 但 `stack`
  在 1.15.0 废弃、1.17.0 移除，届时这个取舍自动消失，所以只是 WARN
- `http_clients[].engine = "apple"`：Apple 独占（NSURLSession），别的平台内核起不来

依据 `docs/PLATFORM-MATRIX.md` + 官方 `docs/clients/*/features.md`。

**已废弃的一项**：早期还写了一条「`outbound.domain_resolver` 指向 `local` 类型 DNS：Android
上不总能工作」，对应的门禁按 `domain_resolver == "dns-local"` 匹配 —— 而本仓库的 DNS 服务器
tag 一直是 `dns-bootstrap` / `dns-cn` / `dns-proxy`，**该门禁永远不可能触发**（死检查，只在
`archive/1.14/` 的旧文件里出现过 `dns-local`），已删除。教训：门禁若按某个字面量匹配，
必须同时确认该字面量在当前配置里真的会用到（见 L25 的同类问题）。

**门禁**：`platform_strict_route`, `android_override_vpn_no_adi`,
`apple_include_all_networks_stack`, `apple_engine_on_universal`

---

## L9 出站骨架与引用完整性
**现象/风险**

分流组骨架被改错（Proxy 不是 urltest、AI 被改成 selector、AD 被塞代理节点），
组里嵌组（`AI.outbounds` 里放 `Proxy`，两个 urltest 串联测速），
或引用了不存在的 tag —— 这类错误 `check` 不会报，运行时才炸或静默失效。

**根因**

早期把 `AI` 实现成 `selector(outbounds=[Proxy, ...], default: Proxy)`，
以为“AI 组指向 Proxy 就等于默认出口，省事”。但 `selector` 只是**静态指向**，
它不会自己优选；结果 `AI` 与 `Proxy` 完全同源、形同虚设。
第二个错误更隐蔽：`urltest` 套 `urltest` 会**串联两次测速** ——
外层只拿到内层已选中的那一个节点，内层的周期性测速与外层的测速互相拖累。

**背景（m02132 用户要求）**

用户原话：「ai 分流组不要 proxy 作为子节点，直接就是 urltest +台湾节点」。
原因：`AI` 若只是指向 `Proxy` 的 selector，它与 `Proxy` 完全同源，AI 组形同虚设；
而 `urltest` 套 `urltest` 会串联两次测速（外层只拿到内层已选中的那一个节点）。

**为什么没被拦住**

这两类错误都不会让 `check` 失败：`selector` 引用一个存在的 tag 是合法的，
`urltest` 的成员是另一个 `urltest` 也是合法的。它们**语义**错了，**语法**全对。
`audit.py` 当时只有结构检查，没有“组间关系”检查。

**修法**

骨架固定在 `templates/groups.json`；每个 profile 的出站必须与它一致，只往 `outbounds` 数组里加节点 tag。
- `Proxy` 与 `AI` **都是 urltest**，各自在组内节点间独立优选；`AI` 只放用户指定给 AI 的节点（如全部台湾节点）。
- `Proxy` / `AI` / `AD` 的 `outbounds` 里**只允许出现真实节点 tag**，不得引用其它组。
- 骨架模板 `templates/groups.json` 里 `Proxy` / `AI` 的 `outbounds` 允许为空（占位），
  自行生成的 profile 里为空则报 WARN `empty_group_skeleton`。
- `AD` 组的 `outbounds` **只允许 `block`**（m07194 起删掉 `direct`），`default` 必须逐字是 `"block"`。
- 三个组的 tag 必须逐字是 `🚀 Proxy` / `🤖 AI` / `🚫 AD`（emoji + **一个 ASCII 空格** + 名字）。
  它们是 `route.final`、`route.rules[].outbound`、DNS 规则与规则集的引用目标，
  因此写错一个字符就等价于「tag 找不到」（`check` 不报，运行时才报 `outbound not found`
  或静默落到 `final`）；同时它也是客户端策略组列表里给用户看的显示名。

**门禁**：`dup_tag`, `empty_group`, `empty_group_skeleton`, `urltest_no_url`, `final_missing`, `dangling_ref`, `group_wrong_type`, `group_nesting`, `group_tag_incomplete`, `rule_outbound_missing`, `rule_ruleset_missing`, `ad_group_polluted`, `ad_group_default_not_block`, `template_missing`, `template_json`, `template_group_missing`, `template_legacy_auto`, `template_group_tag_incomplete`, `template_proxy_not_urltest`, `template_proxy_no_url`, `template_ai_not_urltest`, `template_ai_no_url`, `template_ad_polluted`, `template_ad_default_not_block`

---

## L10 规则集 URL 与下载方式
**现象/风险**

- 用 `raw.githubusercontent.com`：国内经常连不上，规则集下载失败 → 启动 FATAL
- 不写 `http_client` / 写已废弃的 `download_detour`：1.14 起前者是唯一正确写法
- URL 不以 `.srs` / `.json` 结尾又不写 `format`：无法推断格式

**根因**

规则集是**启动时联网下载**的资源，所以它的可用性链路比配置本身长得多：
① URL 的 CDN 在国内可达性 ② 下载走哪个出站 ③ 文件格式能否推断。
三者任一断掉都是**启动 FATAL**（`initialize rule-set[...]`），而不是“功能降级”。
`raw.githubusercontent.com` 在国内不稳是已知事实；`download_detour` 在 1.14 被
`http_clients` + `route.default_http_client` 取代且两者同时出现会直接报冲突。

**为什么没被拦住**

下载链路的正确性**只在真启动时才验证** —— 而 `sing-box check` 不做任何初始化（铁律 4），
规则集根本不会去下载。所以“check 全绿”与“能不能启动”之间差着整条网络链路（L1）。

**修法**

- 统一用 CDN 镜像：`https://testingcf.jsdelivr.net/gh/<repo>@<ref>/...srs`。
- 下载走专用非空 direct 出站（`direct-download`，带 `domain_resolver`），
  经 `http_clients: [{tag: ruleset-dl, detour: direct-download}]` + `route.default_http_client` 引用。
- 需要时显式写 `format: "binary"` / `"source"`。

**门禁**：`ruleset_url`, `ruleset_url_raw`, `ruleset_http_client`, `ruleset_download_detour`, `ruleset_format`

---

## L11 缓存文件路径
**现象/风险**

`experimental.cache_file.path` 指向的**父目录不存在**时，`CacheFile.start()` 直接 ENOENT，**启动失败**。
sing-box 的 cachefile 包**不会创建父目录**（全包无 `Mkdir`/`MkdirAll`），`os.O_CREATE` 只能建文件。
含 `..` 的相对路径还依赖工作目录，跨平台不可靠。

**根因**

代码里打开 cache 文件只用了 `os.O_CREATE`，而它的语义是“**文件**不存在就创建”，
**不包含“创建父目录”**。`../cache/cache.db` 这种写法把存在性押在“上级目录恰好存在”上 ——
在仓库里恰好成立，在 Android 客户端的私有工作目录里不成立。
用户实测：`../cache/cache.db` 报错、`../cache.db` 不报错 —— 差别只在父目录。

**为什么没被拦住**

父目录是否存在是**运行时环境**的属性，JSON 里看不出来。
静态检查能看出“路径含 `..`”和“是绝对路径”，但看不出“这个机器的这个目录在不在”。

**修法**：用工作目录内的相对文件名（`cache.db`）。

**门禁**：`cache_path_abs`, `cache_path_parent`

---

## L12 DNS 引用完整性
**现象/风险**

`dns.rules[].server` / `rule_set` / `dns.final` / `route.default_domain_resolver.server`
指向不存在的 tag 时，启动期才报错。

**根因**

sing-box 的 tag 是**字符串引用**，没有类型系统或编译期校验。
DNS 这一层引用密度最高（`dns.final` → server、`dns.rules[].server` → server、
`dns.rules[].rule_set` → rule_set、`route.default_domain_resolver.server` → server），
任意一处拼错都只在**构造 DNS 路由器**时才暴露。

**为什么没被拦住**

`sing-box check` 只反序列化 JSON，不做引用解析；`dns.servers` 里的 tag 是自由字符串，
写 `dns-cn` 还是 `dns-cnn` 在 schema 层面都合法。

**修法**

把 DNS 侧的交叉引用做成**显式清单**逐条校验（`audit_repo_rules()`），
新增一个 server / rule_set 时同步补进清单。

**门禁**：`dns_final_missing`, `dns_rule_server_missing`, `dns_rule_ruleset_missing`, `ddr_missing`

---

## L13 新旧写法并存
**现象/风险**

`http_clients` 与已废弃的 `download_detour` 同时出现 → 直接 `FATAL http_client is conflict with deprecated download_detour field`。

**根因**

1.14 把规则集下载方式从 `download_detour`（字符串）迁移到
`http_clients`（出站定义）+ `route.default_http_client`（引用）。
迁移期两种写法**语义重叠但字段并存**，内核选择直接 FATAL 而不是“以新为准”，
所以“新旧都留着更保险”的开发直觉在这里恰恰是致命的。

**为什么没被拦住**

两条规则各自检查“该字段是否合法/是否该有”，**没有一条检查“两者是否同时存在”**。
这是**互斥字段**问题，只有把两个字段放在一起看才发现。

**修法**：迁移立刻删旧字段，不留“保守的冗余”。

**门禁**：`http_client_conflict`

---

## L14 反向：门禁自身出错（`UnboundLocalError`）
**现象**

`tools/audit.py` 曾经把 `route = cfg.get("route", {})` 写在首次用到它**之后**，
导致 `UnboundLocalError`，整个门禁直接崩掉——**门禁崩了比没有门禁更危险**（会让人以为检查过了）。

**根因**

门禁是一堆顺序执行的检查函数，**局部变量绑定位置**与**使用位置**的正确性
只靠人眼维护；重构时把 `cfg.get()` 往上挪几行就崩。
而崩的后果是：`audit.py` 抛异常 → 什么都不输出 → 使用者以为“没输出就是没问题”。

**为什么没被拦住**

**“检查器自己有没有坏”这件事，没有任何检查器在看**。
CI 里 `python tools/audit.py --run` 非零退出确实会红，但本机跑崩了、又没细看输出时，
人会误以为门禁通过（L25 把这条扩展成了 `audit_tools()`）。

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

**根因**

“教训台账”与“检查代码”是两份**独立维护**的文本，
没有任何机制阻止它们漂移：写文档时顺手写一个不存在的 code、
加代码时忘了回来记一条，两边都各自看起来很正常。
**漂移的方向恰好是“让人更放心”的方向** —— 所以没人会主动发现。

**为什么没被拦住**

这是**元层面**的检查：需要读 `audit.py` 的源码（而不只是跑它）+ 读 `LESSONS.md` 的正文。
普通的“跑一遍门禁”做不到，因为漂移的正好是门禁清单本身。

**修法（双向可追溯）**

`tools/audit.py` 的 `audit_lessons()` 对此做机器校验（并已接入 `main()`，不经 `--lessons`）：

1. **方向一（本文件 → 代码）**：本文件每条 `**门禁**：` 行里以反引号包裹的 code
   （形如 `xxx_yyy`），必须在 `tools/audit.py` 源码里以 `rep.error("xxx_yyy"` 或
   `rep.warn("xxx_yyy"` 真实出现，否则报 ERROR `lessons_missing_gate`。
2. **方向二（代码 → 本文件）**：`tools/audit.py` 里每个非框架 code 都必须在
   某个 `docs/*.md` 里出现过，或在 `tools/audit.py` 内的已知白名单里，
   否则报 ERROR `gate_without_lesson`。

**白名单（框架性/非配置类，不要求有教训条目）**：
`json`, `no_singbox`, `run_skipped`, `singbox_check`, `singbox_run`, `singbox_run_tun`, `singbox_timeout`, `skip_check_template`

**门禁**：`lessons_missing_gate`, `gate_without_lesson`, `lessons_missing`, `lesson_missing_gate_line`

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
- 本机实测（`local/` 里自建的 mixed 入站 + AD selector(default block) 最小配置）：
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
2. 当时的 force-push 只重置分支指针，**不会立刻删除旧对象**；旧 commit 仍可按 SHA 直取。
   （2026-10-12 晚删库重建后才真正消失 —— 但“先把内容洗掉、再考虑重建”这条顺序不能省，
   而且重建是最后手段，不能当成常规修法。）
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

**根因（实测，非推断）**：force-push 只把**分支指针**挪走 —— **当时**GitHub 上的旧对象仍可按 SHA 直取：

```bash
$ gh api repos/<owner>/<repo>/commits/<旧 SHA> --jq '.commit.committer.date'   # HTTP 200，返回 2026-10-12T08:29:54Z
$ curl -s https://github.com/<owner>/<repo>/commit/<旧 SHA>.patch | grep -c '<泄漏域名>'   # 3
```

同时还查了两件事：**全新 clone 里已经没有这个对象**（`git cat-file -e` 失败、`count-objects` 为 0），
但这不等于它不可取 —— REST API 与网页 commit 页是**另一条路径**，两条都实测 HTTP 200。
（**2026-10-12 晚删库重建后，这两条路径都已变 404**。本条保留的是“force-push 本身不够”这个结论，
不是“现在还能取到”—— 重建是最后手段，不能当成常规修法。）

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
  `LEAK_SCAN_START_DATE = "2026-10-12 20:00:00"`（`tools/audit.py`），
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

## L25 门禁只审配置，不审自己 —— 工具本身没人检查

**现象**：一天之内出现三次“工具自己坏了、但所有检查都 PASS”：
1. `tools/audit.py` 的 `audit_new_features()` 里写成 `return    uncovered = []`（两行粘成一行）
   ⇒ `SyntaxError: invalid syntax`，**整个门禁跑不起来**，是在本机手跑时才发现的。
2. `tools/gen-docs.py` 的 `pinned` 在赋值前被引用 ⇒ `UnboundLocalError: cannot access local variable 'pinned'`。
3. 别人为去硬编码把 `tools/audit.py` 的 `find_singbox()` 本机兜底路径删了（只留 `ROOT/bin/` 与 `PATH`）；
   本机没有 `bin/`、`PATH` 里也没有 sing-box ⇒ `--run` **静默降级**为 `[i] 未指定 sing-box 可执行文件，已跳过 sing-box check`，
   整体照样 PASS。而「真启动一次、只筛 FATAL」恰恰是我们唯一能拦住
   “写出一个语法合法但跑不起来的配置” 的那层（`sing-box check` 只反序列化，见 L1）。

**根因**：所有门禁都是“拿**配置文件**当输入”写的。**工具自己不是检查对象**。
于是存在一个死角：门禁坏了 → 门禁输出看起来正常 → 没人发现它已经没在工作。
这比“门禁报错”危险得多，因为它是**静默**的。

**为什么没被拦住**：
- `audit.py` 的定位一直是“审配置”，压根没把自己列进目标（`targets` 里只有 `profiles/**.json` 与 `templates/groups.json`）。
- 第 3 条尤其隐蔽：它**不是报错**，是**跳过**，而跳过用的是 `rep.info`/`rep.warn` —— 一个 INFO 文本夹在一屏输出里，没人会去抓它。
- 反过来看 CI：CI 里 `SINGBOX_BIN=/usr/local/bin/sing-box` 是设好的，所以 **CI 真的跑了 run 验证**，
  本机与 CI 行为不一致，进一步掩盖了本机的问题。

**修法**：新增 `audit_tools()`（`tools/audit.py`），在 `main()` 里与其它台账同级挂上：
- 逐个 `compile()` `tools/*.py` 
  → 新 code **`tool_syntax_error`**（类型 1、2 这类错误从此跑不掉：注意 `compile()` 只查语法，
  而语法错恰恰是实际发生过的形态；`UnboundLocalError` 属运行期，靠第 2 类不变量测试兕）。
- 对关键工具做**不变量测试**（不是“跑一遍”，是断言它算出的结果对）：
  `tools/diff_config.py` 的 `compare()` 被抽成可 import 的函数，
  用「两份相同 / 只改一个值 / 一边多一个字段」三个输入验它分别给出 0 差异 / `changed=["a"]` / `only_a`+`only_b`
  → 新 code **`tool_selftest_failed`**。
  另外断言 `DIRECT_NON_EMPTY_KEYS` 不含 `domain_strategy`（L1 就错在这里）且含 `domain_resolver`。
- 把“工具静态可发现”的检查留在 `find_singbox` 层级，**不把本机绝对路径写回仓库**
  （铁律 7：仓库不放本机信息），改为**在本机用 `SINGBOX_BIN` 环境变量**提供路径；
  `--run` 降级情况已由 `no_singbox` / `run_skipped` 两个既有 code 覆盖。

**同类教训**：一条检查链的强度 = **最弱一环**，而“检查器自身”永远是没人看的那一环。
凡新增门禁，先问：**如果它坏了，谁会知道？** 答“没人知道” ⇒ 就得给它配一条自检。

**门禁**：`tool_syntax_error`, `tool_selftest_failed`

**涉及**：`tools/audit.py`、`tools/diff_config.py`、`tools/gen-docs.py`

---

## L26 台账里写下的“风险点”，没有任何字段承载 —— 到了升级那天没人会记得

**现象**

`docs/version-matrix.json` 的 `new_tun_sing_tun_stack` 条目是 `adopt: "must"`（1.15 必须删 `stack`，
1.17 不删就 FATAL），它的 `reason` 里写着一条**唯一的风险点**：

> ★ 本仓库 tun 写的是 mtu=9000，官方对比表用 1500/4064/65535，换栈后 mtu 取值需在正式版文档确认后再定。

而三份 profile 里 `inbounds[type=tun].mtu` 全都是 `9000`、`stack` 全都是 `"system"`（实测 grep）。
也就是说：**这个风险点只存在于一段散文里**。到 1.15 真正发布时，
“删 `stack`”这件事有门禁（`expect: "absent"` 会在配置里发现残留），
但“`mtu` 要不要跟着改”没有任何机器痕迹 —— 只靠那天有人恰好读到这句 reason。

**根因**

`kind: "new"` / `kind: "deprecated"` 条目能表达的是**字段级的三种状态**
（该有 / 不该有 / 该怎么改），而“这个迁移还附带一个需要重新决策的参数”不是字段状态，
是一种**附加待办**。矩阵的 schema 里没有承载它的位置，于是它被写进了 `reason` ——
而 `reason` 是给人读的散文，门禁只校“非空”，不校“里面的待办被处理了”。
`docs/DECISIONS.md` 的 `**前提 / 风险**` 栏同理：它是一段说明，不是一个能被触发的提醒。

**为什么没被拦住**

门禁的设计前提是“**判据在配置里**”：能通过读 JSON 判断对错才写得出检查。
“mtu 该不该改”的判据**不在配置里，而在上游正式版文档里**（而 1.15 正式版还没发布，
本地 `docs/upstream-tun.md` 的 `#### mtu` 只有一句 “The maximum transmission unit.” ——
无默认值、无建议值、无 Since 徽章）。所以这类待办**天然落在现有门禁能力之外**，
需要的是“提醒”而不是“校验”。

**修法**

1. 矩阵 schema 增 `follow_up` 字段（数组，元素 = 一句话待办 + 触发条件），
   承载“迁移时还要重新决策的参数”这类附加项；`new_tun_sing_tun_stack` 把 mtu 那句从 `reason` 移进 `follow_up`。
2. 门禁：`follow_up` 非空 ⇒ **每次跑 `audit.py` 都打 INFO 提醒**（不是 ERROR，因为尚未到决策时点），
   内容含条目 id 与触发条件；这样“读不读到”不再取决于人。
3. 决策截止（`decide_by`）到期时，`follow_up` 未清空 ⇒ 升级为 ERROR。

**门禁**：`matrix_follow_up_reminder`

**涉及**：`docs/version-matrix.json`、`tools/audit.py`、`docs/DECISIONS.md`（D1 的前提/风险栏）

---

## L27 文件头声称“每条都必须有”，而从没有人验证过

**现象**

`docs/LESSONS.md` 的文件头第 3 行写着：

> 每条教训都必须有：现象 → 根因（含源码位置）→ 为什么没被拦住 → 修法 → 已加的门禁 code。

实测这条声明**大面积不成立**：25 条里只有 10 条（L1/L2/L18–L25）五要素齐备。
L7–L15 用 `**现象/风险**` 替代 `**现象**`、根本没有 `**根因**` 与 `**为什么没被拦住**` 段；
L10/L12/L13 连 `**修法**` 都没有（只有 `**门禁**`）。
同一个文件里还有第二处同型错误：头部写格式是 `### L<n> <标题>`，实际全部是 `## L<n>`；
头部写「`门禁：` 行」，实际是 `**门禁**：`（`tools/audit.py` 的判定就是 `line.startswith("**门禁**：")`）——
**照着头部的写法加一条新教训，门禁会抽不到任何 code**。

**根因**

写头部的时候，声明描述的是**意图**（“我打算每条都写全”），
而 `audit_lessons()` 实现的是**可机器校验的那一半**（code 双向追溯）。
两者之间那句“每条都必须有”从来没被翻译成检查条件 ——
于是它退化成一句**让读者放心、但不产生任何约束力**的话。
更糟的是格式描述写错了，而错的那一版**会让新加的条目静默失效**（门禁抽不到 code 却不报错）。

**为什么没被拦住**

`audit_lessons()` 当时只做两件事：code 双向追溯、`**门禁**：` 行是否存在。
“这一段写了没有”属于**文档内部结构**，没有纳入检查范围 ——
**而文件头的声明恰恰是最像“已经检查过了”的地方**，所以最没人回头验。

**修法**

1. `audit_lessons()` 增加段落存在性检查：每条要点必须能在正文里匹配到
   `**根因` / `**为什么` / `**修法`（`**现象**` 允许写作 `**现象/风险**`，早期条目的既有写法）
   与 `**门禁**：` 行；缺哪段就报 ERROR `lesson_missing_element`。
   实测这一步立刻抓出 12 条（L3–L15 中的 12 条），随后逐条补齐。
2. 头部改成与实现**逐字对齐**的表述：明确是 `## L<n>`、`**门禁**：` 行、
   并写明“缺哪一段会报 `lesson_missing_element`”。
3. 头部必须与检查代码同源 —— **凡在文件头写“必须”，就要能说出是哪一行代码在保证它**。

**门禁**：`lesson_missing_element`, `lesson_missing_gate_line`

**涉及**：`docs/LESSONS.md`（头部 + L3–L15）、`tools/audit.py`

---

## L28 `dns.rules` 与 `route.rules` 是两份独立的顺序表 —— 只改一处就是静默失效

**现象**

把 Jinx / 秋风广告规则前置到 DNS 层后，配置能启动、`sing-box check` 也过，
但结果是**要么白名单没生效**（微信、极光推送、友盟统计类域名集体 NXDOMAIN），
**要么拦截没生效**（国内广告域名照旧解析成功），
而且**日志里看不出任何异常** —— 只有逐条看 `dns.rules` 的求值顺序才能发现。

**根因**

- 这两张表的匹配语义完全一样：`dns/router.go` 的规则循环与 `route/route.go:670-705` 的 `matchRule`
  都是**首个终止动作命中即 break**，`predefined` / `reject` / `route` 都是终止动作。
- 但它们是**两份独立的顺序表**，各写各的，没有任何机制保证两者一致。
- 顺序错的两个方向都是静默的：
  - **白名单排到拦截之后** —— 实测 Jinx 白名单 47 条域（`local/android-usai.json` 用到的
    `jinx-direct`：43 条 `domain` + 4 条 `domain_suffix`）**100% 被拦截集覆盖**
    （`gm.mmstat.com` ← `mmstat.com`、`jpush.cn` 及其 9 个子域 ← `jpush.cn`、
    `zlink.ugsdk.cn` ← `ugsdk.cn`、`seeds-sina.xycdn.com` ← `xycdn.com`）。
    拦截集一旦排在前面，白名单**一条都救不回来**。
  - **拦截排到 `geosite-cn` 之后** —— 国内广告域名多数也算大陆域名，
    会先被 `{"rule_set":["geosite-cn"],"action":"route","server":"dns-cn"}` 放行。
- 另一类静默错误：把广告拦截集写成 `"action": "route"`。DNS 层的 `route` 是「换个服务器去解析」，
  不是「拒绝解析」⇒ 广告域名照常解析成功，**看起来配置完全正常**。

**为什么没被拦住**

`_audit_jinx()` 只校 `route.rules` 那一侧：
  · 顺序判据用的是 `route.rules` 里 `rule_set` 的首次出现位置；
  · 与 DNS 无关。
而 `dns.rules` 侧当时唯一的检查是「引用完整性」（`dns_rule_ruleset_missing`）——
它只问「这个 tag 存不存在」，不问「顺序对不对、动作对不对」。
更糟的是：早先 `_audit_jinx` 里还写死过一条
「**广告规则集不得出现在 `dns.rules` 的 `rule_set` 里（那是 DNS 分流，不是拦截）**」——
这条注释把「DNS 层拦截」整个判成了非法用法，直接挡住了后来这次正确的实装。
⇒ 教训：**约束要按「语义」写，不能按「当下这种做法」写**。

**修法**

- `dns.rules` 里插入两条，且顺序固定（详见
  `docs/evidence/2026-10-12-dns-layer-adblock-feasibility.md`）：

  ```json
  { "rule_set": ["jinx-direct"],            "action": "route",      "server": "dns-cn"  },
  { "rule_set": ["jinx-ads", "awanue-ads"], "action": "predefined", "rcode": "NXDOMAIN" }
  ```

  两条都必须排在 `geosite-cn → dns-cn` **之前**（白名单 → 拦截 → geosite-cn）。
  拦截动作只能用 `predefined` 或 `reject`；**不能用 `route`**。
- 新增 `_audit_dns_adblock(cfg, rep)` 把上述约束机器化；同时把 `_audit_jinx` 里那条
  反注释改成「route 层广告拦截集只能落到 AD 组或直接 reject（DNS 层见 L28）」。
- **route 层规则不能删**：任何绕过 sing-box DNS 的解析（应用自带 DoH/DoT、系统私有 DNS）
  只有在 route 层才拦得住。DNS 层是**前置**，不是**替代**。

**门禁**：`dns_ad_without_whitelist`, `dns_ad_target`, `dns_ad_order`

**涉及**：`dns.rules`、`route.rules`、`local/android-usai.json`、`tools/audit.py`

---

## L29 防泄漏门禁只扫「已跟踪文件」—— 新文档本地全绿、CI 一推就红

**现象**

`docs/evidence/` 下新写的证据文档里带了几个实测 IP，本地 `python tools/audit.py` 全绿，
`git push` 之后 CI 立刻报 5 个 ERROR（`sensitive_ip_in_repo`，指向那个新文件的
第 55 / 114 / 115 / 116 行）。同一个仓库、同一份门禁代码，结论却相反。

**根因**

`audit_redaction()` 的文件名单来自 `git ls-files` —— 它只列**已跟踪**文件。
新写的文档在第一次 `git add` 之前根本不在这个名单里，
所以我本地跑（当时是跑在 `git add -A` 之前）时它完全不被扫；
而 CI 是 checkout 已提交内容之后跑的，文件必然已跟踪，于是被扫出来。
⇒ 门禁代码相同，**输入集合不同**，结论自然不同。

**为什么没被拦住**

这不是「用错门禁」，是**门禁自身的设计缺陷**：
`audit_redaction()` 想表达的是「仓库里不许有未审阅的公网 IP」，
而 `git ls-files` 回答的是「仓库里**现在已有**什么」——
「仓库里**即将有**什么」它天生看不见。
我跑验证的时机（先 audit、后 `git add`）只是把缺陷暴露出来；
就算我当时顺序对了，**把正确性寄托在「记得先 add」上，等于没有门禁**。

**修法**

`audit_redaction()` 的文件名单改为两个来源合并去重：

```
git ls-files                              # 已跟踪
git ls-files --others --exclude-standard  # 未跟踪、且未被 .gitignore 忽略 = 即将提交的新文件
```

`local/` 仍在 `startswith("local/")` 处跳过（它被 `.gitignore` 忽略，本就不在名单里）。
推论：**交付前跑 audit 必须与 CI 同条件** —— 先 `git add -A`，再 audit。

**门禁**：`sensitive_ip_in_repo`, `redaction_clean`

**涉及**：`tools/audit.py`、`docs/evidence/`、`.gitignore`

---

## L30 门禁常量不带时区 —— 本机（+0800）与 CI（UTC）扫出两个不同的窗口

**现象**

刚修完 L29 的同一轮里，CI 是绿的，
但我在本机跑同一条命令却报 1 个 ERROR：
`公网 IP <某个未审阅公网 IP> 出现在 commit message`。
两边跑的是**同一份代码、同一个提交**。

**根因**

`LEAK_SCAN_START_DATE = "2026-10-12 20:00:00"` —— **没有时区偏移**。
`git log --since=<无偏移字符串>` 由 git 按**执行机器的本地时区**解释：

| 执行环境 | 解释为 | 窗口内提交数 |
|---|---|---|
| 本机（CST, +0800） | `2026-10-12 12:00 UTC` | **6** |
| CI（Ubuntu, UTC） | `2026-10-12 20:00 UTC` | **0** |

⇒ 本机多扫了 6 个提交（其中包含我写测试时留在 commit message 里的一个公网 IP），
CI 一个都没扫。**同一份门禁，因为运行环境不同而给出相反结论。**

**为什么没被拦住**

L29 我刚写下「交付前跑 audit 必须与 CI 同条件」——但那条纪律只覆盖了
**输入集合**（先 `git add -A`），没覆盖**环境**（时区、locale、路径分隔符……）。
我把「与 CI 同条件」理解成了「先 add」，漏掉了这一层。
换句话说：L29 和 L30 是**同一个错误的两半** ——
「本地必须能复现 CI 的结论」这件事，一半靠输入齐全，一半靠环境一致。

**修法**

- 常量改为带显式偏移的 ISO 形式：
  `LEAK_SCAN_START_DATE = "2026-10-12T20:00:00+08:00"`。
  这样本机与 CI 解释出的绝对时刻完全相同，窗口重归一致。
- `audit_tools()` 加自检：常量必须匹配
  `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$`，
  否则报 `tool_selftest_failed`。**把「只有真正跑过 CI 才知道」的差异，
  变成一个本机就能红的门禁** —— 这是 L25（工具也要被自己的门禁检查）的直接应用。
- 一般化：**凡是被 git / 文件系统 / 系统 API 解释的字符串常量，都必须自带环境信息**
  （时间带时区、路径用绝对或 `/`、编码显式指定）。

**门禁**：`tool_selftest_failed`

**涉及**：`tools/audit.py`、`docs/LESSONS.md`

---

## L31 把 commit message 顺手 amend 掉，却没有推送 —— 远端留下「带脏 message 的双胞胎」

**现象**

修 L30 时我用 `git commit --amend` 把 message 里的测试 IP 换成了占位描述，
本机 `git log` 看着很干净、门禁 0 ERROR。
但 `git ls-remote origin main` 给出的 SHA 与本地 HEAD **不是同一个**：

| | commit message |
|---|---|
| 本地 HEAD（amend 后的新提交） | 干净（占位描述） |
| 远端 `origin/main`（amend 前的旧提交） | **仍含那个测试 IP** |

两个提交的 **tree 完全相同**（同一个 `%T`）、parent 相同、author date 相同，
**只有 commit date 与 message 不同** —— 典型的「amend 产生双胞胎」。

> ⚠️ 按 L24，本条**不写这两个提交的 SHA**：SHA 是能在 GitHub 上直取旧对象的指针，
> 写进仓库等于把要清理的东西又引用一遍。初稿确实写了，被自己复查揪出来（见「修法」）。

**根因**

`git commit --amend` 只改本地；**它不会推送**。我在同一轮里 amend 完就直接跑
`git log` 自检，看到的是本地视图，于是以为「已经修好了」。
而 `audit_redaction()` 是**在本地工作区里**跑 `git log` —— 它扫的是**本地历史**，
自然也扫不到远端那个仍然带脏 message 的旧提交。
⇒ **门禁的视野 = 本地仓库，而泄漏的载体 = 远端仓库。两者不是一回事。**

**为什么没被拦住**

没有任何门禁会去比对「本地 HEAD 与 `origin/main` 的 message 是否一致」——
`audit_redaction()` 只扫本地 commit message，它看不见远端。
这跟 L29（只看已跟踪文件、看不见未 add 的新文件）是同一类病：
**门禁的输入集合比泄漏的传播面窄**。历史里还犯过一次更严重的（`ec5d300`，见 L24）。

**修法**

- 推送后一律用 `git ls-remote origin main` 核对远端 SHA 是否等于本地 HEAD。
  **`git log` 绿 ≠ 远端干净**；判断泄漏是否真的清了，必须看远端。
- 需要 amend 已推送的提交时：`git push --force-with-lease` 是必须的收尾动作，
  不能停在 amend。（`--force-with-lease` 而非 `--force`：远端被别人推进时会拒绝。）
- 一般化：**任何「修改历史」的操作（amend / rebase / reset）都以「推送完成」为终点**，
  否则本地与远端会出现两个语义相同、内容不同的提交，而所有本地自检都只看得见其中一个。
- 连带自查：写完这条教训后我自己又犯了一次 L24 —— 初稿把两个提交的 SHA
  原样抄进了正文。**写「不要写 SHA」的教训时，最容易顺手写上 SHA。**
  描述事故一律用「日期 + 背景 + 相对身份（远程/本地、新/旧）」，不用 SHA。

**门禁**：（本轮由人工核对发现，暂无自动门禁。若要加，方向是「推送后校验远端 HEAD 的
commit message 与本地一致」，但需要网络与远端访问，不适合放进无网 CI。）

**涉及**：`git` 操作纪律、`AGENTS.md`

---

## L32 平台差异清单零门禁 —— 第 1 节把「Android 上静默失效」的字段写成 ✅

**现象**

`docs/PLATFORM-MATRIX.md` 第 1 节长期只有一行：

```
| route_address / route_exclude_address 系列 | ✅ | ✅ | ✅ |
```

而这行是**错的**：`_set` 变体（`route_address_set` / `route_exclude_address_set`）
在 **Android 图形客户端完全无效**，而且是**静默**无效 —— 不报错、不警告，只是白写。
用户按这行给安卓加「bypass 大陆 IP」，会得到一份毫无效果却看起来正确的配置。

同一份文档第 4 节写「其余（`dns`/`route`/`outbounds`/`http_clients`）三平台完全一致」，
漏了 `experimental`（差异恰好在那里：desktop 多一个 `clash_api`，三家 `cache_id` 各不相同）。

**根因**

平台差异的文档在**第 1/2 节是一句人话**（「✅/❌/⚠️ + 说明」），
`tools/audit.py` 的 `audit_platform_caps()` 只看配置里**出现了什么**（写了 `strict_route` 就报），
**不看官方能力清单**，于是：

- 文档写错 → 没有门禁能发现；
- 配置里缺少某平台的东西（例如 Android 该删没删）→ 也没有门禁。

`grep PLATFORM-MATRIX tools/*.py` 只命中 `audit.py` 文件头的一句注释 ⇒
「平台差异的唯一真源」在机器面前**完全不存在**。

**为什么没被拦住**

矩阵的断言全是**散文**（✅、❌、⚠️ + 中文说明），没有任何可机读的形状，
所以既没法解析、也就没想过要解析。直到要把它变成门禁时才发现：
**散文天生不可校验**，必须先把它压成「JSON 路径 + 期望值」的三列表格。

**修法**

1. 修事实：`route_exclude_address_set` 从「系列」里拆出来单独一行，Android 标 ❌ 并新增 §1a
   写清两个内核闸门（`protocol/tun/inbound.go:384` 的 `if t.platformInterface == nil || C.IsWindows`
   与 `:418` 的 `!(runtime.GOOS == "android" && t.platformInterface != nil)`）。
2. 把 §4 速查表改成**机器读得懂的六行**：第一列 `` `JSON 路径` ``（可加「条数」后缀），
   后三列 `` `JSON 字面量` `` 或 `**删除**`，说明文字一律移到表外。
3. 新增两条门禁（`tools/audit.py`）：
   - `matrix_platform_stale` —— §4 逐格与三份 `profiles/1.14/*-lazy.json` 实际值对账；
   - `profile_drift` —— 反向兜底，三份配置出现**任何**未登记的差异即 ERROR
     （防止「悄悄改了配置、忘了登记」和「登记了但配置没改」两个方向）。
4. 明确能力清单（§1/§1a/§2/§2a）**无法机器核对**（没有可靠的官方机读源），
   只能按来源一栏人工复核 —— 这点写在文件头，免得下次误以为它也被上锁了。

**门禁**：`matrix_platform_stale`, `profile_drift`, `matrix_platform_ok`

**涉及**：`docs/PLATFORM-MATRIX.md`, `tools/audit.py`, `AGENTS.md` 铁律 18

---

## L33 骨架模板与实例配置之间没有任何一致性检查

**现象**

`templates/groups.json` 是「这份配置该有哪些分流组」的唯一声明
（`🚀 Proxy` / `🤖 AI` / `🚫 AD` / `direct` / `block` / `direct-download`），
三份 `profiles/1.14/*-lazy.json` 是它的实例。但在本轮梳理前：

- 模板里加一个组、profile 没跟着加 → 机器全绿；
- 模板说 `AI` 必须是 `urltest`、某个 profile 悄悄写成 `selector` → 机器全绿；
- profile 里冒出一个模板没登记的组 → 机器全绿。

`audit_template()` 只审模板自己（组在不在、类型对不对），
**从头到尾没有任何一行代码把模板与 profile 放在一起看**。

**根因**

`audit_template(rep)` 的签名里根本没有配置参数 —— 它被设计成「只审那一份骨架文件」。
于是「模板对不对」有门禁，「照模板做出来的东西对不对」没人管。

这类缺口的共同形状是：**检查只覆盖了「声明」，没覆盖「声明 ⟺ 实现」**。
同一个形状在 L26（风险点无字段承载）、L27（文件头声明无人校验）、L32（矩阵零门禁）里都出现过。

**为什么没被拦住**

模板是给**人**看的参考文件，最早引入时只当成一份「复制粘贴的起点」，
没被当成「可校验的接口」。接口一旦不被校验，它的值就退化成了注释。

**修法**

新增 `audit_matrix_coverage()`（`tools/audit.py`），双向对账：

1. 模板里每个 selector/urltest 组，三份 profile 都必须有，且**类型一致**
   → `template_profile_group_missing` / `template_profile_group_type`；
2. profile 里每个 selector/urltest 组都必须在模板里有登记
   → `profile_group_not_in_template`；
3. 全部通过时打 INFO `matrix_coverage_ok`。

**门禁**：`template_profile_group_missing`, `template_profile_group_type`,
`profile_group_not_in_template`, `matrix_coverage_ok`

**涉及**：`templates/groups.json`, `profiles/1.14/*-lazy.json`, `tools/audit.py`

---

## L34 门禁按一个「早就不再使用的字面量」匹配 —— 它永远不会响

**现象**

`audit_platform_caps()` 里有一条 WARN 门禁 `android_resolver`，判据是
「Android 平台上某个出站的 `domain_resolver` 指向 `dns-local`」。
而本仓库的 DNS 服务器 tag **从一开始就是** `dns-bootstrap` / `dns-cn` / `dns-proxy`，
`dns-local` 只在 `archive/1.14/` 的旧文件里出现过 —— 而 `archive/` 不在扫描范围内。

⇒ 这条门禁**在任何输入下都不可能报出**。它给人的却是「Android 的 DNS 解析器问题已经被守住了」
这种安全感，比没有门禁更坏。

**根因**

门禁是**按字面量匹配**写的（`domain_resolver == "dns-local"`），而那个字面量对应的命名法
在后续重构中被替换掉了：DNS 服务器从「按类型命名」改成「按用途命名」，
`dns-local` 变成了 `dns-bootstrap` + `dns-cn` + `dns-proxy` 三个。
代码里的字符串常量没人同步 —— 它指向的东西**已经不存在了**。

这是 L2/L7/L25 同一个形状的又一种表现：**代码里的断言与它描述的现实脱钩后，
不会自己报错，只会静静失效**。区别在于前几次脱钩的是「配置」，这次是「门禁自己的判据」。

**为什么没被拦住**

- `audit_lessons()` 的双向校验只查「code 在台账与代码里两边都有」，
  查不出「code 永远不可能触发」；
- 门禁的输出里，**没报错和「报不了」长得一模一样**（都是绿）。
  这正是 L25「门禁只审配置、不审自己」的同一个盲区 —— 只不过 L25 管的是
  「工具能不能跑」，这里管的是「工具的判据还对不对」。

**修法**

1. **删掉** `android_resolver` 门禁，并在 `docs/LESSONS.md` L8 里记下删除原因，
   写成「已废弃的一项」，免得日后有人照着旧文档又把它加回来。
2. 一般化的纪律（写进 `AGENTS.md` 铁律 19 的注脚）：**门禁里出现的每个字面量，
   都必须在当前配置里真的会被用到**。新增一条按字面量匹配的门禁时，
   顺手 `grep` 一下那个字面量在三份 profile 里出现几次 —— 0 次就说明这条门禁是死的。
3. 同轮把 `audit_platform_caps()` 重写成「按平台能力清单」而不是「按配置里出现了什么反查」，
   让新增的能力约束有个统一的落脚点（见 L32）。

**门禁**：无（本条说的正是「删掉一条死门禁」）。删除后的一致性由既有的双向校验兜住：
`_audit_gate_codes()` 与 `_lessons_gate_codes()` 要求「代码实现了的门禁」与「台账声明的门禁」
两边对齐 —— 所以删代码时必须同时删掉 L8 里对它的声明，否则立刻报 `lessons_missing_gate`。

**涉及**：`tools/audit.py`, `docs/LESSONS.md` L8, `AGENTS.md` 铁律 19

---

## L35 组改名只改了「定义」，没改「引用」—— `dns.servers[].detour` 指向了不存在的出站

**现象**

把三个分流组改名成 `🚀 Proxy` / `🤖 AI` / `🚫 AD`（m07194）之后，
`local/android-usai.json` 里 `outbounds[].tag`、`route.final`、`route.rules[].outbound` 都改了，
唯独 `dns.servers[2].detour` 还写着 `"Proxy"` —— 而配置里已经没有任何出站叫 `Proxy` 了。

**根因**

`dns.servers[].detour` 和 `route.rules[].outbound` 一样，是**按 tag 字符串引用出站**的字段。
改名时我按「组定义 + route 引用」列清单，没有把 `dns` 段算进引用面。
`tools/audit.py` 当时校了 `route.rules[].outbound`（`rule_outbound_missing`）、
`route.final`（`final_missing`）、`route.rule_set[].tag`（`rule_ruleset_missing`）、
`dns.rules[].server`（`dns_rule_server_missing`）、`dns.rules[].rule_set`（`dns_rule_ruleset_missing`）、
`dns.final`（`dns_final_missing`）、`outbounds[].outbounds`（`dangling_ref`）、
`route.default_domain_resolver.server`（`ddr_missing`）——
**唯独漏了 `dns.servers[].detour`**，而它恰好是唯一一处「组 tag 出现在 dns 段」的地方。

**为什么没被拦住**

1. 该字段当时没有任何门禁：所有 `detour` 相关的检查都只扫 `http_clients` 与 `route.rule_set[].download_detour`
   （它们查的是「空 direct 出站」问题，`dangling_download_detour`），不扫 `dns.servers`。
2. `sing-box check` 对这个错误 **exit=0**。check 只做反序列化、不做任何初始化。
   要注意的是：**`--run` 是能抓到它的** —— 真启动时会 `FATAL start service: start dns-transport:
   start dns/https[dns-proxy]: outbound detour not found: Proxy` 立刻退出（DNS 服务本身要挑出站，
   这是启动期的硬依赖）。所以这一条本可以被 `--run` 拦住，只因它出现在**不进仓库的 `local/`** 里，
   而 `--run` 在 CI 上只跑 `profiles/` 与 `templates/`。
3. 三份 profile 是**一起**改的（都改对了），所以 `profile_drift`（查「三份不一致」）也发现不了 ——
   这个错误只出现在不进仓库的 `local/*.json` 里，仓库门禁本来就扫不到它们。

**修法**

1. 修数据：`local/android.json` / `android-usai.json` / `android-A-dns-ipv4only.json` /
   `android-B-full-ipv4.json` 四份的真节点配置逐份补改（`android.json` / A / B 各 8 处，
   `android-usai.json` 1 处 —— 前一轮改它的 `dns` 段时漏了这一个字段）。
2. 加门禁 **`dns_server_detour_missing`**：`dns.servers[i].detour` 必须存在于出站 tag 集合中。
3. 同轮把「引用 dns.servers 的 tag」也补成完整清单，加门禁 **`domain_resolver_missing`**：
   `outbounds[].domain_resolver.server` / `route.rule_set[].domain_resolver.server` /
   `http_clients[].domain_resolver.server` 三处都必须存在于 `dns.servers[].tag` 中。
   门禁对**空 `dns_tags` 的骨架模板**放行（`templates/groups.json` 没有 dns 段，
   不能因为「引用了尚未声明的 DNS 服务」报错）。
4. 一般化的纪律：**改名时的引用面清单，应当来自「这个字符串在配置里出现的所有位置」，而不是来自记忆。**
   做法：`grep -o` 出该 tag 在全仓 JSON 里的出现次数，逐个确认；或直接用
   `python tools/diff_config.py` 比对新旧配置。本条同时暴露了铁律 20 的注脚还不够硬。

**门禁**：`dns_server_detour_missing`, `domain_resolver_missing`

**涉及**：`tools/audit.py`, `local/android.json`, `local/android-usai.json`,
`local/android-A-dns-ipv4only.json`, `local/android-B-full-ipv4.json`, `AGENTS.md` 铁律 20

---

## L36 组改名 98% 的成本在散文里，而散文一处门禁都没有

**现象**

执行「组 tag 加 emoji 前缀」（`Proxy` → `🚀 Proxy`）时：

- 配置侧要改的**只有 24 处**（三份 profile 各 8 处 + 模板 + `nodes.example.json`），
  且每一处都有门禁盯着（`profile_drift` / `dangling_ref` / `template_profile_group_missing`）。
- 散文侧要改的是 **240 处、19 个文件**（`docs/LESSONS.md` 39、`tools/audit.py` 54、
  `docs/WORKFLOW.md` 32、`AGENTS.md` 39…），**一处门禁都没有**。
- 实际耗时几乎全在散文：我手写了两版替换脚本（`_retag.py` / `_retag2.py`，13 条上下文正则），
  仍然漏掉 `templates/groups.json:46` 的裸 `Proxy`（搭配是「与 Proxy 各自独立测速」，
  不在任何模式里），只能靠人肉 grep 一轮一轮找漏。

**根因**

配置里的组 tag 是**有类型的引用**（JSON 字符串，位置可枚举，门禁可逐格对账）；
散文里的组 tag 是**无类型的词**——同一个 `Proxy` 可能是：

1. 组名引用（`jinx-ads → AD`、`` `AD` ``、`selector[AD]`）——**必须改**，
   因为下一个读它的人会照抄进配置，留旧名就等于埋悬空引用（这正是 L35 的成因）；
2. 历史叙述（「用户原话：给 Proxy 改为🚀 Proxy」「早期 AI 实现成 selector(outbounds=[Proxy])」）
   ——**绝不能改**，改了就是篡改记载；
3. 完全无关的词（`NaiveProxy`、`OpenAI`、「给 AI 读的入口」）——**改了就错**。

在门禁出现之前，区分这三类**只靠人的判断力**。而判断力不可累积、不可回归、不可交接——
每换一轮上下文就得重新判断 240 次。这就是「组改名很慢」的全部原因。

**为什么没被拦住**

`tools/audit.py:13` 的文件头注释写着「设计依据：docs/version-matrix.json（字段生命周期）、
`docs/PLATFORM-MATRIX.md`（平台能力）」，但 `PLATFORM-MATRIX.md` 当时零门禁（L32 已修）。
散文组名更是从头到尾没有任何检查——`grep -n 'group_name' tools/audit.py` 在本次改动前为空。

更根本的原因：**门禁体系只覆盖「有 schema 的东西」**（JSON 字段、台账条目形态），
而「文档里的名词是否过期」不属于任何 schema，所以从来没人想过要检查它。

**修法**

新增 `audit_doc_group_names()`，把上述三类区分写成代码：

- 文件范围 = `_tracked_files()`（含未 add 的新文件，L29）去掉 `docs/upstream-*`、`archive/`、
  `docs/evidence/`、`docs/schema.json`。
- **历史台账豁免**：`docs/LESSONS.md` 与 `docs/DECISIONS.md` 是**追加型历史记录**，
  它们必须能写下旧名（改名决策本身就得写出「由 `Proxy` / `AI` / `AD` 改成…」）。
  门禁只管**活文档**——下一个人会照着写新配置的那些。
- 规范名自带 emoji 前缀，故向前看 **2 个字符**（emoji + 一个 ASCII 空格）才算命中规范名；
  只看 1 个字符会漏掉那个空格，把 `🚀 Proxy` 里的 `Proxy` 误判成旧名（第一版就是这么错的）。
- 只报**配置引用位**（`→ X` / `outbound X` / `selector[X]` / `` `X` ``）；
  散文短称（「🚫 AD 组」「🚫 AD 里的 direct」）不报——强行全写成长名只会变噪音。
- 豁免：`EXEMPT` 关键词（旧名/原话/改名/仍指向/早期…）、专有名词（`NaiveProxy`/`OpenAI`）、
  「AI = 人工智能/助手」的搭配词，以及门禁自己的**反向检测字面量**
  （`{"Proxy", "AI", "AD"}`——改成规范名就变成永远不响的死检查，同 L34 的教训）。

**门禁**：`doc_group_name_stale`, `doc_group_name_clean`

**涉及**：`tools/audit.py`, `AGENTS.md` 铁律 20, `templates/groups.json`


---

## L37 门禁从来没有被反向验证过 —— 负向样本一次性用完即删

**现象**

组改名那一轮，验证新门禁靠的是**临时现写脚本**（`local/_negtest.py`、`local/_neg1.sh`……），
跑完就删。下一轮要验证别的门禁时，从零再写一遍。

代价有三层：

- **慢**：每轮重新造样本、重新调 CLI、重新解析输出；
- **没回归网**：改门禁时把一个能响的检查改成不响的，`audit.py` 自己照旧全绿；
- **死检查无人知**：L34 那个 `android_resolver` 按早就不再使用的字面量匹配，
  **永远不会响**，但从代码到 CI 没有任何一环会发现 —— 因为「不响」和「没事」看起来一样。

**根因**

门禁的**验证方式**从来没被产品化。每道门禁只在写它的那一次被人肉确认过，
之后就再没有任何机制重复验证它。`audit.py` 的设计原则是「干净时安静」——
这恰好意味着**一个彻底失效的门禁与一个正常工作且无事的门禁，输出完全相同**。

这是 L25（工具自检）、L29（未被跟踪文件）、L30（时区常量）的同一类问题：
**验证手段本身没有验证**。

**为什么没被拦住**

因为「临时脚本用完即删」在当时看起来是负责的行为 —— 没人希望仓库里堆一次性文件。
但它把「一次性的验证」当成了「验证完成了」，于是验证成果不可积累、不可回归。

更隐蔽的是：临时代码只需在「刚刚改过的那一种破坏」上正确，它不需要对**下一轮**负责。

**修法**

新增 `tools/negtest.py` —— 把负向样本固化成**常驻回归套件**：

- 24 个用例，每个 = 「取真实 profile 的 dict → 做一处最小破坏 → 期望某 code 报出」；
- 走**真实的 CLI**（`python tools/audit.py --no-check --json <file>`），不 mock、不 import 审计函数，
  走的就是 CI 走的那条路；
- 支持 `-k` 过滤与 `-v` 详情；跑完自动清理 `local/_negtest/`；全程约 1 秒。

三条语义细分（都是跑第一遍就暴露出来的）：

1. **作用范围**：`single` = 临时配置只跑那一份（快）；
   `repo` = 临时改**真实** `profiles/1.14/android-lazy.json` 跑整仓审计再还原 ——
   因为 `template_profile_group_missing` / `doc_group_name_stale` 这类门禁**必须与真实文件对账**，
   临时文件根本触发不了（`_load_profiles()` 读的是真实路径）。用 `try/finally` + 字节比对保证还原。
2. **期望级别不是常量**：`cache_path_abs` 是 **WARN** 不是 ERROR ——
   而 harness 的 `_audit_codes()` 默认只收 ERROR，把「能响的 WARN 门禁」误判成死检查。
   于是级别必须逐个用例声明，不能写死。
3. **豁免要按「谁需要旧名」判定，不能按文件名硬编码**：`negtest.py` 上线后
   立刻被 `doc_group_name_stale` 拦下（它的**本职就是写出旧名**）。
   若当时按文件名硬编码 `tools/negtest.py`，下一个负向脚本又会重踩；
   改为 `_is_negative_fixture()`（按词根 `neg`/`_neg` 判定），
   覆盖 `tools/negtest.py` 与 `local/` 下的一次性脚本。

另修一个平台坑：Windows 上 stdout 重定向到管道时默认回退 GBK，本文件到处是 ✅/❌，
一 `| tee` 就 `UnicodeEncodeError` 崩掉 —— **管道里崩**正是「本地绿、CI 红」的温床。
故 import 后立即 `reconfigure(encoding="utf-8")`。

接入点：`tools/check-all.sh` 新增 `[3/4] 门禁负向回归`；CI 新增同名 step。

**门禁**：无（本条目约束的是「验证手段」本身，由 `tools/negtest.py` 与
`tools/check-all.sh` 承载，不产生 `audit.py` 的 code）

**涉及**：`tools/negtest.py`, `tools/check-all.sh`, `.github/workflows/audit.yml`


## L38 门禁只说「哪里错」，不说「改哪里」—— 定位成本被转给了人

**现象**

门禁报错长这样：

```
[E] §4 说 desktop 的 `inbounds[0].strict_route` 是 `true`，实际是 None
[E] 三份 profile 的 `dns.servers[2].server` 不一致（...），但 §4 表里没有登记这一项
```

两条都能看懂**错在哪**，但要说清**该改哪一行**，还得自己回文件里搜 ——
第一处要改的是 `docs/PLATFORM-MATRIX.md` 的 §4 表格某一行，
第二处要改的是同一张表（**加**一行），而报错文本里没有行号、没有文件名。

**根因**

`Report.error(code, msg)` 的消息是**人写的散文**，而定位信息本来就在代码手里：
`_sec4_rows()` 解析表格时逐行遍历，行号唾手可得；`audit_matrix_coverage()` 也知道
出事的是哪一份 profile。但接口只接受「一段文字」，于是定位信息在拼消息时就丢了。

这不是「写得不够详细」，而是**接口缺字段**：只要 `Report` 没有承载位置的地方，
每道门禁都会各自决定要不要把位置塞进散文里 —— 结果就是只有一部分塞了、格式还各不相同。

**为什么没被拦住**

因为门禁的验收标准一直是「能不能报出来」。定位质量不属于任何一条门禁的判据，
也不影响退出码，于是它永远排在被砍掉的那一侧。

**修法**

给 `Report` 的三种级别加第三个可选参数 `where`（`文件:行号`，统一 `/`、相对仓库根）：

- 终端输出改成 `[E] <消息>   ← <文件>:<行号>`，`--json` 里多一个 `where` 字段；
- `_sec4_rows()` 顺带返回每行在原文里的**行号**（§4 起始行 + 段内偏移）；
- `profile_drift` 指向 §4 表头（要加行的地方），
  `template_profile_group_missing` / `profile_group_not_in_template` 指向出事的那份 profile；

⇒ 读报错的人不用再搜索：`← docs/PLATFORM-MATRIX.md:179` 直接跳过去。

**门禁**：`matrix_platform_stale`, `profile_drift`, `template_profile_group_missing`,
`template_profile_group_type`, `profile_group_not_in_template`

**涉及**：`tools/audit.py`（`Report` / `_loc()` / `_matrix_sec4_lineno()` / `_sec4_rows()`）


---

## L39 门禁挂在矩阵的 `path` 上，而上游改了路径之后没有任何东西会告诉你

**现象**：`docs/version-matrix.json` 里 `kind=deprecated/removed` 的条目**全部靠 `path` 定位字段**
（`audit_matrix()` 用 `find_paths(cfg, e["path"])` 去找）。上游一旦把字段改名、搬走或删掉，
`find_paths` 就永远返回空 —— 条目**静默失声**：门禁还在 `audit.py` 里、`docs/LESSONS.md` 里也列着它，
`audit.py` 全绿，但那条保护已经不存在了。这与 L34（门禁按已经不再出现的字面量匹配）是同一种病，
但 L34 是「门禁自己写错」，这一条是「门禁没错、外面的世界变了」。

**根因**：门禁的输入有两个来源 —— 配置（`profiles/`、`local/`）与**知识**（矩阵的版本号、path、replacement）。
前者一直在扫，后者**只被扫过「有没有被 D 条目收录」**（`audit_decisions`），
从来没有人验过「矩阵里的 path 在锁定的内核上是否还找得到」。
单看矩阵看不出问题（它自洽），单看内核也看不出问题（它没坏），
只有**两个来源交叉比对**才暴露。

**为什么没被拦住**：因为这属于「缺一个探针」而不是「写错一行」。此前的所有门禁都是拿**配置**当输入，
上游改字段名这件事根本不进入任何检查的视野。另外它**天然不会自曝**：失效的门禁与正常门禁
在输出上完全一样（都是一行 `[i] sing-box check EXIT=0`）。
`tools/negtest.py` 也抓不到 —— 它靠「故意改坏配置」，而这条门禁的失效与配置无关。

**修法**：新增 `audit_matrix_paths()` —— **不读任何真实配置**，而是按矩阵的 `path` 反推出一个
最小探针配置，注入那个字段名，交给 `sing-box check` 判它认不认识：
- 内核报 `unknown field "<leaf>"` ⇒ 字段已不存在；
- 内核毫无意见 ⇒ 认识（可能顺带自报 `deprecated in sing-box A and will be removed in B`，与矩阵自称的版本号比对）。

按「矩阵声称该字段此时应当存在/已废弃」筛选后，只有一种情况判 ERROR：
**内核已经不认它，而矩阵还在要求门禁去查它**。

⚠️ 刻意**不报**的情况：矩阵说「已移除」、内核却仍然照收。这在本项目里是**常态** ——
sing-box 用 migration 保住旧字段，就是为了让人误用时不至于炸（例如 `inbounds[].sniff`、
`dns.servers[].address` 在 1.14.3 上仍被接受），正因如此才需要 `kind=deprecated` 门禁去拦。
第一版实现把它当 ERROR，一跑就是 17 条假报警，已删除。

**同类补强（同一根因的另一面）**：`tools/upgrade-check.py` 的 `TRACKED_DOCS` 原只跟踪四份上游文档
（`deprecated`/`migration`/`changelog`/`inbound/tun`），而**平台能力清单的唯一权威源**
（`docs/clients/apple/features.md`、`docs/clients/android/features.md`）没有本地快照 ——
上游把某个 `:material-close:` 改成 `:material-check:` 时，仓库里硬编码的平台判据
（`platform_strict_route` 等）会继续把**正确的写法判成 ERROR**，而且没人会知道。已纳入跟踪。

**门禁**：`matrix_path_unreachable`, `matrix_path_unprobeable`, `matrix_path_probe_error`,
`matrix_path_ok`, `matrix_probe_skipped`, `matrix_version_mismatch`

**涉及**：`tools/audit.py` 的 `_probe_candidates()` / `_probe_verdict()` / `audit_matrix_paths()`
与 `main()` 的 `probe_rep`；`tools/upgrade-check.py` 的 `TRACKED_DOCS`。

## L40 我在同一次会话里，用同一种方式毁了两份文件

**现象**：一次会话里两次把仓库文件写坏，且**方式完全相同**：

1. `tools/audit.py` 从 **1919 行被截成 828 行** —— 我用 `find(lambda l: l.strip() == 'try:')`
   定位替换点，命中的是文件里**第一个** `try:`（:514），不是我要改的那个。
2. `AGENTS.md` 变成 **0 字节** —— 脚本里 `open(p,'wb')` **先把文件清空**，
   后面才算要写的内容，而中间那句 `raw.replace('字符串', …)` 对 bytes 抛了 `TypeError`，
   异常把 `finally` 里的还原也一起跳过了。
3. （同一族）heredoc 里写 `b'\x00'` 被 shell 二次解释成**真 NUL 字节**，
   写进 `tools/audit.py` 后 `py_compile` 报
   `SyntaxError: source code string cannot contain null bytes`，整段重写两次。

**根因**：这三件事是**同一个**：我在「**先动文件、后确定内容**」。
`open(p,'wb')` 是「先动」，按短 token 定位是「还没确定要动哪一处就先动了」，
heredoc 是「内容先经过了一层我不控制的解释器」。
共同点：**写入这个动作被拆成了两半，中间插入了可能失败、可能被改写的步骤。**

**为什么没被拦住**：仓库里有 30 多条门禁，全部在检查**结果**（配置对不对、文档对不对），
没有一条检查**写入方式**。而这类事故的产物是「文件变短/变空」，恰恰不违反任何配置规则 ——
`git diff --stat` 才看得出来（`AGENTS.md | 323 ----`）。
另外我自己的一条错判推波助澜：我以为「先把备份 `cp` 到 `/tmp` 就安全」，
但 `/tmp` 路径在这台机器的 git/python 里**根本读不到**，等于没有备份。

**修法**：
1. 新增 `tools/patch-text.py` —— 把「改文件」变成一件不会伤到文件的事：
   - **原子写**：先算好完整内容 → 写同目录 `*.tmp-patch` → `os.fsync` → `os.replace()`；
     中途任何异常都不碰原文件（`open(p,'wb')` 那条路直接不存在了）。
   - **唯一锚点**：每条 patch 声明期望匹配次数，实际次数不符就**整体拒绝**、一个字节都不改。
   - **不经 shell**：find/replace 只从 JSON 读（`--spec-inline` 也走 JSON），
     不再有 heredoc 二次解释。
   - 每个 patch 打印 `文件:行号 匹配 N 处`，改了什么、改在哪一行当场可见。
2. 备份只放**仓库内**路径（`local/` 受 `.gitignore` 保护），不用 `/tmp`。
3. 铁律 22（`AGENTS.md`）：**改文件不许「先打开、后算内容」**。

**门禁**：无（约束的是「写入方式」而不是配置内容；由 `tools/patch-text.py` 与铁律 22 承载 ——
`audit_tools()` 会把 `patch-text.py` 一起 `compile()`，语法坏掉时报 `tool_syntax_error`）

**涉及**：`tools/patch-text.py`、`AGENTS.md` 铁律 22、`tools/audit.py` 的 `audit_tools()`

---
## L41 把临时文件写进 `local/` —— 我本机全绿，CI 直接跑崩

**现象**：`5a130fe` 推上去后 CI 立刻红，报错原文：

```
File "/home/runner/work/sing-box/sing-box/tools/audit.py", line 1141, in audit_matrix_paths
    tmp = LOCAL / ".matrix-probe.json"
FileNotFoundError: [Errno 2] No such file or directory:
    '/home/runner/work/sing-box/sing-box/local/.matrix-probe.json'
```

本机同一份代码 `0 ERROR`（`sing-box check` 与两次 `python tools/negtest.py` 都是绿的）。

**根因**：探针的临时文件写到了 `LOCAL / ".matrix-probe.json"`，而 `local/` **不入库**
（`.gitignore` 忽略、只存在我这台机器上）。CI 是 `git checkout` 出来的干净树 ——
**根本没有 `local/` 这个目录**，`write_text()` 的父目录不存在就 ENOENT。
探针在 CI 上反而是**最该跑**的那条（CI 里 `SINGBOX_BIN` 一定有值），
于是「本机跳过、CI 必跑」的路径恰好落在了「本地有、CI 没有」的目录上。

**为什么没被拦住**：这是 L29 / L30 的第三次变形，同一根因：
**门禁/工具的输入输出路径依赖了本机的目录布局**。
- L29：输入集合漏了「未 add 的新文件」（本机扫不到）；
- L30：常量字符串的时区由**执行机器**解释（本机 +0800 / CI UTC 两个窗口）；
- L41：输出目录只在本机存在。

共同点：**同一份代码在不同环境里输入/输出不同**。而这三件事在我本机跑都全绿 ——
「本机绿」永远是弱证据，这条在 L29 已写下，却又踩了一次。

**修法**：
1. 探针临时文件改用**系统临时目录**（`tempfile.gettempdir()`），与仓库布局解耦。
2. 顺手把一个**隐式约束**变成会响的断言：`local/` 只做顶层 glob、不递归，
   所以负向样本必须放在子目录里 —— 若哪天有人把 `NEGDIR` 改成 `local/` 顶层，
   临时样本会被整仓审计顺手审一遍，用例断言的「某 code 出现了」可能是别的文件贡献的，
   **一个永远不响的门禁照样会「通过」**。现在 `run_case_single()` 会直接抛错拦住。

**局部验证做不到的事**：这两个问题**都不可能靠本机复现**。
唯一有效的验证是「在没有 `local/` 的树上跑一遍」—— 已用 `mv local /tmp_local_bak`
模拟过（结果 `4 个配置文件 + 10 份台账/扫查，0 ERROR`，与 CI 同形）。

**门禁**：无（约束的是工具的路径选择；由 `tools/negtest.py` 的 `_is_scan_target()` 断言
与 `check-all.sh` 的环境无关性承载）

**涉及**：`tools/audit.py` 的 `audit_matrix_paths()`（`tempfile`）、`tools/negtest.py` 的
`run_case_single()` / `_is_scan_target()`

---
---

## 附：怎么加一条新教训

1. 在 `tools/audit.py` 里把能拦住这次事故的**门禁 code** 实现出来（不能只写文档）。
2. 在本文件追加 `## L<n> <标题>` 条目（**二级标题**；L6 是历史空号，新条目继续往后编）。
3. 正文必须含五个小标题，`audit_lessons()` 会逐条校验缺哪个：
   `**现象**`（早期条目写 `**现象/风险**` 也可以）/ `**根因**`（带源码路径）/
   `**为什么没被拦住**` / `**修法**` / `**门禁**：`（全角冒号、加粗，行首开始）。
4. 在 `**门禁**：` 行里写上第 1 步的 code（反引号包裹）；这条教训没有对应门禁就写「无」，
   **但必须写这一行**，否则报 `lesson_missing_gate_line`。
5. `python tools/audit.py` 应当能过 —— `audit_lessons()` 会替你检查两边对得上。
6. 跑负向回归：把用例登记进 **`tools/negtest.py`** 的 `CASES`（不要临时现写脚本、跑完就删 ——
   那是七条改造第 7 条要消除的浪费，也是「门禁可能是死的」没被发现的原因，见 L37）。
   先确认它 ❌（新门禁还没实现时），实现后再确认 ✅。
7. `bash tools/check-all.sh` 应当能过 —— 它把「静态门禁 + 负向回归 + 逐份 `sing-box check`」
   串成一条命令，任一步失败都会在汇总里点名。
8. 要改**任何**文件时用 `python tools/patch-text.py spec.json`，不要临时写 heredoc/python 重写文件
   —— 原子写 + 唯一锚点 + 不经 shell，三条各对应一次真实事故（L40）。
