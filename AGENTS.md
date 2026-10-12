# AGENTS.md — sing-box 配置生成工作流（AI 入口）

> 本文件是**给 AI 读的入口**。任何人（或任何 AI）拿到本仓库后，按本文流程即可根据用户提供的
> 节点分享链接，生成**当前 sing-box 正式版可实际运行**的 Android / iOS / Windows 配置。

## 0. 一句话任务

用户只给**节点分享链接**（`vmess://` `vless://` `trojan://` `hysteria2://` `ss://` `anytls://` …）
和**想要的落点**（Proxy / AI / AD 三个分流组之一），你负责：

0. **先读 `docs/LESSONS.md`（事故台账）** —— 里面逐条记录了历史上真机上出过的事故、
   根因、以及对应的门禁 code。开工前扫一遍，别重犯。
1. 查证**当前正式版**是什么版本、有哪些字段已废弃/已移除 → `singbox_version.txt` + `docs/VERSION-MATRIX.md`
2. 用 `docs/PROTOCOL-MAPPING.md` 把分享链接翻译成 `outbounds[]` 里的一个节点对象
3. 把该节点塞进用户指定的分流组的 `outbounds` 列表
4. 用 `tools/audit.py` 跑一遍门禁（含 `sing-box check`）
5. 输出**平台对应**的完整 JSON 给用户

**不要凭记忆写字段。** 每个字段都必须能在 `docs/PROTOCOL-MAPPING.md` 或 schema 里查到。

### 0.1 铁律 0：给用户改配置前，先做字段差异比对

如果用户给了一份**已有的配置**，让你改（不管改多小），**必做**：

```bash
python tools/diff_config.py 用户原始配置.json 我改完的配置.json
```

输出三段：`只在原始配置里（可能被我删了）`、`只在生成配置里（可能是我加的）`、
`两边都有但值变了`。**每一个差异都必须能说出为什么**。说不出原因的，就按原始配置保留。
这条是拿真实事故换来的（见 `docs/LESSONS.md` 的 **L4**）：我当初凭印象重写模板，
把用户原始配置里本来就有的 `auto_detect_interface: true` 删了，直接导致真机没网。

## 1. 硬性铁律

| # | 铁律 |
|---|------|
| 1 | **只面向正式版**。现行正式版记在仓库根 `singbox_version.txt`；不用 `-alpha` / `-beta` / `-rc` 字段去写配置 |
| 2 | **未知字段 = 致命错误**。sing-box 对未知字段直接 `FATAL ... json: unknown field`，启动失败 |
| 3 | **已移除字段 = 致命错误**。见 `docs/VERSION-MATRIX.md` 的"已移除"列 |
| 4 | **`check` 通过 ≠ 配置正确**。`check` 对"已废弃但未移除"的字段可能完全静默（例如 `download_detour`），也不校验平台能力、不校验规则集顺序。必须同时过 `docs/VERSION-MATRIX.md` 和 `docs/PLATFORM-MATRIX.md` |
| 5 | **平台能力不同**。iOS/Android 不支持 `strict_route`；Android 无 `process_name` 权限等。见 `docs/PLATFORM-MATRIX.md` |
| 6 | **分流组只有三个**：`Proxy`（默认代理，**本身就是 urltest**）、`AI`（**也是 urltest**，独立优选）、`AD`；再加 `direct` 与 `block` 两个出站。**`Proxy` 与 `AI` 的 `outbounds` 里只放真实节点，不要嵌套组**（不引用 `Proxy`）。国内/私有/广告**不出组**，用规则直连或落 AD |
| 7 | **任何时候、任何文件都不放真实节点**。`profiles/` 下只允许占位域名（`node-01.example.com`）；含真实凭据的配置一律写进仓库外的 `local/`（已在 `.gitignore`），**仅存本地，永不提交、永不推送**。<br>⚠️ **范围是整个被跟踪仓库，不只是 `profiles/`** —— `docs/` 里的散文同样是公开的。写证据/台账时禁止出现节点域名、节点 IP、密码（发生过一次：L18 的证据文档写了“实测”，却把节点域名与它的 A/AAAA 一起写进了公开仓库）。<br>`audit.py` 有三道兜底：`placeholder_server`（`profiles/` 的 server 字段）、`sensitive_ip_in_repo`（全仓库未审阅公网 IP）、`redaction_clean`（无命中时的通过记录） |
| 8 | **规则集走 CDN**，不用 `raw.githubusercontent.com`。CDN 前缀统一 `https://testingcf.jsdelivr.net/gh/`（也可用 `cdn.` / `fastly.` / `gcore.` 镜像） |
| 9 | **广告规则集用 Jinx**，不用 `MetaCubeX` 的 `category-ads-all`。拦截集 = `jinx-ads` + `awanue-ads`；这两个**必须**先跟 `jinx-direct` 放行集，且顺序为 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| 10 | **旧版本配置只归档不删除**（`archive/<大版本>/`） |
| 11 | **不在本机乱试**。本机有 OpenClash 网关，在本机跑 `sing-box run` 得到的连通性结论**一律不可信**（DNS 会被网关劫持，实测过：不含 fakeip 的最小配置也会被返回 `198.18.0.x`）。排查问题只允许三种手段：读配置、读官方文档、读 sing-box 源码。`sing-box check` 与 `audit.py --run` 只用来验「能不能启动」，**不准用来验「能不能上网」**。<br>**唯一例外（允许且推荐）**：用 `log.level = debug` 读 **sing-box 自己的日志**来判断「本机往出站递了什么」——`router: resolved [...]` 与 `outbound connection to <目标>` 是本机产生的记录，不受网关劫持影响（能据此区分「目标是 IP 字面量」还是「目标是域名」）。证据须存档到 `docs/evidence/` |
| 12 | **tun + auto_route 必须写 `route.auto_detect_interface: true`**。不写 ⇒ `common/dialer/default.go` 不会挂 protect/绑定网卡 ⇒ 出站 socket 回灌 tun ⇒ 表现为「能启动但没网、节点全无延迟、只有上传没下载、连接数暴涨、内存飙升」。`audit.py` 有 `tun_without_auto_detect_interface` 门禁兜底 |
| 13 | **日志里出现 `using outbound/selector[AD]: operation not permitted` 是正常的**，不是 AD 组出错：`protocol/block/outbound.go` 就是用 `syscall.EPERM` 表示“拦住”，日志名取的是本连接选中的那层出站（AD selector → block）。**不要因此去“修” AD 组**（那会把广告放行）。嫌刷屏就 `log.level: "panic"`。反过来说：**AD 组的 `default` 必须始终是 `"block"`**，被改成 `direct` 会让所有广告静默放行 —— `audit.py` 有 `ad_group_default_not_block` 门禁兜底 |
| 14 | **「只走 IPv4」必须端到端**。`dns.strategy: "ipv4_only"` 只管本地 DNS；目标域名默认是**原样交给代理服务端**的。必须在 `route.rules` 里加 `{"action": "resolve", "strategy": "ipv4_only"}`，**位置紧跟 `hijack-dns` 之后、排在所有 `route`/`reject`/`bypass` 之前**（放末尾等于没放 —— 首个 route/reject 命中即 `break match`，见 L18）。`route/conn.go:103-104` 见 `DestinationAddresses` 非空就走 `DialSerialNetwork`，目标变成 IPv4 字面量。`strategy` 不要省。`audit.py` 有 `resolve_not_ipv4_only` / `resolve_missing_ipv4_only` / `resolve_not_first` 门禁兜底 |
| 15 | **出口 IP 的地址族不由客户端决定**。`resolve` 只能保证「本地 → 服务端」这一段是 IPv4 字面量（日志可证）；「服务端 → 目标站」那一段完全由服务端决定（NAT64、服务端 `sniff` 后自行重解析域名等）。⇒ 看到 IPv6 出口时**不要在本机配置里找原因、更不要为了它继续加固本地**，先确认该地址是不是节点本身的 AAAA 记录；要改就去服务端禁用 IPv6 出网。**已证实**：本地已全 IPv4 仍出现 VPS 自身 AAAA 出口；**未证实**：服务端为何在某些时段选 IPv6、禁用 IPv6 是否就能解决（属建议，未在真实 VPS 验证）。详见 `docs/evidence/2026-10-12-resolve-ipv4-vs-vps-egress.md` |
| 16 | **上游新增功能必须显式写下「启用 / 不启用 / 必须跟随」**。上游发新版本时，除了「哪些字段要删」（`deprecated`/`removed`），还有「多了哪些新能力」——后者**没有默认答案**，不写就是隐式选择了“不启用”，理由往往是“没注意到”。⇒ 每个新功能在 `docs/version-matrix.json` 里建一条 `kind: "new"`（必填 `adopt` + `reason`，有字段可检测的还要 `expect`），并在 `docs/DECISIONS.md` 记下理由与备选方案。`audit.py` 有 `new_feature_without_adoption` / `new_feature_expect_invalid` / `new_feature_decision_overdue` / `new_feature_uncovered` / `decision_without_record` 门禁兜底 |
| 17 | **改配置、改流程都先拉仓库、先看 diff**。走到新环境时先 `git clone`（或 `git pull`），在本地产出改动后：**先 `git diff` 给人看、得到同意、才 `commit` / `push`**。**不得直接覆盖已有文件** —— 历史上有过“把已更正过的文档又改回错误结论”的先例（L17 写反 → L18 推翻）。**克隆拿不到 `local/`**（已 `.gitignore`），真实节点只能由用户当场提供（铁律 7） |

### 固定规则集清单（不要自行改动）

| tag | 用途 | 格式 | 来源 | update_interval |
|---|---|---|---|---|
| `jinx-direct` | 白名单放行（47 条，包含被国内大厂 SDK 误拦的合法域名） | `source` | `RiverFlowsInUUU/Jinx@main/sing-box-direct.json` | `1d` |
| `jinx-ads` | 广告拦截（3901 条） | `source` | `RiverFlowsInUUU/Jinx@main/sing-box-ads.json` | `1d` |
| `awanue-ads` | 广告拦截补充（秋风规则，965 条） | `source` | `TG-Twilight/AWAvenue-Ads-Rule@main/Filters/AWAvenue-Ads-Rule-Singbox.json` | `1d` |
| `geosite-private` | 局域网/私有域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geosite-ai` | AI 服务域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geosite-cn` | 中国大陆域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geoip-cn` | 中国大陆 IP | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |

全部 URL 前缀统一 `https://testingcf.jsdelivr.net/gh/`，全部带 `"http_client": "ruleset-dl"`。

**顺序铁律**（Jinx 官方要求，实测验证过为什么）：

```
jinx-direct     → outbound direct      ✅ 白名单放行，必须最先
jinx-ads        → outbound AD          🚫 拦截
awanue-ads      → outbound AD          🚫 拦截（必须排在 jinx-ads 之后）
geosite-cn      → outbound direct      🚦 常规分流，必须在拦截之后
```

原因：国内广告域名多数同时也属「中国大陆域名」。`geosite-cn` 若排到拦截之前会先命中放行，广告规则再无机会执行。
秋风（`awanue-ads`）与 Jinx 判定标准不同，**会拦掉 Jinx 白名单里的 8 个域**，所以必须排在 Jinx 之后，
且前面要有 `jinx-direct` 兵底。

## 2. 仓库结构

```
AGENTS.md                     ← 你在读的文件（AI 入口）
README.md                     ← 人类入口
singbox_version.txt           ← 当前正式版号 + 核查日期（唯一的版本真相）
docs/
  LESSONS.md                  ← 【开工先读】事故台账：现象 / 根因 / 为什么没拦住 / 修法 / 对应门禁
  DECISIONS.md                ← 【开工先读】决策记录：新功能为何启用/不启用、备选方案、前提风险
  WORKFLOW.md                 ← 完整工作流（升级流程 / 生成流程 / 校验流程 / 排障）
  PROTOCOL-MAPPING.md         ← 【核心】分享链接 → outbound 字段映射表
  VERSION-MATRIX.md           ← 逐版本废弃/移除字段总表（由 version-matrix.json 生成，勿手改）
  version-matrix.json         ← 同上，机器可读（audit.py 的依据）
  PLATFORM-MATRIX.md          ← Android / iOS / Windows 能力差异表
  schema.json                 ← sing-box 官方 schema（字段白名单）
  upstream-*.md               ← 上游 deprecated / migration / changelog / tun 快照
profiles/1.14/                ← 按内核大版本归档的可运行配置（占位节点）
  desktop-lazy.json
  android-lazy.json
  ios-lazy.json
templates/groups.json         ← 固定分流组骨架（Proxy / AI / AD / direct / block）
nodes/nodes.example.json      ← 节点书写格式与分享链接对照示例
tools/
  audit.py                    ← 门禁：结构 + 废弃字段 + 平台能力 + 引用完整性 + 防回灌 + 教训台账一致性 + sing-box check
  upgrade-check.py            ← 上游有新正式版/新废弃项时报告差异
  gen-docs.py                 ← 由 version-matrix.json 生成 VERSION-MATRIX.md
archive/<大版本>/             ← 旧版本配置归档（只归档不删除）
local/                        ← 【不提交】本机真实节点配置（.gitignore 已忽略）
```

## 3. 三种典型任务

### 任务 A：用户给节点 → 出配置

```
1. cat singbox_version.txt                       # 确认目标正式版
2. 读 docs/PROTOCOL-MAPPING.md 对应协议小节      # 拿到字段清单
3. 读 profiles/<ver>/{platform}-lazy.json        # 拿骨架
4. 按映射表把链接解成 outbound，插到出站列表
   —— ⚠️ 若用户给了一份已有配置让你改，**先做字段差异比对**（见 §0.1 铁律 0）
5. 把 outbound tag 加进用户指定的分流组（Proxy / AI / AD）的 outbounds 数组
   —— `Proxy` 与 `AI` **都是 urltest 组**，节点直接加进去就是加进自动测速（不再有单独的 `Auto` 组）；
      `AI` 只放用户指定给 AI 的节点，**默认不要引用 `Proxy`**
6. python tools/audit.py profiles/<ver>/<platform>-lazy.json --platform <p>
7. 输出完整 JSON（不是 diff、不是片段）

**产物落哪里**（关键）：
- 只含占位节点的骨架 → `profiles/<ver>/<platform>-lazy.json`
- **含真实节点的成品 → `local/<platform>.json`，绝不写进 `profiles/`，绝不提交**
- 给用户的成品可以放在仓库外任意位置（例如 `android-lazy-test.json`）再发送
```

### 任务 B：上游发布新正式版

```
1. python tools/upgrade-check.py                 # 看报告：1 版本比对 2 文档 diff 3 矩阵对账 4 升级风险 5 新功能清点
2a. 【旧字段部分】按报告第 3/4 节改 docs/version-matrix.json（kind=deprecated/removed/…）
2b. 【新功能部分】按报告第 5 节出「升级清单」，三栏分类：
    · 必须跟随（旧写法被取代，必须删旧字段）—— 如 1.15 的 tun.stack
    · 必须决策（新能力，启用/不启用由用户拍板）—— 如 MASQUE / Tailcat / auto_redirect
    · 可放着（纯内部更新或与场景无关）—— 也要记一笔，否则下次会被当成漏项反复报警
    ⚠️ 这三栏**必须逐条给用户看、等用户拍板**，不得自行决定（铁律 16）
2c. 用户拍板后，写两个地方：矩阵 entries[] 加 kind="new" 条目（机器依据，
    含 adopt / reason / since / decide_by / keywords）；
    docs/DECISIONS.md 加 D<n> 条目（人的理由，含备选方案与前提风险）
3. python tools/gen-docs.py                      # 重新生成 VERSION-MATRIX.md
4. cp -r profiles/<旧ver> profiles/<新ver>，按报告逐项修正
5. python tools/audit.py --version <新ver> profiles/<新ver>/*.json
6. 更新 singbox_version.txt；确认无误后 upgrade-check.py --write 刷新文档快照
```

> ⚠️ 流程 B 改流程本身时，四个文件必须同步（见 `docs/LESSONS.md` L22）：
> `AGENTS.md`（本文）/ `README.md` / `docs/WORKFLOW.md` / `docs/DECISIONS.md`。

### 需用户同意的六个动作（铁律 17 的具体清单）

以下六件事**每次都必须先说、得到同意才做**，不在这六条内的可直接执行：

| # | 动作 | 为什么需要同意 |
|---|---|---|
| 1 | `git commit` | 落盘即进入历史 |
| 2 | `git push` | 一旦推到公开仓库就**收不回来**（`ec5d300` 泄漏节点信息就是靠 force-push 补的，且旧 commit 仍可按 SHA 取到） |
| 3 | 改 `singbox_version.txt` | 这是“唯一版本真相”，改了等于宣布全仓库已对齐新版 |
| 4 | 改矩阵里的 `adopt` | 等于替用户决定“用不用这个新功能” |
| 5 | **删除任何现有字段** | 删错了就是真机没网（L4 教训：当年删了 `auto_detect_interface`） |
| 6 | `upgrade-check.py --write` | 会把上游文档快照整体覆盖 —— **覆盖会丢掉本地手工标注**，先 diff |

### 任务 C：用户反馈"跑不起来"

```
1. 先看错误原文（sing-box 报错自带 ^ 指向出错路径）
2. FATAL unknown field  → 字段名写错或版本不支持 → 查 VERSION-MATRIX
3. FATAL legacy/removed → 用了已移除字段 → 查 VERSION-MATRIX 的迁移写法
4. 静默但功能不对      → 查 PLATFORM-MATRIX 平台能力
5. **能启动但没网**     → 先查 `route.auto_detect_interface`（见下方分岔点），再查 DNS detour
6. **先在 `docs/LESSONS.md` 里查有没有同类事故**，有就按那条的修法办
7. 修完把新的教训追加成 `## L<n>` 条目，并确保对应门禁 code 已实现（否则 `audit_lessons()` 会拦）
```

**分岔点：错误是 check 阶段还是 run 阶段？**

- `sing-box check -c` 就能报的 → 字段名/类型/枚举问题，直接查矩阵。
- **`check` exit=0，但 `run` 启动即 FATAL** → 属于初始化期问题。已收录的典型：
  `FATAL ... initialize rule-set[n]: ... detour to an empty direct outbound makes no sense`。
  这是「下载用的 direct 出站是空的」。处理：给 `direct-download` 加
  `domain_resolver`（或 `bind_interface` / `inet4_bind_address` / `routing_mark`）。
  **`domain_strategy` / `network_strategy` 不算数**（已 `schema:"omit"`）。
- 修完必须跑 `python tools/audit.py --run --run-seconds 20` 复现一次，确认不再有 `FATAL`；
  静态检查 + `check` + `run` 三层都过才算修完。

**第三层陷阱：`check` 过了、`run` 也活着，手机上仍然没网。**

已收录的典型症状：**能启动、但节点全部没有延迟、只有上传流量没有下载流量、连接数上万、内存飙到 1GB**。

根因是配置里缺 `route.auto_detect_interface: true`。机制（源码 `common/dialer/default.go`）：

```
if defaultOptions.BindInterface != "" && !disableDefaultBind { ... }
else if networkManager.AutoDetectInterface() && !disableDefaultBind {
    // Android 图形客户端走这一支
    bindFunc := networkManager.ProtectFunc()   // → VpnService.protect(fd)
    dialer.Control = control.Append(dialer.Control, bindFunc)
    listener.Control = control.Append(listener.Control, bindFunc)
}
```

没写这个字段 ⇒ 整个 `else if` 不成立 ⇒ 出站 socket **一个 Control 都不挂** ⇒ Android VpnService
把自己 App 的流量也抓进隧道（`Settings.allowBypass` 默认 false）⇒ 出站回灌 tun ⇒
节点测速全部失败（→ 全无延迟）、流量只进不出（→ 只有上传）、urltest 3 分钟一轮反复重试（→ 连接数与内存暴涨）。

官方原文（`docs/configuration/inbound/tun.md`）：
> To avoid traffic loopback, set `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`

Android 上后两者都不可用（VpnService 托管环境没有可用网卡名），**唯一可行的是 `auto_detect_interface`**。
官方 `docs/manual/proxy/client.md` 的三份客户端示例也都写了 `"auto_detect_interface": true`。

注意：`sing-box check` 对这个问题**完全静默**（`check` 只反序列化），所以只能靠 `audit.py` 的静态门禁兜住。

## 4. 校验命令

```bash
# 八项门禁（结构 / 废弃字段 / 平台能力 / 引用完整性 / 防回灌 / 广告拦截语义 / IPv4-only 端到端 / 新功能采纳）+ 教训台账一致性 + 决策记录双向校验 + 防泄漏扫查 + sing-box check
# audit.py 自己找 sing-box；找不到可用 --singbox 或环境变量 SINGBOX_BIN 指定
# 每次跑都会先校验 docs/LESSONS.md 的 `**门禁**：` 声明与代码里的 rep.error/rep.warn/rep.info code 双向对得上，
# 并校验 docs/DECISIONS.md 与矩阵里 kind=new 条目双向对得上
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
python tools/audit.py --singbox "C:/path/to/sing-box.exe" --version 1.14.3

# 只跑 sing-box 官方 check
sing-box check -c profiles/1.14/ios-lazy.json

# ★ 交付 / 排错前必跑：真启动一次，抓 check 看不见的启动期 FATAL
#   （会自动把 tun 入站临时换成 mixed、cache_file 指到临时目录；会真的连网拉规则集）
python tools/audit.py --run --run-seconds 20

# 上游巡检 / 重新生成人读版矩阵
python tools/upgrade-check.py
python tools/gen-docs.py
```

> **铁律：`sing-box check` 只反序列化、不初始化。**
> “check 全绿”**不等于**“能启动”。空的 direct 出站、规则集下不下来、
> 初始化期的引用问题，check 一律 exit=0。交付前至少跑一次 `--run`。

`audit.py` 退出码：`0` 全通过，`1` 有 ERROR（禁止交付）。
WARN 可以交付，但必须在回复里向用户说明。

**教训台账一致性**（`audit_lessons()`，每次跑都执行，不需要额外参数）：
- 方向一：`docs/LESSONS.md` 里 `**门禁**：` 声明的每个 code 必须在 `tools/audit.py` 源码里真实存在（`rep.error` / `rep.warn` / `rep.info` 都算），
  否则报 ERROR `lessons_missing_gate`（防止“文档声称有防护、代码里根本没实现”）。
- 方向二：`tools/audit.py` 里每个非框架 code 必须在 `docs/*.md` / `AGENTS.md` / `README.md` 里出现过，
  否则报 ERROR `gate_without_lesson`（防止新门禁无人知道拦的是什么）。
- 框架性白名单（不要求有教训条目）：`json`, `no_singbox`, `run_skipped`, `singbox_check`, `singbox_run`, `singbox_run_tun`, `singbox_timeout`。

> 注意：`ads_block_log_noise` 故意做成 **INFO** 而不是 WARN —— 它描述的是“正常现象”，若做成 WARN 则每次自检都不干净，反而让人麻木。

`--version` 用来**预演**「假设客户端升级到这个版本会怎样」，例如
`python tools/audit.py --version 1.15.0 profiles/1.14/ios-lazy.json` 会提前告诉你要删 `stack`。

## 5. 交付给用户时的固定话术

必须包含：

- 目标 **sing-box 版本号**（正式版）
- 目标 **平台**（Android / iOS / Windows）
- 新增节点落在**哪个分流组**
- audit 结果（四项门禁是否全绿，有哪些 WARN）
- 完整 JSON（可复制粘贴的那种）

不得声称"已实测联网可用"——除非用户在本机真跑了 `sing-box run`。

## 6. 节点占位规则

- `profiles/` 里的文件**永远是占位值**（`node-0X.example.com`），它只是骨架与格式参考。
- 用户给了真实分享链接后，**替换占位、不要新增重复节点**，产物写进 `local/<platform>.json`。
- `local/` 已列入 `.gitignore`；提交前用 `git status` 复核，并可用
  `git grep -n -f <(printf '%s\n' "$真实域名")` 之类方式确认没有真实节点混进暂存区。
- 判断标准很简单：`python tools/audit.py` 对 `profiles/` 下任何文件报
  `placeholder_server` 就是错误，必须把真实节点挪出 `profiles/`。
