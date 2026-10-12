# WORKFLOW.md — 完整工作流

> 本文件说明「怎么用这套仓库」和「怎么维护这套仓库」。给 AI 的下手顺序见根目录 `AGENTS.md`，
> 分享链接怎么翻译成 outbound 见 `docs/PROTOCOL-MAPPING.md`。

## 零、这套仓库要解决什么问题

sing-box 迭代快，字段会**改名、合并、废弃、移除**，而且：

- 未知字段 → `FATAL ... json: unknown field` → 配置起不来
- 已移除字段 → `FATAL ... deprecated in X and removed in Y` → 配置起不来
- **已废弃但未移除** → 很多字段 `sing-box check` **完全静默**（典型：`download_detour`）
- **平台差异** → `check` 完全不校验（iOS 写 `strict_route` 照样 exit=0，但没效果）

所以只靠"让 AI 背文档"必然出错。本仓库把这四类知识**固化成可执行的检查**：

| 风险 | 兜底手段 |
|---|---|
| 未知字段 / 已移除字段 | `sing-box check`（内核自己报） |
| 已废弃未移除字段 | `docs/version-matrix.json` + `tools/audit.py` |
| 平台能力差异 | `docs/PLATFORM-MATRIX.md` + `tools/audit.py` |
| 引用完整性（出站/规则集/DNS server 不存在） | `tools/audit.py`（`check` 不校验！） |
| 规则集**顺序**（放行/拦截/分流先后错了等于没加） | `tools/audit.py` 的 Jinx 顺序检查 |
| **tun 出口回灌**（能启动但没网，`check` 全静默） | `tools/audit.py` 的 `tun_without_auto_detect_interface` 门禁 |
| 上游又改了 | `tools/upgrade-check.py` |

## 一、目录职责

```
singbox_version.txt        当前锁定的正式版（唯一真相）
AGENTS.md                  AI 入口与铁律
README.md                  人类入口
docs/PROTOCOL-MAPPING.md   分享链接 → outbound 字段映射（核心知识）
docs/PLATFORM-MATRIX.md    三平台能力差异
docs/version-matrix.json   机器可读字段生命周期（audit.py 的依据）
docs/VERSION-MATRIX.md     上表的人读版（由 tools/gen-docs.py 生成）
docs/schema.json           sing-box 官方 schema（字段白名单）
docs/upstream-*.md         上游 deprecated / migration / changelog / tun 的本地快照
profiles/<大版本>/          可运行配置（**占位节点**），按平台分文件
local/                      【不提交】本机真实节点配置（.gitignore 已忽略，仅存本地）
nodes/nodes.example.json   用户节点在该仓库里的书写示例
templates/                 片段骨架（节点、分流组）
tools/audit.py             门禁
tools/upgrade-check.py     升级巡检
tools/gen-docs.py          由 JSON 生成人读版矩阵
archive/                   旧大版本配置归档
docs/LESSONS.md            事故台账（每条教训 → 对应门禁 code，双向可追溯）
```

## 一bis、开工前必做：读事故台账

**每次生成或修改配置之前，先扫一遍 [`docs/LESSONS.md`](LESSONS.md)。**
台账里逐条记了历史上真机上出过的事故（包括用户报的完整报错原文）、源码级根因、
以及对应的门禁 code。那些坑都是真金白银踩出来的，不要重踩。

台账与门禁**双向绑定**，`python tools/audit.py` 每次都会校验：

- 台账里声明的门禁 code 必须在 `tools/audit.py` 里真实实现（`lessons_missing_gate`）
- 代码里每个非框架门禁 code 必须在某个文档里有出处（`gate_without_lesson`）

所以“文档声称有防护、代码里没有”和“新加了门禁没人知道它拦什么”这两类问题都会被拦住。

**为什么 `profiles/` 按大版本分目录**：1.14 的配置在 1.15 上可能直接 `FATAL`（例如 1.17 移除
`stack` 后就起不来）。按大版本分目录后，升级＝新开一个目录，旧配置原地保留、随时可回退。

## 二、流程 A：用户给节点 → 出配置（最高频）

### A0. 产物落哪里（先看这条，别搞错）

| 产物 | 位置 | 是否提交 |
|---|---|---|
| 只含占位节点的骨架 | `profiles/<ver>/<platform>-lazy.json` | ✅ 提交 |
| **含真实节点的成品** | `local/<platform>.json` | ❌ **永不提交** |
| 给用户下载的成品 | 仓库外任意位置（如桌面 `android-lazy-test.json`） | ❌ 不提交 |

**铁律：任何时候仓库都不放真实节点，含真实节点的文件仅存留本地。**

- `local/` 已写进 `.gitignore`，`git status` 看不到它。
- `tools/audit.py` 内置 `placeholder_server` 检查：只要 `profiles/` 下出现非 `.example.com`
  这类占位域名的 `server`，直接报 ERROR。所以"不小心把真实节点写进 profiles"会在门禁那步被挡住。
- 提交前可再自查一遍：`git status` 应只有 `profiles/` / `docs/` / `tools/` 等预期改动。

### A0bis. 改用户给的现成配置时：先做字段差异比对

如果用户不是“从零给链接”，而是给了一份**已有配置**让你改（哪怕只改一个字段），
**必做字段差异比对**，并把每一个差异都说得出理由。

这么做是因为真的犯过（`docs/LESSONS.md` 的 **L4**）：我凭印象重写模板，
把用户原始配置里本来就有的 `auto_detect_interface: true` 删了，直接导致真机没网。

脚本见 `AGENTS.md` 第 0.1 节。要点：逐叶子节点比对，
`只在原始配置里（可能被我删了）` 和 `只在生成配置里（可能是我加的）` 都必须逐条解释。

### A1. 收集输入

需要用户提供：

1. **节点分享链接**（可多个）：`vless://…` `vmess://…` `trojan://…` `hysteria2://…` `ss://…` …
2. **落点分流组**：`Proxy`（普通外网）、`AI`（AI 类网站走更干净的出口）、`AD`（广告拦截）
3. **目标平台**：Android / iOS / Windows
4. （可选）**AI 组是否要单独指定节点**（默认跟随 `Proxy` 这个 urltest 优选）

缺哪个就问，不要自己猜。用户只说"A 放 AI 组"，那就只动 AI 组。

### A2. 查版本

```bash
cat singbox_version.txt          # 例如 1.14.3   2026-10-12
```

配置必须能在这个版本上跑起来。如果用户客户端版本比这个低，先让用户升级客户端
（正式版之间也可能有字段移除，例如 1.13 → 1.14 移除了 legacy DNS server 格式）。

### A3. 翻译链接

打开 `docs/PROTOCOL-MAPPING.md`，找到对应协议的小节，逐字段抄。

三条最容易出错的：

- **`vmess://` 后面是 base64**，解出来是 JSON；字段名是 v2rayN 的（`scy` `aid` `net` `type`），
  sing-box 的字段名不一样（`security` `alter_id` `transport.type`）。
- **`ss://` 有两种形态**：`ss://base64(method:password)@host:port#tag` 和
  `ss://base64(method:password@host:port)#tag`。都要能识别。
- **`hysteria2://` 的 `user:pass` 里 user 部分官方客户端会忽略**，整串 `user:pass` 可能都被
  当成密码。以客户端实际发的为准，拿不准就问用户。

### A4. 落地到配置

从 `profiles/<版本>/<平台>-lazy.json` 拿骨架（**不要新写一份配置**），然后：

1. 在 `outbounds[]` 末尾追加节点对象，`tag` 用「节点名-地区-协议」这种可读名，
   且**不得与既有 tag 重复**（`Proxy` `AI` `AD` `direct` `block` 是保留名；`Proxy` 是 urltest 组，节点更不能占用）。
2. 把新 tag 加进目标分流组的 `outbounds` 数组。
   `Proxy` 本身就是 urltest，加进去即自动测速——**不再有单独的 Auto 组**；
   `AI` 默认指向 `Proxy`，用户没特别要求就不用单独加节点。
3. **不要动** `route.rules`、`dns`、`inbounds`、`rule_set`，除非用户另外要求。
   其中规则集与规则顺序是**固定骨架**（见 `AGENTS.md` 的「固定规则集清单」）：
   `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`，少一个、换个位置都不行。
4. `AD` 分组**只允许** `block` 和 `direct`，永远不要把代理节点放进去。

### A5. 跑门禁

```bash
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
```

`audit.py` 会自己找 `sing-box`，也可以显式指定：

```bash
python tools/audit.py --singbox "C:/path/to/sing-box.exe" profiles/1.14/ios-lazy.json --platform ios
# 或设环境变量
export SINGBOX_BIN=/path/to/sing-box
```

要求：**0 ERROR**。有 ERROR 不许交付。WARN 要看清是什么，并写进给用户的说明里。

### A6. 交付

回复里必须写清：

- 目标 **sing-box 正式版号**
- 目标 **平台**
- 每个新节点**落在哪个组**
- audit 结论（`sing-box check` 是否通过、有没有 WARN）
- **完整 JSON**（能直接复制粘贴的那种，不要只给 diff）
- 一句提醒：配置里的占位域名（`node-01.example.com`）必须已被替换成真实地址；
  含真实节点的成品放 `local/`，**不要提交进仓库**
- ⚠️ **不得声称“实测能上网”**（铁律 11）：本机环境不可信，`check` / `--run` 只证明能启动。
  真机联网结论只能由用户给出。若上次交付后用户报了新问题，修完追加一条 `docs/LESSONS.md` 条目。

## 三、流程 B：上游发布新正式版

### B1. 巡检

```bash
python tools/upgrade-check.py
```

报告包含：最新正式版号、文档快照差异、矩阵对账、升级风险、受影响配置。

### B2. 判断跨度

- **补丁版（1.14.2 → 1.14.3）**：通常只是修 bug，配置一般不用改。仍要跑一遍报告。
- **小版本（1.14 → 1.15）**：一定有废弃项。**必须**逐条处理。
- **跨多个小版本**：按版本顺序逐段处理 `docs/upstream-deprecated.md`。

### B3. 处理废弃项

对报告里每一条：

1. 找到官方原文（`docs/upstream-deprecated.md` 对应段 + 链接的 migration 锚点）
2. 在 `docs/version-matrix.json` 的 `entries[]` 里补一条，字段含义：

```json
{
  "id": "唯一标识",
  "kind": "deprecated | removed | platform | semantic | info",
  "deprecated_in": "1.15.0",
  "removed_in": "1.17.0",
  "path": "inbounds[type=tun].stack",
  "replacement": "改成什么",
  "doc": "官方链接",
  "note": "补充说明"
}
```

`path` 语法（`audit.py` 用的）：

| 写法 | 含义 |
|---|---|
| `route.rule_set[].download_detour` | 数组任意元素 |
| `inbounds[type=tun].stack` | 数组里 `type == "tun"` 的元素 |
| `**.tls.acme` | 任意深度下匹配 |
| `dns.rules[].ip_cidr` | 同上 |

若字段是"某类出站"整体移除（如 `type: wireguard`），用：

```json
"type_check": { "where": "outbounds", "field": "type", "equals": "wireguard" }
```

3. 如果废弃项有前提条件，用 `require_present` / `require_absent` 限定，例如
   "只有 DNS 规则带 `action` 时 `strategy` 才算废弃"：

```json
"path": "dns.rules[].strategy",
"require_present": ["action"]
```

### B4. 改配置

```bash
cp -r profiles/1.14 profiles/1.15
# 在 profiles/1.15/ 里逐项删除/替换已废弃字段
python tools/audit.py --version 1.15.0 profiles/1.15/*.json
```

`--version` 参数就是"假设我在这个版本上跑"——用它可以**提前**发现"升到新版会炸什么"。

### B5. 收尾

```bash
python tools/gen-docs.py          # 重新生成人读版矩阵
python tools/audit.py             # 全仓库配置体检
# 全部 0 ERROR 后：
echo "1.15.0  checked 2026-xx-xx" > singbox_version.txt
python tools/upgrade-check.py --write    # 更新上游文档快照
```

## 四、流程 C：用户反馈"跑不起来"

按报错形态分流：

| 报错 | 原因 | 处理 |
|---|---|---|
| `FATAL ... json: unknown field "xxx"` | 字段名写错，或该版本没有这个字段 | 查 `docs/schema.json` 是否有该字段；查 `docs/VERSION-MATRIX.md` 是否已改名 |
| `FATAL ... deprecated in X and removed in Y` | 用了已移除字段 | 查 `docs/VERSION-MATRIX.md` 的替代写法 |
| `FATAL ... decode config at` 后面跟着具体路径 | 类型/枚举值不对 | 看错误里指出的路径 |
| `FATAL ... initialize outbound[n]: invalid public_key / illegal base64` | 密钥格式不对 | reality public_key 必须是合法 base64url；SS 2022 密码必须是合法 base64 |
| `FATAL ... http_client is conflict with deprecated download_detour field` | 两者同时出现 | 删掉 `download_detour` |
| `FATAL ... detour to an empty direct outbound makes no sense` | **下载用的 direct 出站是空的**：只写了 `{"type":"direct","tag":"direct"}` | 给下载专用 direct（tag 固定为 `direct-download`）加 `domain_resolver`，或 `bind_interface` / `inet4_bind_address` / `routing_mark` 等任意一项。**注意：`domain_strategy` / `network_strategy` 已被 `schema:"omit"`，填了也不起作用、仍算空** |
| 启动成功但某类流量走错 | 平台能力 / 规则顺序 | 查 `docs/PLATFORM-MATRIX.md`、检查 `route.rules` 顺序 |
| **启动成功、但完全没网**：节点全无延迟、只有上传没下载、连接数上万、内存飙到 1GB | 缺 `route.auto_detect_interface: true`：出站 socket 没被 `protect()`，回灌 tun | 在 `route` 里加 `"auto_detect_interface": true`（Android 上唯一可行的防回环手段）。`audit.py` 会报 `tun_without_auto_detect_interface` |
| 崩溃/无日志 | 工作目录问题 | Android 看 `$working_directory/stderr.log`；Windows 看 `C:\ProgramData\sing-box-daemon` |

### ⚠️ 最重要的一条：`check` 过了不代表启动得了

**`sing-box check` 只做反序列化，不做任何初始化。**下面这类错它**一律 exit=0、一句话不说**：

- 空的 direct 出站（`detour to an empty direct outbound makes no sense`）
- 规则集 / DNS 服务器 / 出站在**初始化期**才会暴露的引用与资源问题
- 规则集 URL 实际下不下来（要等真去 Get 那一刻）

判定机制（源码级）：`protocol/direct/outbound.go` 里
`isEmpty = reflect.DeepEqual(options.DialerOptions, option.DialerOptions{AbstractDialerOptions{UDPFragmentDefault: true}})`——
即整个 dialer 选项块一个非默认字段都没有就是“空”。`common/dialer/detour.go` 的 `init()`
在 `!defaultOutbound && !disableEmptyDirectCheck` 时对 `IsEmpty()` 的 direct 直接报错。

**所以仓库的门禁必须真跑一次**：

```bash
# 会真的连网拉规则集，故不放进默认；发布前/排错时必跑
python tools/audit.py --run --run-seconds 20
```

`--run` 会自己把 tun 入站临时替成 `mixed`（避免 Windows 建假网卡），把 `cache_file.path` 指到临时目录，
跑 20 秒后主动终止，只看输出里有没有 `FATAL`。CI 里已经默认带上这一步。

### ⚠️ 第二重要的一条：能启动、也不报错，但就是没网

`route.auto_detect_interface` 缺失属于**第三层问题**：静态结构对、`check` EXIT=0、`run` 也能活着，
但手机上一用就废。症状固定好认：

- 首页/仪表盘显示内存占用瞬间 1GB
- 瞬间爆出上万个入站与出站请求
- 所有节点都测不出延迟（等于全不可用）
- 只有上传流量，没有下载流量

机制（源码 `common/dialer/default.go` 的 `NewDefault`）：

```
if defaultOptions.BindInterface != "" && !disableDefaultBind { ... }
else if networkManager.AutoDetectInterface() && !disableDefaultBind {
    if platformInterface != nil && platformInterface.UsePlatformNetworkInterfaces() {
        bindFunc := networkManager.ProtectFunc()        // Android: VpnService.protect(fd)
        dialer.Control = control.Append(dialer.Control, bindFunc)
        listener.Control = control.Append(listener.Control, bindFunc)
    }
}
```

`networkManager.AutoDetectInterface()` 直接返回 `route.auto_detect_interface` 的值。没写 ⇒ 整个分支不成立 ⇒
出站 socket **一个 Control 也不挂** ⇒ Android VpnService 把本 App 自己的流量也抓进隧道
（`Settings.allowBypass` 默认 `false`）⇒ 出站回灌 tun：

```
设节点 → 回灌 tun → 命中规则 → 又设节点 → ……
```

官方原文（`docs/configuration/inbound/tun.md`）：

> To avoid traffic loopback, set `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`

三个手段在 Android 图形客户端上只有第一个可行：`default_interface` 需要真实网卡名、
`bind_interface` 同样；而且 `route/network.go` 的 `NetworkManager` 在图形客户端走的是
`ProtectFunc()`（`experimental/libbox/service.go` 的 `UsePlatformNetworkInterfaces()` 恒 `true`），
不是桌面那套网卡绑定。官方 `docs/manual/proxy/client.md` 三份客户端示例也都写了
`"auto_detect_interface": true`。

**为什么 `check` 抓不到**：`check` 只反序列化，不跑 `NetworkManager.Start()`，也不调 `NewDefault`。
所以只能在 `audit.py` 里做静态门禁（`tun_without_auto_detect_interface`）：
有 tun 入站且既没有 `route.auto_detect_interface` 也没有 `route.default_interface`
也没有全部出站的 `bind_interface` 时，直接 ERROR。

### ⛔ 铁律：不在本机乱试

本机（Windows）挂着 OpenClash 网关，DNS 会被网关劫持——实测过：一份**完全不含 fakeip 配置**的
最小配置查 `testingcf.jsdelivr.net`，`223.5.5.5` 仍返回 `198.18.0.70`（fakeip 网段）。

所以：

- **在本机跑出来的"能上网 / 不能上网"结论一律作废**，不能写进交付说明
- `sing-box check` 与 `audit.py --run` 只用来验「能不能启动」，**不准用来验「能不能上网」**
- 排查问题只允许三种手段：**读配置、读官方文档、读 sing-box 源码**
- 真机结论只能由用户在真机上给出

**修完必须回写**：把这次踩坑补进 `docs/PROTOCOL-MAPPING.md` 的"常见解码坑"表，
或 `docs/version-matrix.json`。否则下次还会踩。

## 五、维护这张表的规矩

1. **`docs/version-matrix.json` 是唯一真相**，`docs/VERSION-MATRIX.md` 由它生成。
2. 每条 `removed_in` 必须能在 `docs/upstream-deprecated.md` 里找到原文。
3. 不确定"什么时候移除"的，`removed_in` 留空或写 `null`，别猜。
4. 每条都要有 `doc` 链接。
5. 改完必须 `python tools/audit.py` 全绿才算完。

## 六、常见误区

| 误区 | 事实 |
|---|---|
| "`sing-box check` 过了就没问题" | 错，而且错得很危险。`check` **只反序列化、不初始化**：空 direct 出站、规则集下不下来、`download_detour` 这类废弃字段，它全都不吭声。发布前必须 `audit.py --run` |
| "`direct` 出站就是个直连，不用写别的" | 裸的 `{"type":"direct","tag":"direct"}` 是**空 direct**，不能当规则集下载的 detour。下载专用出站固定叫 `direct-download`，必须带 `domain_resolver` |
| "给 direct 加 `domain_strategy: ipv4_only` 就不算空了" | 错。`domain_strategy` 已废弃并被 `schema:"omit"`，**填了也不算数**；而且 1.14 下直接触发 legacy domain strategy 的 FATAL。真正算数的是 `domain_resolver` / `bind_interface` / `inet4_bind_address` / `routing_mark` 等 |
| "字段没了内核会提示" | 未知字段/已移除字段会，**已废弃未移除的常常不会** |
| "iOS 和 Windows 配置可以通用" | 大部分可以，但 `strict_route`、`clash_api`、TUN 地址这些要分开 |
| "规则集用 GitHub raw 就行" | 国内经常打不开，必须走 jsdelivr CDN，且配置里显式指定下载用的 `http_client` |
| "广告用 `category-ads-all` 就够了" | 本仓库用 Jinx (`jinx-ads`) + 秋风 (`awanue-ads`)，且**必须**配 `jinx-direct` 放行集，顺序 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| "规则顺序无所谓" | 顺序错了等于没加。`geosite-cn` 排在拦截之前，国内广告域名会先命中直连，广告规则再无机会执行 |
| "`cache_file.path` 可以写 `../cache/cache.db`" | sing-box **不会**自动建父目录，父目录不存在直接 `FATAL` 起不来。写 `cache.db` |
| "分流组越多越好" | 本仓库只要 `Proxy` / `AI` / `AD` 三个 + `direct` / `block` |
