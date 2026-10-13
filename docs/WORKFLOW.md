# WORKFLOW.md — 完整工作流

> 本文件说明「怎么用这套仓库」和「怎么维护这套仓库」。
>
> **入口已按职责分成两扇门，先确认你要动的是"配置"还是"规则"：**
> - 改配置（给节点、出配置、排障）→ 根目录 `AGENTS.md` + `python tools/mknode.py`
> - 改规则（升级内核、加门禁、改矩阵、改组 tag）→ 根目录 `MAINTAINERS.md`
>
> 分享链接怎么翻译成 outbound 见 `docs/PROTOCOL-MAPPING.md`（只在手工拼节点时才需要）。

## 零、这套仓库要解决什么问题

sing-box 迭代快，字段会**改名、合并、废弃、移除**，而且：

- 未知字段 → `FATAL ... json: unknown field` → 配置起不来
- 已移除字段 → `FATAL ... deprecated in X and removed in Y` → 配置起不来
- **已废弃但未移除** → 很多字段 `sing-box check` **完全静默**（典型：`download_detour`）
- **平台差异** → `check` 完全不校验（iOS 写 `strict_route` 照样 exit=0，但没效果）

所以只靠"让 AI 背文档"必然出错。本仓库把这些知识**固化成可执行的检查**（下面每一行都是一类风险）：

| 风险 | 兜底手段 |
|---|---|
| 未知字段 / 已移除字段 | `sing-box check`（内核自己报） |
| 已废弃未移除字段 | `docs/version-matrix.json` + `tools/audit.py` |
| 平台能力差异 | `docs/PLATFORM-MATRIX.md` + `tools/audit.py` |
| 引用完整性（出站/规则集/DNS server 不存在） | `tools/audit.py`（`check` 不校验！） |
| 规则集**顺序**（放行/拦截/分流先后错了等于没加） | `tools/audit.py` 的 Jinx 顺序检查 |
| **tun 出口回灌**（能启动但没网，`check` 全静默） | `tools/audit.py` 的 `tun_without_auto_detect_interface` 门禁 |
| **新增能力没决策**（多了什么而不是少了什么） | `tools/upgrade-check.py` 第 5 节 + `version-matrix.json` 的 `kind="new"` + `docs/DECISIONS.md` |
| **真实节点地址泄到公开仓库**（`docs/` 的散文也会公开） | `tools/audit.py` 的 `sensitive_ip_in_repo`（扫被跟踪文件 + commit message） |
| **门禁自己坏了 / 静默跳过**（工具语法错也能全绿） | `tools/audit.py` 的 `tool_syntax_error` + `tool_selftest_failed` |
| **模板里的文字过期**（`_rules_of_thumb` 无人消费，最易写反） | `tools/audit.py` 的 `template_thumb_stale` |
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
docs/upstream-*.md         上游文档快照（**取上游 testing 分支，不是锁定版本**）

  ⚠️ 这四份快照的 ref 是 `upgrade-check.py` 里的 `BRANCH = "testing"`，
  也就是**可能比 `singbox_version.txt` 锁定的正式版更新**（实测 `upstream-tun.md` 731 行
  vs 1.14.3 官方 `tun.md` 699 行，多出的正是 1.15.0 的变更段）。
  这是**故意的**：它的用途是「提前预警下一个版本要改什么」，不是「当前版本的说明书」。
  ⇒ 用它判断「1.14.3 支持什么」是错的；判断当前版本请查源码树里的
  `_probe/src/sing-box-<版本>/docs/`，或线上对应版本的 tag 文档。
docs/evidence/             事故证据存档（脱敏后入库）
profiles/<大版本>/          可运行配置（**占位节点**），按平台分文件
local/                      【不提交】本机真实节点配置（.gitignore 已忽略，仅存本地）
nodes/nodes.example.json   用户节点在该仓库里的书写示例
templates/                 片段骨架（节点、分流组）
tools/audit.py             门禁（唯一入口：配置 + 台账 + 决策 + 防泄漏 + 工具自检 + 平台矩阵 / 模板覆盖对账）
tools/diff_config.py       两份配置的字段差异比对（铁律 0 的执行工具，跨平台）
tools/upgrade-check.py     升级巡检（含第 5 节新功能清点）
tools/gen-docs.py          由 JSON 生成人读版矩阵
archive/                   旧大版本配置归档
docs/LESSONS.md            事故台账（每条教训 → 对应门禁 code，双向可追溯）
docs/DECISIONS.md          决策记录（每条新功能的启用/不启用、备选方案、前提风险）
```

## 一bis、开工前必做：读事故台账

**每次生成或修改配置之前，先扫一遍 [`docs/LESSONS.md`](LESSONS.md)。**
同时看 [`docs/DECISIONS.md`](DECISIONS.md) —— 那里记着「为什么这些新功能被否决」，
避免把已经否定过的方案又提一遍。
台账里逐条记了历史上真机上出过的事故（包括用户报的完整报错原文）、源码级根因、
以及对应的门禁 code。那些坑都是真金白银踩出来的，不要重踩。

台账与门禁**双向绑定**，`python tools/audit.py` 每次都会校验：

- 台账里声明的门禁 code 必须在 `tools/audit.py` 里真实实现（`lessons_missing_gate`）
- 代码里每个非框架门禁 code 必须在某个文档里有出处（`gate_without_lesson`）

所以“文档声称有防护、代码里没有”和“新加了门禁没人知道它拦什么”这两类问题都会被拦住。

**但双向绑定只能证明门禁「存在」，证明不了它「会响」** —— 一个按早已不用的字面量匹配的门禁
（L34）在代码里真实存在、在文档里也有出处，却永远不会报错。
所以每道门禁还必须有一个**负向用例**：`tools/negtest.py` 故意改坏 28 处，
每处必须报出对应的 code（见 L37）。加新门禁时**必须**往 `CASES` 里登一个用例，
不要临时现写脚本、跑完就删。

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
2. **落点分流组**：代理组（普通外网）、智能组（AI 类网站走更干净的出口）、去广告组（广告拦截）
3. **目标平台**：Android / iOS / Windows
4. **智能组要放哪些节点**（智能组与代理组是两个独立的 urltest 组，各自在组内节点间优选；
   用户不说就先把所有代理节点都放进去，**不要**用代理组当子节点）

缺哪个就问，不要自己猜。用户只说"A 放智能组"，那就只动智能组。

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
   且**不得与既有 tag 重复**（三个分流组 tag 与 `direct` `block` 都是保留名，逐字规范名见 `AGENTS.md` 铁律 6；代理组是 urltest，节点更不能占用）。
2. 把新 tag 加进目标分流组的 `outbounds` 数组。
   代理组与智能组都是 urltest，加进去即自动测速——**不再有单独的 Auto 组**；
   两个组的 `outbounds` 里**只放真实节点，不要放代理组 / 智能组这类组 tag**（不嵌套）。
3. **不要动** `route.rules`、`dns`、`inbounds`、`rule_set`，除非用户另外要求。
   其中规则集与规则顺序是**固定骨架**（见 `AGENTS.md` 的「固定规则集清单」）：
   `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`，少一个、换个位置都不行。
   **若启用了 DNS 层前置拦截**（见 `docs/DECISIONS.md` D13），`dns.rules` 里还有第二套顺序
   （白名单 → 拦截 → `geosite-cn`）需要同步维护 —— 两张表各写各的，排错即静默失效（L28）。
4. 去广告组**只允许** `block`（m07194 起删掉 `direct`），永远不要把代理节点放进去。
5. **组 tag 逐字用规范名**：`🚀 Proxy` / `🤖 AI` / `🚫 AD`（emoji + 一个 ASCII 空格 + 名字）。
   写错一个字符 = `route.final` / 规则引用全部落空（`check` 不会报）。详见 `AGENTS.md` 铁律 20。
   理由：`direct` 这一档在去广告组里没有任何使用场景（想直连的域名就该在规则里走 `direct`），
   而它一旦被用户选中或写成 `default`，广告就静默放行了。

### A5. 跑门禁

```bash
# 推荐：一条命令串完三层（静态门禁 + 负向回归 + 逐份 sing-box check）
bash tools/check-all.sh
bash tools/check-all.sh --run      # 再加启动级验证（约 1 分钟）

# 只想跑单份时：
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
# 交付前至少再真启动一次（check 只反序列化，验不了能不能起来）
python tools/audit.py --run --run-seconds 20 profiles/1.14/ios-lazy.json --platform ios
```

`audit.py` 会自己找 `sing-box`，也可以显式指定：

```bash
python tools/audit.py --singbox "C:/path/to/sing-box.exe" profiles/1.14/ios-lazy.json --platform ios
# 或设环境变量
export SINGBOX_BIN=/path/to/sing-box
```

要求：**0 ERROR**。有 ERROR 不许交付。WARN 要看清是什么，并写进给用户的说明里。

> `sing-box check` 通过 **不等于**能启动 —— 它只反序列化、不做任何初始化。
> 所以交付前必须至少跑一次 `--run`（真启动、只筛 `FATAL`），这是唯一能拦住
>「语法合法但跑不起来」的一层。因此交付话术里应当同时给出 `check` 与 `--run` 两个结论，
> **不得只报 `check` 通过就说“没问题”**。

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

> 🎯 **B1 之后第一件事是确认「门禁还好不好使」**：`audit_matrix_paths()` 会把矩阵里每条 `path`
> 注入一个最小探针交给内核认（见 L39）。它报 `matrix_path_unreachable` 就说明上游改过字段名或路径，
> 那条门禁**已经悄悄失效**——此时先更新矩阵的 `path`/`replacement`，再谈其他升级动作。

> 上游文档快照的**平台能力两页**（`docs/clients/{apple,android}/features.md`）已纳入跟踪：
> 它是 `docs/PLATFORM-MATRIX.md` §1/§1a/§2/§2a 的唯一权威源，上游把某个
> `:material-close:` 改成 `:material-check:` 时，仓库里硬编码的平台判据会把**正确写法判成 ERROR**。
> 文档快照取上游 **`testing` 分支**，可能比 `singbox_version.txt` 锁定的正式版更新（属提前预警）。

### B2. 判断跨度

- **补丁版（1.14.2 → 1.14.3）**：通常只是修 bug，配置一般不用改。仍要跑一遍报告。
- **小版本（1.14 → 1.15）**：一定有废弃项。**必须**逐条处理。
- **跨多个小版本**：按版本顺序逐段处理 `docs/upstream-deprecated.md`。

### B3. 处理废弃项

> 📖 先看 B3bis —— **新功能**（多了什么）与废弃项（少了什么）是两件事，都要处理。

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

### B3bis. 处理新增能力（`kind="new"`）—— 与废弃项同等重要

废弃项的处理是「**少了什么，怎么补**」；新能力是「**多了什么，用不用**」。
后者**没有默认答案**，不写就等于隐式选了“不启用” —— 而真实原因往往是“根本没注意到它存在”。

1. 看 `python tools/upgrade-check.py` 报告的第 5 节【新功能清点】：
   它把 `docs/upstream-changelog.md` 里的正式版新功能列出来，
   并标出哪些还没在矩阵里被收录（`new_feature_uncovered` 就是这条比对失败）。

> ⚠️ **比对窗口不是「≥ 锁定版本」**，而是**半开区间 `(policy.coverage_floor, 锁定版本]`** ——
> 起点显式写在 `docs/version-matrix.json` 的 `policy.coverage_floor`，含义是「已逐条盘点到此」。
> 为什么不能直接用锁定版当起点：`ver_ge(ver, floor)` 的语义是 **「>=」**，
> 这意味着**低于起点的版本不是「检查过」，而是「从来没进过检查」**（L43）。
> 若用锁定版当起点，1.14.0 那 49 条正式版新功能会永远落在窗口外、一次都没被盘过，
> 而门禁一路全绿 —— 而且升版到 1.15.0 那一刻窗口会把 1.14.x 整段拉回来，一次炸出几十条 ERROR。
> 因此 `coverage_floor` **只能显式声明**（不能用 `min(since)` 推导：「登记一条历史条目」就会把窗口拉低）。
> 同一版的盘点结论落在 `docs/evidence/` 下，并在 `policy.inventories` 里登记口径
> （`per-entry` = 逐条建条目 / `by-class` = 按类归档、结论只在文档里）。
> 若某条 `kind=new` 的 `since` 落在窗口之外（即 `since <= coverage_floor`），
> 它必须写 `inventory` 指向盘点文档，且文档里要出现该条目的 id（`inventory_doc_unlinked` 会拦）。
2. 把清单整理成**三栏**给用户看，逐条等拍板（**不得自行决定**，铁律 16）：

| 栏位 | 含义 | 矩阵写法 |
|---|---|---|
| **必须跟随** | 新写法取代旧写法、没有开关（例：1.15 把 `tun.stack` 换成 sing-tun 自带栈） | `kind="deprecated"` + `removed_in`（不是 `new`） |
| **必须决策** | 新能力，启用/不启用由用户拍板（例：MASQUE / Tailcat / `auto_redirect`） | `kind="new"`，`adopt` 必填 |
| **可放着** | 与场景无关或纯内部更新 —— 也要记一笔 | `kind="new"`，`adopt: "no"` + `reason` 写清“为何无关” |

3. 拍板后**写两个地方**（少一个都会被门禁拦）：

```jsonc
// docs/version-matrix.json 的 entries[] —— 机器依据
{
  "id": "new_masque_endpoints",
  "kind": "new",
  "since": "1.15.0",
  "title": "MASQUE 端点（CONNECT-IP）",
  "path": "endpoints[type=masque]",           // 可选：有字段可检测时才写
  "expect": "absent",                          // 有 path 时必填：present=配置里必须有 / absent=配置里必须没有
  "adopt": "no",                               // yes | no | must
  "reason": "现有 hy2/vless 节点已满足需求；MASQUE 需服务端支持",
  "decide_by": "1.16.0",                       // 可选：到这个版本前必须重新看一次
  "keywords": ["MASQUE", "CONNECT-IP"]         // 用于与 changelog 条目比对
}
```

```markdown
<!-- docs/DECISIONS.md —— 人的理由，模板见该文件开头 -->
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
bash tools/check-all.sh --run     # 静态门禁 + 负向回归 + 启动级 + 逐份 check
# 全部 0 ERROR 后：
echo "1.15.0  checked 2026-xx-xx" > singbox_version.txt
python tools/upgrade-check.py --write    # 更新上游文档快照
```

⚠️ **别漏这一步**：升版后要把 `docs/version-matrix.json` 的 `policy.coverage_floor` 推到新版本，
并在 `policy.inventories` 里补一条该版的盘点记录（口径 `per-entry` 或 `by-class` + `evidence` 文档）。
漏了不会当场炸 —— `coverage_inventory_missing` 才会响，而那正是它存在的理由：
「升级了但没盘点」在窗口里看起来和「盘过了、没问题」一模一样（L43）。

> ⚠️ 上面最后两行属于「需用户同意的六个动作」（`singbox_version.txt` / `--write`），
> **先给人看 diff、得到同意再做**。

## D5 MASQUE 端点：不启用
- **日期**：2026-10-12
- **触发**：1.15.0 上游新增
- **决策**：不启用
- **矩阵 ID**：`new_masque_endpoints`
- **为什么**：……
- **备选方案**：……（以及为何没选）
- **前提/风险**：……（什么条件下该重新评估）
```

> 编号取名时必须先看 `docs/DECISIONS.md` 现有的最大编号 —— 上面的 `D5` 只是示例，
> 真实文件里 `D5` 已经是「Tailcat + MASQUE + NaiveProxy 三合一」，照抄会撞号。
> 几件事同一理由时可以合写一条（真实 D5 就是合写）。

4. 门禁自检：`python tools/audit.py`。相关 code：
   `new_feature_uncovered`（changelog 有新功能但矩阵没收录）、
   `new_feature_without_adoption`（`kind=new` 缺 `adopt` / `reason`）、
   `new_feature_expect_invalid`（`adopt` 与 `expect` 矛盾，例如写了 `adopt: "no"` 却要求字段必须存在）、
   `new_feature_decision_overdue`（已过 `decide_by` 仍未拍板）、
   `decision_without_record` / `decision_references_unknown`（矩阵与 `DECISIONS.md` 双向不一致）。

> 为什么“必须跟随”类不算 `new`：它没有“用不用”的余地 —— 旧字段一删就得跟着走，
> 归入 `deprecated` 那套（含 `removed_in` 升级风险）才正确。

## 四、流程 C：用户反馈"跑不起来"

按报错形态分流：

| 报错 | 原因 | 处理 |
|---|---|---|
| `FATAL ... json: unknown field "xxx"` | 字段名写错，或该版本没有这个字段 | 查 `docs/schema.json` 是否有该字段；查 `docs/VERSION-MATRIX.md` 是否已改名 |
| `FATAL ... deprecated in X and removed in Y` | 用了已移除字段 | 查 `docs/VERSION-MATRIX.md` 的替代写法 |
| `FATAL ... decode config at` 后面跟着具体路径 | 类型/枚举值不对 | 看错误里指出的路径 |
| `FATAL ... initialize outbound[n]: invalid public_key / illegal base64` | 密钥格式不对 | reality public_key 必须是合法 base64url；SS 2022 密码必须是合法 base64 |
| `FATAL ... http_client is conflict with deprecated download_detour field` | 两者同时出现 | 删掉 `download_detour` |
| `FATAL ... detour to an empty direct outbound makes no sense` | **下载用的 direct 出站是空的**：只写了 `{"type":"direct","tag":"direct"}` | 给下载专用 direct（tag 固定为 `direct-download`）加 `domain_resolver`，或 `bind_interface` / `inet4_bind_address` / `routing_mark` 等任意一项。**注意：`domain_strategy` 已被 `schema:"omit"`，填了根本不会生效（而且 1.14 上写了直接 FATAL）；但 `network_strategy` 不受此限 —— 它是真字段，填了就能把出站变非空** |
| 启动成功但某类流量走错 | 平台能力 / 规则顺序 | 查 `docs/PLATFORM-MATRIX.md`、检查 `route.rules` 顺序 |
| 日志刷 `connection: open connection to …: operation not permitted`，目标 IP 反复出现 | **不是故障**：这是 `block` 出站拦广告的正常输出（`protocol/block/outbound.go` 返回 `syscall.EPERM`），日志里写 `outbound/selector[🚫 AD]` 是因为打印的是本连接被选中的那层出站 —— 说明 `jinx-ads` / `awanue-ads` 命中了 | **不用改配置**。嫌刷屏就把 `log.level` 设为 `"panic"` 或 `log.disabled: true`。详见 `docs/LESSONS.md` L16 |
| **启动成功、但完全没网**：节点全无延迟、只有上传没下载、连接数上万、内存飙到 1GB | 缺 `route.auto_detect_interface: true`：出站 socket 没被 `protect()`，回灌 tun | 在 `route` 里加 `"auto_detect_interface": true`（Android 上唯一可行的防回环手段）。`audit.py` 会报 `tun_without_auto_detect_interface` |
| 崩溃/无日志 | 工作目录问题 | Android 看 `$working_directory/stderr.log`；Windows 看 `C:\ProgramData\sing-box-daemon` |
| 用户说「访问境外网站还有 IPv6 请求」/ `https://ip.net.coffee/` 首页汇总里出现 IPv6 出口 IP | ⚠️ **先分清是哪一层**：① 本地往服务端递的仍是域名（`resolve` 没生效或位置不对）；② 本地递的已是 IPv4 字面量，但**服务端**自己选了 IPv6 出口 | ① 看 `route.rules` 里 `resolve` 是否紧跟 `hijack-dns`、排在第一个 route/reject 之前 —— **放末尾等于没放**（第一条 route 一命中就 `break match`）。`audit.py` 报 `resolve_not_first` / `resolve_not_ipv4_only` / `resolve_missing_ipv4_only`。② **本地配置已无能为力**，先确认那个 IPv6 是不是节点自身的 AAAA 记录；要改去服务端禁用 IPv6 出网（铁律 15）。判定方法见 `docs/LESSONS.md` L17/L18 与 `docs/evidence/2026-10-12-resolve-ipv4-vs-vps-egress.md` |

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
5. 改完必须 `bash tools/check-all.sh` 全绿才算完（含负向回归）。

## 六、常见误区

| 误区 | 事实 |
|---|---|
| "`sing-box check` 过了就没问题" | 错，而且错得很危险。`check` **只反序列化、不初始化**：空 direct 出站、规则集下不下来、`download_detour` 这类废弃字段，它全都不吭声。发布前必须 `audit.py --run` |
| "`direct` 出站就是个直连，不用写别的" | 裸的 `{"type":"direct","tag":"direct"}` 是**空 direct**，不能当规则集下载的 detour。下载专用出站固定叫 `direct-download`，必须带 `domain_resolver` |
| "给 direct 加 `domain_strategy: ipv4_only` 就不算空了" | 错。`domain_strategy` 已废弃并被 `schema:"omit"`，**填了也不算数**；而且 1.14 下直接触发 legacy domain strategy 的 FATAL。真正算数的是 `domain_resolver` / `bind_interface` / `inet4_bind_address` / `routing_mark` 等 |
| "字段没了内核会提示" | 未知字段/已移除字段会，**已废弃未移除的常常不会** |
| "iOS 和 Windows 配置可以通用" | 大部分可以，但 `strict_route`、TUN 地址这些必须分开；差异全表见 `docs/PLATFORM-MATRIX.md` §4，且那张表有门禁守着（铁律 19） |
| "规则集用 GitHub raw 就行" | 国内经常打不开，必须走 jsdelivr CDN，且配置里显式指定下载用的 `http_client` |
| "广告用 `category-ads-all` 就够了" | 本仓库用 Jinx (`jinx-ads`) + 秋风 (`awanue-ads`)，且**必须**配 `jinx-direct` 放行集，顺序 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| "规则顺序无所谓" | 顺序错了等于没加。`geosite-cn` 排在拦截之前，国内广告域名会先命中直连，广告规则再无机会执行 |
| "`cache_file.path` 可以写 `../cache/cache.db`" | sing-box **不会**自动建父目录，父目录不存在直接 `FATAL` 起不来。写 `cache.db` |
| "分流组越多越好" | 本仓库只要代理组 / 智能组 / 去广告组三个 + `direct` / `block` |
| "让智能组指向代理组省事" | 两个 urltest 串联后测速会互相拖累，且智能组失去独立优选意义；组的 `outbounds` 只放真实节点 |
