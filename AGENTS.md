# AGENTS.md — sing-box 配置工作流（AI 入口 · 司机版）

> 本文件是**给要改配置的人/AI 读的**。目标：拿到分享链接 + 目标平台，
> **一条命令**产出「能在当前 sing-box 正式版上跑起来」的配置。
>
> 你不需要背规则。规则已经编译进了工具里 —— 你只需要**把链接交给工具**。
> 走的是快车道；想抄近路（手工拼 JSON）才需要读下面那些铁律。

## 0. 一句话任务

用户给**节点分享链接**（`vmess://` `vless://` `trojan://` `hysteria2://` `ss://` `anytls://` `tuic://`）
+ **目标平台**（desktop / android / ios）+ **落点**（代理组 / 智能组），你负责出一条命令：

```bash
python tools/mknode.py 'vless://...' 'vmess://...' --platform ios --group proxy
```

它内部做完四件事，**一步不落**：

| # | 做什么 | 由谁保证 |
|---|---|---|
| 1 | 链接 → outbound | `tools/share-link.py`（reality 块、aid 缺省、SS2022 密钥长度、transport、flow 值域…） |
| 2 | 套骨架、换掉占位节点 | `profiles/<ver>/<platform>-lazy.json` |
| 3 | 新节点 tag 加进目标组 | 组名常量与 `audit.py` 逐字一致 |
| 4 | 跑门禁（含 `sing-box check`） | `tools/audit.py` |

产物落 **`local/<platform>.json`** —— 含真实节点，`.gitignore` 已忽略，**永不提交**。

### 三个选项

| 选项 | 什么时候用 |
|---|---|
| `--group ai` | 用户说"给 AI 用""走台湾节点"→ 落到 `🤖 AI` 组 |
| `--name 香港01` | 用户想自己命名节点（可重复，按顺序对应链接） |
| `--keep-placeholders` | 想在骨架基础上继续手工加东西（默认**删掉**占位节点并清理悬空引用） |

`--group ad` 会被**直接拒绝** —— `🚫 AD` 组只放 `block`，永远不放代理节点。

### 交付前只有一条硬规矩

**不要把没跑过门禁的配置交给用户。** `mknode.py` 已经替你跑了；如果你手工改了产物，
再跑一次：

```bash
python tools/audit.py local/ios.json --platform ios
```

退出码 `0` 才算交付。有 `[E]` 就是**别发**。WARN 可以发，但要在回复里说明。

### 交付话术（第 5 节有完整版）

必须说清四件事：目标 sing-box 版本号 / 目标平台 / 新节点落在哪个组 / 门禁结果。
**不得声称"已实测联网可用"** —— 除非用户在本机真跑了 `sing-box run`。

---

## 1. 硬性铁律

> ⚠️ **下面这些是"抄近路"才会用到的**。你走 `mknode.py` 快车道时，铁律 2/3/5/6/9/12/13/14
> 都已经在工具与门禁里了 —— **不用背，错了会被当场拦下**。
>
> 真正需要你**主动记住**的只有两条：**铁律 7（别把真实节点写进仓库）** 和 **铁律 17（改仓库先给人看 diff）**。
> 这两条机器判不了"你想干什么"，只能你自己守。

| # | 铁律 | 谁在守 |
|---|------|--------|
| 1 | **只面向正式版**。现行版本记在 `singbox_version.txt`；不用 `-alpha`/`-beta`/`-rc` 字段 | `mknode.py` 读该文件 |
| 2 | **未知字段 = 致命错误**（`FATAL ... json: unknown field`） | `audit.py` + schema |
| 3 | **已移除字段 = 致命错误** | `audit.py` 查 `version-matrix.json` |
| 4 | **`check` 通过 ≠ 配置正确**。`check` 不校验平台能力、不校验规则集顺序、对"已废弃未移除"的字段完全静默 | 交付前跑 `--run` |
| 5 | **平台能力不同**。iOS/Android 不支持 `strict_route`；Android 无 `process_name` 权限 | `audit.py` + `PLATFORM-MATRIX.md` |
| 6 | **分流组只有三个**：`🚀 Proxy`（urltest）、`🤖 AI`（urltest）、`🚫 AD`（出口恒为 `block`）+ `direct`/`block`。tag 必须逐字带 emoji。代理组与智能组里**只放真实节点，不嵌套组** | `audit.py`、`mknode.py` 别名表 |
| 7 | ⚠️ **任何时候、任何文件都不放真实节点**。`profiles/` 只允许占位域名；真实凭据只进 `local/`（已 gitignore）。范围是**整个被跟踪仓库**，`docs/` 里的散文同样是公开的。**指针也算泄漏物**：force-push 只挪指针，旧对象仍可按 SHA 直取（实测 HTTP 200）⇒ 引用事故写「日期 + 背景」，**不写 commit SHA** | `sensitive_ip_in_repo` / `placeholder_server` / `redaction_clean` 三道 + **你自己** |
| 8 | **规则集走 CDN**，前缀统一 `https://testingcf.jsdelivr.net/gh/` | `audit.py` |
| 9 | **广告规则集用 Jinx**（不用 `MetaCubeX` 的 `category-ads-all`）。顺序：`jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`。DNS 层与 route 层是**两张独立的顺序表**，改一处必须改另一处 | `_audit_dns_adblock()` |
| 10 | **旧版本配置只归档不删除**（`archive/<大版本>/`） | — |
| 11 | **不在本机乱试**。本机有 OpenClash 网关，本机 `run` 的**连通性结论一律不可信**（DNS 被劫持，实测过）。只允许读配置 / 读官方文档 / 读内核源码。`check` 与 `--run` 只验「能不能启动」 | — |
| 12 | **tun + auto_route 必须写 `route.auto_detect_interface: true`**，否则出站回灌 tun ⇒「能启动但没网、节点全无延迟、连接数暴涨」 | `tun_without_auto_detect_interface` |
| 13 | **日志里 `using outbound/selector[🚫 AD]: operation not permitted` 是正常的**（`syscall.EPERM` 就是"拦住"的意思），**别去"修"**。反过来说：`🚫 AD` 的 `default` 必须始终是 `block` | `ad_group_default_not_block` |
| 14 | **「只走 IPv4」必须端到端**：`route.rules` 里要有一条 `{"action":"resolve","strategy":"ipv4_only"}`，位置**紧跟 `hijack-dns` 之后**（放末尾等于没放） | `resolve_missing_ipv4_only` / `resolve_not_first` |
| 15 | **出口 IP 的地址族不由客户端决定**。看到 IPv6 出口**不要**继续加固本地，先确认是不是节点自身的 AAAA；要改去服务端 | — |
| 16 | **上游新功能必须显式写下「启用/不启用/必须跟随」**，不写等于隐式选了"不启用" | 见 `MAINTAINERS.md` |
| 17 | ⚠️ **改配置、改流程都先拉仓库、先看 diff**。改完**先 `git diff` 给人看、得到同意、才 `commit`/`push`**。**不得直接覆盖已有文件**。克隆拿不到 `local/`，真实节点只能由用户当场提供 | **你自己** |
| 18 | **依据优先级：官方文档 > 官方源码 > 本仓文档**。冲突时以官方为准并**当场修本仓文档**；追不到出处的写成「未验证」而不是写成结论 | — |
| 19 | **平台差异必须同时落三处**（profile + `PLATFORM-MATRIX.md` §4 一行 + 门禁），缺一就是静默失效 | `matrix_platform_stale` / `profile_drift` |
| 20 | **三个组 tag 是不可随手改的契约**。改 tag 必须端到端改（profile + 模板 + 矩阵 + 全部散文 + `local/`）。**引用面必须靠 grep 列，不能靠记忆** —— `dns.servers[].detour` 是个反直觉的落点 | `group_tag_incomplete` / `dns_server_detour_missing` |
| 21 | **凡是把外部事实写进代码/文档的地方，都要配一个探针或快照**。最危险的失效是「门禁还在、判据已经落空」——上游把字段改名后 `find_paths` 永远返回空，门禁**静默失声**而全仓照样全绿 | `matrix_path_unreachable` / `audit_tools()` |

### 过程铁律（22–26）：**只在"抄近路/维护仓库"时适用**

这五条是 2026-10-13 一次 90 分钟任务（实际产出 30 分钟）换来的，见 `docs/LESSONS.md` L45。
**根因是压缩失忆**：上下文被摘要后，"我已经读过这个文件""我已经否决过这个方案"会被先吃掉。

| # | 铁律 |
|---|------|
| 22 | **读文件有预算**：同一文件一次任务只整读一次；第二次起 `grep -n` 定位 + 只读那一段。同类整读到第 3 次必须停下 |
| 23 | **被否决的方案当场落盘**到 `local/_wip.md`，不靠记忆 |
| 24 | **动编辑工具前必须先有一次「定稿」声明**：`定稿：<改什么> → <落在哪些文件> → <验收命令>` |
| 25 | **三振必须上报**：同类动作第 3 次停下，报「卡在哪 / 试过什么 / 二选一」 |
| 26 | **按时报进度**，一次三行（已完成 / 正在做 / 有没有卡住） |

> 💡 **为什么现在不那么痛了**：90 分钟那次，读文件占了成本大头 —— 因为「任务 A」要求先读
> 6 万 token 的文档再手拼 JSON。现在走 `mknode.py`，**要读的只剩你自己写的这一份入口**。
> 铁律 22 依然适用于维护仓库、调门禁这类"必须真读代码"的场合。

---

## 2. 走快车道就不用读的（需要时再查）

```
docs/PROTOCOL-MAPPING.md   ← 只有在「手工拼 outbound」时才需要（约 2.9k token）
docs/VERSION-MATRIX.md     ← 只有在「怀疑某个字段废弃了」时才需要
docs/PLATFORM-MATRIX.md    ← 只有在「怀疑是平台差异」时才需要
docs/LESSONS.md            ← 【查时读，不是开工必读】事故台账。先 grep 关键词，别整读（118KB）
docs/DECISIONS.md          ← 【查时读】决策记录：新功能为何启用/不启用
docs/WORKFLOW.md           ← 完整工作流与排障
tools/                     ← 工具自己会告诉你用法：<tool> --help
```

> ⚠️ **`docs/LESSONS.md` 曾经被标为"开工先读"，那是个错误。** 它是 118KB 的事故卷宗 ——
> 给**改规则的人**看的，不是给**改配置的人**看的。每次改配置都整读它，等于出门买菜先读完
> 整个交警队的事故档案。它的正确用法是：**出错了再来 grep**（任务 C 的第 6 步）。

---

## 3. 三种典型任务

### 任务 A：用户给节点 → 出配置 ★ 最常用

```bash
python tools/mknode.py 'vless://...' --platform ios --group proxy
```

完事。**产物在 `local/ios.json`，门禁已经跑完，退出码 0 就可以交付。**

想先看效果不写盘：加 `--dry-run`。
用户给了**已有的配置**让你在他那份上改：见下面 §0.1。

### 任务 B：上游发布新正式版

→ **完整流程在 `MAINTAINERS.md`**（这是改仓库规则，不是改配置，别在快车道上做）。

一行预览：`python tools/upgrade-check.py`

### 任务 C：用户反馈"跑不起来"

```
1. 先看错误原文（sing-box 报错自带 ^ 指向出错路径）
2. FATAL unknown field  → 字段名写错或版本不支持 → 查 VERSION-MATRIX
3. FATAL legacy/removed → 用了已移除字段 → 查 VERSION-MATRIX 的迁移写法
4. 静默但功能不对      → 查 PLATFORM-MATRIX 平台能力
5. 能启动但没网        → 先查 route.auto_detect_interface，再查 DNS detour
6. grep docs/LESSONS.md 找同类事故（关键词：现象里那个报错），有就按那条的修法办
7. 修完把新教训追加成 ## L<n> 条目，并确保对应门禁 code 已实现（见 MAINTAINERS.md）
```

**分岔点：错误是 check 阶段还是 run 阶段？**

- `sing-box check -c` 就能报的 → 字段名/类型/枚举问题，直接查矩阵。
- **`check` exit=0，但 `run` 启动即 FATAL** → 初始化期问题。典型：
  `FATAL ... initialize rule-set[n]: ... detour to an empty direct outbound makes no sense`。

### §0.1 给用户的**已有配置**改东西时

不管改多小，**必做字段差异比对**：

```bash
python tools/diff_config.py 用户原始配置.json 我改完的配置.json
```

输出三段：`只在原始配置里（可能被我删了）` / `只在生成配置里（可能是我加的）` / `两边都有但值变了`。
**每一个差异都必须能说出为什么**；说不出原因的，按原始配置保留。

这条是拿真实事故换来的（L4）：当年凭印象重写模板，把用户配置里本来就有的
`auto_detect_interface: true` 删了，直接导致真机没网。

> `mknode.py` 是由骨架**重建**，不读用户原配置 —— 所以用户给的是自己那份时，
> 你要么用 `diff_config.py` 复核，要么明确告诉用户"这是按骨架重建的，不是在你那份上改的"。

### 需用户同意的六个动作（铁律 17 的具体清单）

以下六件事**每次都必须先说、得到同意才做**，不在这六条内的可直接执行：

| # | 动作 | 为什么需要同意 |
|---|---|---|
| 1 | `git commit` | 落盘即进入历史 |
| 2 | `git push` | 推到公开仓库就**收不回来**（2026-10-12 那次泄漏节点信息的提交，最终是**删库重建**才彻底清掉） |
| 3 | 改 `singbox_version.txt` | 它是"唯一版本真相"，改了等于宣布全仓库对齐新版 |
| 4 | 改矩阵里的 `adopt` | 等于替用户决定"用不用这个新功能" |
| 5 | **删除任何现有字段** | 删错了就是真机没网（L4） |
| 6 | `upgrade-check.py --write` | 会整体覆盖上游文档快照 —— **覆盖会丢掉本地手工标注**，先 diff |

---

## 4. 校验命令

日常只需要第一条（`mknode.py` 已经替你跑了）：

```bash
python tools/audit.py local/ios.json --platform ios     # 单个产物
bash tools/check-all.sh                                 # 全仓静态门禁 + 负向回归 + 逐份 check（秒级）
bash tools/check-all.sh --run                           # ★ 交付/排错前必跑，加启动级验证（约 1 分钟）
python tools/audit.py --version 1.15.0 profiles/1.14/ios-lazy.json   # 预演升级会怎样
```

**关于 sing-box 可执行文件**：`audit.py` 自己找（`bin/` → PATH → `local/.singbox-bin`），
也认环境变量 `SINGBOX_BIN`。

> ⚠️ 本机没有内核时，`check`/`run` 会**静默降级**为 INFO 跳过 —— 看起来照样 PASS。
> 要真跑就把路径写进 `local/.singbox-bin`（不提交，铁律 7）。

**退出码**：`0` 全通过；`1` 有 ERROR（**禁止交付**）。WARN 可以交付，但要在回复里向用户说明。

`--run` **必须先 `git add -A`** —— 防泄漏扫查看文件名单，不先 add 会「本地绿、CI 红」（L29）。
用 `check-all.sh` 就没这个坑：它把上面几件事串成一条命令，任一步失败都会点名。

> **`sing-box check` 只反序列化、不初始化。** "check 全绿"**不等于**"能启动"：
> 空的 direct 出站、规则集下不下来、初始化期的引用问题，check 一律 exit=0。

---

## 5. 交付给用户时的固定话术

必须包含：

- 目标 **sing-box 版本号**（正式版）
- 目标 **平台**（Android / iOS / Windows）
- 新增节点落在**哪个分流组**
- audit 结果（本次涉及的门禁是否全绿，有哪些 WARN）
- 完整 JSON（可复制粘贴的那种）

不得声称"已实测联网可用"——除非用户在本机真跑了 `sing-box run`。

---

## 6. 节点占位规则

- `profiles/` 里的文件**永远是占位值**（`node-0X.example.com`），只是骨架与格式参考。
- 用户给了真实链接后，产物写进 **`local/<platform>.json`**（`mknode.py` 默认就这么干）。
- 提交前用 `git status` 复核，并可用
  `git grep -n -f <(printf '%s\n' "$真实域名")` 之类方式确认没有真实节点混进暂存区。
- 判断标准很简单：`python tools/audit.py` 对 `profiles/` 下任何文件报 `placeholder_server`
  —— 错误，必须把真实节点挪出 `profiles/`。

---

## 7. 维护者请看 `MAINTAINERS.md`

改**规则本身**（升级内核、加门禁、改矩阵、加教训、改组 tag）的完整流程在那里。
本文件只负责一件事：**让改配置这件事快、且不会错。**
