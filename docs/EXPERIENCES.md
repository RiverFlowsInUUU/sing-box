# EXPERIENCES.md — 经验总结

> 本文是 [`AI_SYNC_WORKFLOW.md`](AI_SYNC_WORKFLOW.md) **模块 5** 的落地处。
>
> ## ⚠️ 使用前必读
>
> **本文不替代上游官方文档，也不具备权威性。**
>
> 每条经验都标注了**性质**，请按性质决定信任程度：
>
> | 标记 | 含义 |
> |---|---|
> | 🟢 **官方确认** | 有上游官方文档/源码/release notes 依据，附来源 |
> | 🟡 **经验推测** | **本仓实测或推断得出，未经官方确认**。可用作线索，**不得当作结论**，更不得据此推断上游行为 |
> | 🔵 **本仓约定** | 本仓库自己的结构性约定，与 sing-box 内核无关 |
>
> 本文内容**需我确认后才写入**。AI 可以建议追加，不得自行落笔。

---

## 一、克隆与仓库完整性

### E1. 浅克隆会让版本对比直接失效 🔵

**现象**：用 `gh repo clone <repo> -- --depth 1` 克隆后，
`git rev-list --count HEAD` 只有 1 个提交、`git tag` 为 0。

**影响**：无法做版本对比、上游差异分析、模板语法迁移判断 —— 这些正是模块 1/2/3 的核心动作。

**修复**：

```bash
git rev-parse --is-shallow-repository   # true 就是浅克隆
git fetch --unshallow
git rev-parse --is-shallow-repository   # 必须回到 false
git rev-list --count HEAD               # 恢复完整提交数
```

**实测**：本工作流建立时踩到过 —— 修复后提交数从 1 恢复到 33。
**结论**：完整克隆是**最高优先级闸门**，不是建议。详见
[`AI_SYNC_WORKFLOW.md`](AI_SYNC_WORKFLOW.md) §七。

---

## 一bis. 开工前：台账怎么用（**查，不是整读**）

生成或修改配置**之前**，除了本文件，还要看两份台账：

- [`LESSONS.md`](LESSONS.md) —— 事故台账：真机上出过的事故（含完整报错原文）、源码级根因、对应门禁 code。
- [`DECISIONS.md`](DECISIONS.md) —— 记着「为什么这些新功能被否决」，避免把已否定过的方案又提一遍。

> ⚠️ **但不要「开工前先整读一遍」。** `LESSONS.md` 有 2000+ 行 —— 它是**查时读**：
> 出错了按报错关键词 `grep` 进去找同类事故。把它当开工仪式整读，是纯浪费。

**台账与门禁双向绑定**，`python tools/audit.py` 每次都会校验：

- 台账里声明的门禁 code 必须在 `tools/audit.py` 里**真实实现**（`lessons_missing_gate`）
- 代码里每个非框架门禁 code 必须在某个文档里有**出处**（`gate_without_lesson`）

所以「文档声称有防护、代码里没有」和「新加了门禁没人知道它拦什么」都会被拦住。

**但双向绑定只能证明门禁「存在」，证明不了它「会响」** —— 一个按早已不用的字面量匹配的门禁
在代码里真实存在、文档里也有出处，却永远不会报错。
所以每道门禁还必须有一个**负向用例**：`tools/negtest.py` 故意改坏 28 处，每处必须报出对应 code。
**加新门禁时必须往 `CASES` 里登一个用例**，不要临时现写脚本、跑完就删。

**为什么 `profiles/` 按大版本分目录**：1.14 的配置在 1.15 上可能直接 `FATAL`。
按大版本分目录后，升级 = 新开一个目录，旧配置原地保留、随时可回退。

## 二、校验与门禁

### E2. 「没跑」和「跑了且通过」看起来一样 🔵

**现象**：门禁依赖 `sing-box` 可执行文件；找不到时相关检查**跳过**，
输出里只有一行 INFO，而整体结论仍是 PASS、退出码 0。

**实测**：把版本矩阵改坏 + 不提供内核 → **0 ERROR / 退出码 0**，一个坏仓库拿到满分体检报告。

**对策**：跳过必须报 **WARN**（现已如此）。**一条永远为真的绿灯等于没有灯。**

**教训**：这正是本仓反复记录的「静默失效比报错危险」。详见 `LESSONS.md`。

### E3. 内核报「已移除」时不会说 `unknown field` 🔵

**现象**：探针（把字段注入最小配置交给内核 `check`）只检查 `unknown field` 来判定「内核不认这个字段」。
但 sing-box 对被**移除**的字段使用内置 migration，报的是
`<x> database is deprecated in sing-box A and removed in sing-box B` ——
**不含 `unknown field`**，于是被判成「内核认识」。

**后果**：依赖该判据的门禁**永远不会响**，而全仓照样全绿。

**对策**：判据同时认 `unknown field` **和** 内核自报的 `removed in`（且需**不晚于**目标版本）。

**性质**：🟡 本条是对**本仓探针实现**的实测结论；「内核这样报」有实际输出佐证，但
「上游所有版本的报法一致」未逐版本验证 —— 依赖具体版本时应重新确认。

### E4. `check` 通过 ≠ 能启动 ≠ 三端都对 🟢

`sing-box check` 的行为有明确边界：

- **只反序列化、不初始化** —— 初始化期的问题（如规则集引用、空出站）它一律 exit=0。
- **不校验平台能力** —— 某端不支持的字段照样通过。
- **不校验规则集顺序**。
- 对「**已废弃但未移除**」的字段可能**完全静默**。

**对策**：三条都过才算数 —— `check` + 版本矩阵 + 平台矩阵。交付前跑启动级验证。

### E5. 平台差异表不是全都上了锁 🔵

`PLATFORM-MATRIX.md` 的 §4（具体字段差异）与三份 profile **逐格机器对账**；
但 §1/§1a/§2/§2a（**能力清单**）**没有可靠的官方机读源**，只能人工按「来源」一栏复核。

**对策**：不要以为能力清单也被门禁保护了 —— 改动它需要人工复核。

---

## 二bis. 排障：按报错形态分流

**先看错误原文** —— sing-box 报错自带 `^` 指向出错路径。

| 报错 | 原因 | 处理 |
|---|---|---|
| `FATAL ... json: unknown field "xxx"` | 字段名写错，或该版本没这个字段 | 查 `schema.json`；查 `VERSION-MATRIX.md` 是否已改名 |
| `FATAL ... deprecated in X and removed in Y` | 用了已移除字段 | 查 `VERSION-MATRIX.md` 的替代写法 |
| `FATAL ... decode config at` + 具体路径 | 类型/枚举值不对 | 看错误里指出的路径 |
| `FATAL ... invalid public_key / illegal base64` | 密钥格式不对 | reality `public_key` 必须合法 base64url；SS 2022 密码必须合法 base64 |
| `FATAL ... http_client is conflict with deprecated download_detour` | 两者同时出现 | 删掉 `download_detour` |
| `FATAL ... detour to an empty direct outbound makes no sense` | **下载用的 direct 出站是空的**（只写了 `{"type":"direct","tag":"direct"}`） | 给 `direct-download` 加 `domain_resolver`，或 `bind_interface` / `inet4_bind_address` / `routing_mark` 任一项。⚠️ `domain_strategy` 已被 `schema:"omit"`，**填了不算数**（1.14 上写了还直接 FATAL）；但 `network_strategy` 是真字段，填了能把出站变非空 |
| `FATAL ... uTLS is required by reality client` | reality 缺 `utls` 块 | reality **必须**配 `tls.utls`（含 `enabled` + `fingerprint`） |
| `FATAL ... initialize outbound[n]: missing tags` | selector / urltest 的 `outbounds` 为空 | 给该组补节点或 `block` |
| 启动成功但某类流量走错 | 平台能力 / 规则顺序 | 查 `PLATFORM-MATRIX.md`；检查 `route.rules` 顺序 |
| 日志刷 `operation not permitted`，目标 IP 反复出现 | **不是故障**：`block` 出站拦广告的正常输出（`syscall.EPERM`） | **不用改配置**。嫌刷屏就把 `log.level` 设为 `"panic"` |
| **启动成功、但完全没网**：节点全无延迟、只有上传没下载、连接数上万、内存飙 1GB | 缺 `route.auto_detect_interface: true`（出站 socket 没被 `protect()`，回灌 tun） | 在 `route` 里加 `"auto_detect_interface": true`。门禁报 `tun_without_auto_detect_interface` |
| 崩溃 / 无日志 | 工作目录问题 | Android 看 `$working_directory/stderr.log`；Windows 看 `C:\ProgramData\sing-box-daemon` |
| 出现 IPv6 出口 IP | ⚠️ **先分清哪一层**：① 本地递的仍是域名（`resolve` 没生效或位置不对）② 本地递的已是 IPv4 字面量，**服务端**自己选了 IPv6 | ① 看 `route.rules` 里 `resolve` 是否紧跟 `hijack-dns`、排在第一个 route/reject 之前 —— **放末尾等于没放**（第一条 route 一命中就 `break match`）。门禁报 `resolve_not_first` / `resolve_not_ipv4_only` / `resolve_missing_ipv4_only`。② **本地已无能为力**，先确认是不是节点自身的 AAAA；要改去服务端禁用 IPv6 出网（铁律 15）。判定方法见 `LESSONS.md` L17/L18 与 `docs/evidence/2026-10-12-resolve-ipv4-vs-vps-egress.md` |

### 三层问题模型（很值得记住）

**第一层 · `check` 就能报** —— 字段名 / 类型 / 枚举。直接查矩阵。

**第二层 · `check` exit=0，但 `run` 启动即 FATAL** —— 初始化期问题。`check` **只反序列化、不做任何初始化**，所以这类错它一律沉默：

- 空的 direct 出站
- 规则集 / DNS 服务器 / 出站在**初始化期**才暴露的引用与资源问题
- 规则集 URL 实际下不下来（要等真去 Get 那一刻）

判定机制（源码级）：`protocol/direct/outbound.go` 里整个 dialer 选项块一个非默认字段都没有就是「空」；
`common/dialer/detour.go` 的 `init()` 对 `IsEmpty()` 的 direct 直接报错。

**所以门禁必须真跑一次**：

```bash
python tools/audit.py --run --run-seconds 20
```

`--run` 会自己把 tun 入站临时替成 `mixed`（避免 Windows 建假网卡），把 `cache_file.path` 指到临时目录，
跑 20 秒后主动终止，只看输出里有没有 `FATAL`。

**第三层 · 能启动、不报错，但就是没网** —— `route.auto_detect_interface` 缺失。
静态结构对、`check` EXIT=0、`run` 也能活着，但手机上一用就废。症状固定好认：

- 首页/仪表盘显示内存占用瞬间 1GB
- 瞬间爆出上万个入站与出站请求
- 所有节点都测不出延迟
- 只有上传流量，没有下载流量

机制：`networkManager.AutoDetectInterface()` 直接返回 `route.auto_detect_interface` 的值。
没写 ⇒ 整个 `NewDefault` 分支不成立 ⇒ 出站 socket **一个 Control 也不挂** ⇒
Android VpnService 把本 App 自己的流量也抓进隧道 ⇒ 出站回灌 tun。

官方原文（`docs/configuration/inbound/tun.md`）：

> To avoid traffic loopback, set `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`

三个手段在 **Android 图形客户端上只有第一个可行**：另两个需要真实网卡名，
而图形客户端走的是 `ProtectFunc()`（`UsePlatformNetworkInterfaces()` 恒 `true`），不是桌面那套网卡绑定。

**为什么 `check` 抓不到**：它不跑 `NetworkManager.Start()`，也不调 `NewDefault`。
所以只能在 `audit.py` 里做静态门禁。

### ⛔ 不在本机乱试

本机（Windows）挂着 OpenClash 网关，DNS 会被网关劫持 —— 实测过：一份**完全不含 fakeip 配置**的
最小配置查 `testingcf.jsdelivr.net`，`223.5.5.5` 仍返回 `198.18.0.70`（fakeip 网段）。

- **本机跑出来的「能上网 / 不能上网」结论一律作废**，不能写进交付说明
- `sing-box check` 与 `audit.py --run` 只验「能不能启动」，**不准验「能不能上网」**
- 排查只允许三种手段：**读配置、读官方文档、读 sing-box 源码**
- 真机结论只能由我在真机上给出

---

## 二ter. 常见误区

| 误区 | 事实 |
|---|---|
| 「`sing-box check` 过了就没问题」 | 错，而且错得很危险。`check` **只反序列化、不初始化**：空 direct 出站、规则集下不下来、`download_detour` 这类废弃字段，它全都不吭声 |
| 「`direct` 出站就是个直连，不用写别的」 | 裸的 `{"type":"direct","tag":"direct"}` 是**空 direct**，不能当规则集下载的 detour。下载专用出站固定叫 `direct-download`，必须带 `domain_resolver` |
| 「给 direct 加 `domain_strategy: ipv4_only` 就不算空了」 | 错。已废弃并被 `schema:"omit"`，**填了也不算数**；1.14 下还直接触发 FATAL |
| 「字段没了内核会提示」 | 未知字段/已移除字段会，**已废弃未移除的常常不会** |
| 「iOS 和 Windows 配置可以通用」 | 大部分可以，但 `strict_route`、TUN 地址这些必须分开；差异全表见 `PLATFORM-MATRIX.md` §4 |
| 「规则集用 GitHub raw 就行」 | 国内经常打不开，必须走 jsdelivr CDN，且显式指定下载用的 `http_client` |
| 「广告用 `category-ads-all` 就够了」 | 本仓用 Jinx + 秋风，且**必须**配放行集，顺序 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| 「规则顺序无所谓」 | 顺序错了等于没加。`geosite-cn` 排在拦截之前，国内广告域名会先命中直连，广告规则再无机会执行 |
| 「`cache_file.path` 可以写 `../cache/cache.db`」 | sing-box **不会**自动建父目录，父目录不存在直接 `FATAL`。写 `cache.db` |
| 「分流组越多越好」 | 本仓只要代理组 / 智能组 / 去广告组三个 + `direct` / `block` |
| 「让智能组指向代理组省事」 | 两个 urltest 串联后测速互相拖累，智能组失去独立优选意义；组的 `outbounds` 只放真实节点 |

### 修完必须回写

把这次踩的坑补进 [`PROTOCOL-MAPPING.md`](PROTOCOL-MAPPING.md) 的「常见解码坑」表，
或 `docs/version-matrix.json`。**否则下次还会踩。**

---

## 三、本仓工作方式

### E6. 「改配置」与「改规则」成本差一个数量级 🔵

**现象**：历史上改一个节点要先按入口文档读完整套技术资料，单次任务耗时远超实际产出。

**对策**：仓库分为两扇门 ——

- **改配置**（给节点、出配置、排障）→ `AGENTS.md` + `tools/mknode.py`（一条命令）
- **改规则**（升级内核、加门禁、改矩阵、改组 tag）→ `MAINTAINERS.md`

**性质**：🔵 本仓约定。具体数据见 `LESSONS.md`。

### E7. 文档分层：`AGENTS.md` 是路牌，不是仓库 🔵

`AGENTS.md` 只放：定位 / 必读顺序 / 硬规则 / 文档索引 / 禁止事项 / 回复格式 / 完整克隆要求。
详细技术内容一律下沉 `docs/`。

**判据**：一条规则在 `AGENTS.md` 里**最多一句话**，解释靠链接。

### E8. 改用户的现成配置前先做差异比对 🔵

不管改动多小，都要比对「我改完的」与「用户原始」的字段差异，**每个差异都要能说出为什么**；
说不出原因的按原始保留。

**来历**：曾凭印象重写模板，把用户配置里本来就有的字段删了，直接导致真机没网。
**工具**：`python tools/diff_config.py <原> <新>`。

---

## 四、文档中标注的「未能确认」事项

以下条目在本次工作流编写时**未能找到官方依据或仓库对应信息**，按要求标注，
**请勿当作结论使用**：

| 事项 | 状态 |
|---|---|
| 三端模板目录 | ✅ 已确认：可运行模板在 `profiles/<大版本>/<平台>-lazy.json`；`templates/{ios,android,windows}/` 为索引入口 |
| 上游项目 URL/名称 | ✅ 已确认：`https://github.com/SagerNet/sing-box` · `https://sing-box.sagernet.org/` |
| 当前同步版本记录文件路径 | ✅ 已确认：`singbox_version.txt` |
| 「仓库不保存可运行配置」 | `{{TODO: 待确认}}` — 与本仓现状不符，`profiles/1.14/` 下存有三份可运行配置（占位节点） |

---

## 五、怎么追加一条经验

1. **先问老板**。未经确认不得写入（模块 5 规则）。
2. 标**性质**：🟢 官方确认 / 🟡 经验推测 / 🔵 本仓约定。
3. 🟢 必须附官方来源链接；没有来源的**只能标 🟡**。
4. 写清**现象 / 影响 / 对策**，能附实测命令与输出更好。
5. 与既有条目重复时**合并**，不要新建重复段落。
