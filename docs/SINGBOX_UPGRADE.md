# SINGBOX_UPGRADE.md — 上游升级流程与新功能请示

> 本文是 [`AI_SYNC_WORKFLOW.md`](AI_SYNC_WORKFLOW.md) **模块 2** 的详细展开。
> 一句话：**AI 可以提醒、可以报告、可以问，但不得自动升级。**
>
> ⚠️ 本模块的「不得自动升级」**只约束本模块**，不限制模块 1/3/4/5 的正常工作。
>
> ⚠️ 唯一权威来源是 sing-box 上游官方 release notes / changelog / 文档。本文件只描述**流程**，
> 不描述 sing-box 的功能细节；找不到官方依据时标注「未能确认」，**不要猜**。

---

## 一、状态机

```
IDLE（只读可提醒）
  → Agent 提醒有新版
  → 我问详情
  → Agent 报告
  → 我授权升级
  → Agent 输出计划
  → 我逐项确认
  → Agent 修改
  → 校验
  → 分支 / PR
  → 我合并
```

**任何一步我不回应，流程就停在原地。** AI 不得自己往下走。

---

## 二、触发

| 谁触发 | 场景 | AI 立刻能做什么 |
|---|---|---|
| AI | 发现上游有新 stable（我提问时顺带看到、或心跳任务里看到） | **只能提醒**，然后停下 |
| 我 | 我说「检查 sing-box 上游最新稳定版」 | 进入**只读报告** |
| 定时任务 | —— | ❌ 不得触发同步 |

> ⚠️ 仓库里的 `.github/workflows/audit.yml` 是**质量门禁**（跑 `tools/audit.py` 防门禁静默失效），
> **不是**上游同步任务。它和本模块无关，不要混为一谈。

**版本范围**：只跟 **latest stable**。排除 `beta`、`alpha`、`rc`、`release candidate`、
`nightly`、`pre-release`、`测试版`、`预览版`。

---

## 三、AI 可以做的事

1. 提醒我上游有新的 stable 版本。
2. 问我要不要查看详情、要不要更新。
3. **只读**检查上游 latest stable 与当前仓库记录的版本差异。
4. 从官方 release notes / changelog / 官方文档提取本版本相对当前仓库记录的**新增/变更功能列表**。
5. 对每个功能给出**结构化条目**（格式见 §五）。
6. **逐点请示我**：每个功能、每个端单独列出，明确问「是否要开启/启用/加入配置」。
7. 输出后**停止**，等我逐条回复。
8. 只把我明确回复「开启」的功能和端，加入对应模板或配置。
9. 我回复「不开启」「暂缓」「不适用」的，**保持原样并记录原因**。
10. 禁止编造功能。找不到官方依据时标注「未能确认」。

---

## 四、AI 绝对不得做的事（仅限本模块 2）

- ❌ 不得因为发现新 stable 就自动升级
- ❌ 不得自动启用任何新功能
- ❌ 不得默认批量开启
- ❌ 不得未经授权修改配置
- ❌ 不得未经授权更新版本记录文件
- ❌ 不得未经授权创建升级 PR

**升级授权口令**（听到类似指令才算授权）：

- 「我确认升级到 sing-box vX.Y.Z」
- 「执行升级」
- 「按这个版本同步」

> **收到口令也不等于可以直接改文件** —— 必须先输出升级计划，等我逐项确认。

---

## 五、功能条目的结构化格式

每个新功能、**每个端**单独一条：

| 字段 | 说明 |
|---|---|
| **功能名称** | 上游 release notes 里的名字，不自行改名 |
| **来源** | release notes / docs / PR 链接（**必填**，无来源不算条目） |
| **一句话说明** | 这个功能干什么 |
| **当前仓库是否已在用** | 是 / 否 / 不确定 |
| **适用性（分端）** | iOS：可用 / 不适用 / 需客户端支持 / 不确定<br>Android：同上<br>Windows：同上 |
| **判断依据** | 例如需要 TUN、需要特定协议、需要客户端 UI 支持、仅服务端、仅移动端、平台限制 |
| **建议** | 开启 / 暂不开启 / 需我确认 |

**逐点请示**：不要合并成一句「这些新增要不要开」。要一条一条问：

```
【功能 A】xxx（来源：<链接>）
  iOS     — 可用        → 是否开启？
  Android — 需客户端支持 → 是否开启？
  Windows — 可用        → 是否开启？
```

---

## 六、升级计划模板

我授权后，AI 先输出这个，**不动文件**：

```
## 升级计划：sing-box <旧版本> → <新版本>

### 1. 版本跨度
- 旧：<singbox_version.txt 当前值>
- 新：<上游 latest stable>
- 中间跳过的版本：<列出>（跨多个版本时必须显式写出）

### 2. 必须跟随（旧写法被取代，必须删旧字段）
| 字段 | 变化 | 影响文件 | 三端 |
|---|---|---|---|

### 3. 必须决策（新能力，由我拍板）
（按 §五 格式逐条列出，附我的决策？）

### 4. 可放着（纯内部更新或与场景无关）
（也要记一笔，否则下次会被当成漏项反复报警）

### 5. 涉及文件清单
| 文件 | 改动类型 | 是否需我逐项确认 |
|---|---|---|

### 6. 校验计划
- <要跑的命令>
```

---

## 五bis. B3bis 新增能力：三栏分类与矩阵写法

废弃项是「**少了什么，怎么补**」；新能力是「**多了什么，用不用**」。
后者**没有默认答案**，不写就等于隐式选了「不启用」—— 而真实原因往往是「根本没注意到它存在」。

看 `python tools/upgrade-check.py` 报告的第 5 节【新功能清点】：它把
`docs/upstream-changelog.md` 里的正式版新功能列出来，并标出哪些还没在矩阵里被收录
（`new_feature_uncovered` 就是这条比对失败）。

### 比对窗口：半开区间 `(policy.coverage_floor, 锁定版本]`

> ⚠️ **不是「≥ 锁定版本」**。起点显式写在 `docs/version-matrix.json` 的 `policy.coverage_floor`，
> 含义是「已逐条盘点到此」。
>
> 为什么不能直接用锁定版当起点：`ver_ge(ver, floor)` 的语义是 **「>=」**，
> 这意味着**低于起点的版本不是「检查过」，而是「从来没进过检查」**（L43）。
> 若用锁定版当起点，1.14.0 那 49 条正式版新功能会永远落在窗口外、一次都没被盘过，
> 而门禁一路全绿 —— 而且升版到 1.15.0 那一刻窗口会把 1.14.x 整段拉回来，一次炸出几十条 ERROR。
>
> 因此 `coverage_floor` **只能显式声明**（不能用 `min(since)` 推导：「登记一条历史条目」就会把窗口拉低）。
> 同一版的盘点结论落在 `docs/evidence/` 下，并在 `policy.inventories` 里登记口径：
> `per-entry` = 逐条建条目 / `by-class` = 按类归档、结论只在文档里。
> 若某条 `kind=new` 的 `since` 落在窗口之外（即 `since <= coverage_floor`），
> 它必须写 `inventory` 指向盘点文档，且文档里要出现该条目的 id（`inventory_doc_unlinked` 会拦）。

### 三栏分类（**逐条给我看、等我拍板，不得自行决定** —— 铁律 16）

| 栏位 | 含义 | 矩阵写法 |
|---|---|---|
| **必须跟随** | 新写法取代旧写法、**没有开关**（例：1.15 把 `tun.stack` 换成 sing-tun 自带栈） | `kind="deprecated"` + `removed_in`（**不是** `new`） |
| **必须决策** | 新能力，启用/不启用**由我拍板**（例：MASQUE / Tailcat / `auto_redirect`） | `kind="new"`，`adopt` 必填 |
| **可放着** | 与场景无关或纯内部更新 —— **也要记一笔** | `kind="new"`，`adopt:"no"` + `reason` 写清「为何无关」 |

### 拍板后写两个地方（少一个都会被门禁拦）

```jsonc
// docs/version-matrix.json 的 entries[] —— 机器依据
{
  "id": "new_masque_endpoints",
  "kind": "new",
  "since": "1.15.0",
  "title": "MASQUE 端点（CONNECT-IP）",
  "path": "endpoints[type=masque]",           // 可选：有字段可检测时才写
  "expect": "absent",                          // 有 path 时必填：present=配置里必须有 / absent=必须没有
  "adopt": "no",                               // yes | no | must
  "reason": "现有 hy2/vless 节点已满足需求；MASQUE 需服务端支持",
  "decide_by": "1.16.0",                       // 可选：到这个版本前必须重新看一次
  "keywords": ["MASQUE", "CONNECT-IP"]         // 用于与 changelog 条目比对
}
```

```markdown
<!-- docs/DECISIONS.md —— 人的理由，模板见 §六ter -->
```

## 六bis. B1/B2：巡检与判断跨度

**B1 巡检**

```bash
python tools/upgrade-check.py
```

报告五节：① 版本比对 ② 文档 diff ③ 矩阵对账 ④ 升级风险 ⑤ 新功能清点。

> ⚠️ 若报告里出现 `matrix_path_unreachable`，说明**上游改过字段名或路径**、
> 那条门禁**已经悄悄失效** —— 此时先更新矩阵的 `path`/`replacement`，再谈其他升级动作。

> 上游文档快照的**平台能力两页**（`docs/clients/{apple,android}/features.md`）已纳入跟踪：
> 它是 `PLATFORM-MATRIX.md` §1/§1a/§2/§2a 的**唯一权威源**。上游把某个
> `:material-close:` 改成 `:material-check:` 时，仓库里硬编码的平台判据会把**正确写法判成 ERROR**。

**B2 判断跨度**

| 跨度 | 处理 |
|---|---|
| **补丁版**（1.14.2 → 1.14.3） | 通常只是修 bug，配置一般不用改。**仍要跑一遍报告** |
| **小版本**（1.14 → 1.15） | **一定有废弃项**，必须逐条处理 |
| **跨多个小版本** | 按版本顺序逐段处理 `docs/upstream-deprecated.md` |

## 六ter. B5 收尾（别漏这一步）

```bash
python tools/gen-docs.py                # 重新生成人读版矩阵
bash tools/check-all.sh --run           # 静态门禁 + 负向回归 + 启动级 + 逐份 check
# 全部 0 ERROR 后：
echo "1.15.0  checked 2026-xx-xx" > singbox_version.txt
python tools/upgrade-check.py --write   # 更新上游文档快照
```

⚠️ **别漏这一步**：升版后要把 `docs/version-matrix.json` 的 `policy.coverage_floor` 推到新版本，
并在 `policy.inventories` 里补一条该版的盘点记录（口径 `per-entry` 或 `by-class` + `evidence` 文档）。
漏了**不会当场炸** —— `coverage_inventory_missing` 才会响，而那正是它存在的理由：
**「升级了但没盘点」在窗口里看起来和「盘过了、没问题」一模一样**（L43）。

> ⚠️ 上面最后两行（改 `singbox_version.txt` / `--write`）属于「**需用户同意的六个动作**」，
> **先给人看 diff、得到同意再做**。

**B3 附加：决策记录（`DECISIONS.md`）条目格式**

```
## D<n> <主题>：启用 / 不启用
- **日期**：YYYY-MM-DD
- **触发**：<上游版本 + 功能名>
- **决策**：启用 / 不启用
- **矩阵 ID**：`new_xxx`
- **为什么**：……
- **备选方案**：……（以及为何没选）
- **前提/风险**：……（什么条件下该重新评估）
```

> 编号取名时**必须先看 `docs/DECISIONS.md` 现有的最大编号** —— 照抄示例会撞号。
> 几件事同一理由时可以合写一条。

**B3 门禁自检**：`python tools/audit.py`。相关 code：

| code | 拦什么 |
|---|---|
| `new_feature_uncovered` | changelog 有新功能但矩阵没收录 |
| `new_feature_without_adoption` | `kind=new` 缺 `adopt` / `reason` |
| `new_feature_expect_invalid` | `adopt` 与 `expect` 矛盾（写了 `adopt:"no"` 却要求字段必须存在） |
| `new_feature_decision_overdue` | 已过 `decide_by` 仍未拍板 |
| `decision_without_record` / `decision_references_unknown` | 矩阵与 `DECISIONS.md` 双向不一致 |

> **为什么「必须跟随」类不算 `new`**：它没有「用不用」的余地 —— 旧字段一删就得跟着走，
> 归入 `deprecated` 那套（含 `removed_in` 升级风险）才正确。

## 七、本仓库现成的工具

本仓已有一套与模块 2 对应、可直接使用的实现（**复用，不要另造**）：

| 用途 | 命令 / 位置 |
|---|---|
| 上游巡检：版本比对 / 文档 diff / 矩阵对账 / 升级风险 / 新功能清点 | `python tools/upgrade-check.py` |
| 字段生命周期台账（机器可读） | `docs/version-matrix.json` |
| 人读版字段表（自动生成，**勿手改**） | `docs/VERSION-MATRIX.md` ← `python tools/gen-docs.py` |
| 决策记录（新功能为何启用/不启用） | `docs/DECISIONS.md` |
| 上游文档快照 | `docs/upstream-{changelog,deprecated,migration,tun}.md` |
| 门禁（防「新功能没决策」） | `tools/audit.py` 的 `new_feature_*` / `decision_without_record` |

> ⚠️ `docs/upstream-*.md` 是**上游 testing 分支**的快照（`tools/upgrade-check.py` 里的 `BRANCH = "testing"`），
> 可能比 `singbox_version.txt` 锁定的正式版更新。它的用途是**提前预警下个版本要改什么**，
> **不是**当前版本的说明书。用它判断「当前锁定版本支持什么」是错的。

**新功能清点的比对窗口**：半开区间 `(policy.coverage_floor, 锁定版本]`，
起点显式写在 `docs/version-matrix.json`。详见 `MAINTAINERS.md`。

---

## 八、与 `MAINTAINERS.md` 的分工

| 文档 | 面向 | 内容 |
|---|---|---|
| **本文件** | 我（老板）与 AI 的**交互流程** | 什么时候能做什么、怎么请示、怎么授权 |
| [`MAINTAINERS.md`](../MAINTAINERS.md) | 改**规则本身**时的**操作手册** | 具体改哪个文件、矩阵条目怎么写、门禁怎么加、教训怎么记 |

简单说：**本文件管「能不能做」，`MAINTAINERS.md` 管「怎么做」。**
