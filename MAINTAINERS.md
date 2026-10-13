# MAINTAINERS.md — 改**规则本身**的人读这份

> **司机看 `AGENTS.md`，立法者看这份。**
>
> 判断你该看哪份：你要动的东西**会不会改变"什么算对"**？
> - 升级内核、加门禁、改矩阵、改组 tag、加教训 → **改规则** → 本文件
> - 给节点、出配置、修一份跑不起来的配置 → **改配置** → `AGENTS.md`（走 `mknode.py` 快车道）
>
> 这两件事的成本差一个数量级。以前它们共用一个入口，结果是**改一个节点也要先读完整本维护手册**
> —— 那是 2026-10-13 那次 90 分钟任务的直接成因（`docs/LESSONS.md` L45）。

---

## 0. 核心心智模型：规则的三种寿命

`audit.py` 里的门禁按**判据来源**分三类，维护责任完全不同。搞混了就会做无用功。

| 类型 | 判据从哪来 | 上游升级时要做什么 |
|---|---|---|
| ① **版本驱动型** | `docs/version-matrix.json` 的 `deprecated_in` / `removed_in` / `since` | **自动跟着变**，改矩阵即可 |
| ② **外部事实硬编码型** | 平台能力判据、规则集顺序、`PLATFORM-MATRIX.md` §4 | **必须人工复核**（已有兜底：矩阵 §4 逐格对账） |
| ③ **本仓结构性约定** | 组 tag 形态、去广告组只留 `block`、目录用途 | 与内核版本无关，只需内部一致 |

> ⚠️ **最危险的失效是「门禁还在、判据已经落空」**：矩阵的 `path` 若被上游改名或搬走，
> `find_paths` 永远返回空，那条门禁**静默失声**，而配置侧的门禁全部照旧全绿。
> ⇒ 铁律 21：**凡是把外部事实写进代码/文档的地方，都要配一个探针或快照。**
> 这正是 `audit_matrix_paths()` 存在的理由。

---

## 1. 任务 B：上游发布新正式版

```bash
python tools/upgrade-check.py      # 报告：1 版本比对 2 文档 diff 3 矩阵对账 4 升级风险 5 新功能清点
```

### 1a. 旧字段部分（按报告第 3/4 节）

改 `docs/version-matrix.json`，`kind=deprecated` / `removed` / …。

### 1b. 新功能部分（按报告第 5 节）★ 最容易漏

上游除了「哪些字段要删」，还有「多了哪些新能力」。后者**没有默认答案** ——
不写就是隐式选择了"不启用"，而理由往往只是"没注意到"（铁律 16）。

出「升级清单」，三栏分类：

| 栏 | 含义 | 例子 |
|---|---|---|
| **必须跟随** | 旧写法被取代，必须删旧字段 | 1.15 的 `tun.stack` |
| **必须决策** | 新能力，启用/不启用由**用户拍板** | MASQUE / Tailcat / `auto_redirect` |
| **可放着** | 纯内部更新或与场景无关 | —— **也要记一笔**，否则下次会被当成漏项反复报警 |

> ⚠️ 这三栏**必须逐条给用户看、等用户拍板，不得自行决定**（铁律 16）。

### 1c. 用户拍板后，写两个地方

1. `docs/version-matrix.json` 的 `entries[]` 加 `kind="new"` 条目
   （机器依据，含 `adopt` / `reason` / `since` / `decide_by` / `keywords`；有字段可检测的还要 `expect`）
2. `docs/DECISIONS.md` 记下理由与**备选方案**

对应的门禁：`new_feature_without_adoption` / `new_feature_expect_invalid` /
`new_feature_decision_overdue` / `new_feature_uncovered` / `decision_without_record`

### 1d. 收尾

```bash
python tools/gen-docs.py                # 由 version-matrix.json 重新生成 VERSION-MATRIX.md（勿手改后者）
# 更新 singbox_version.txt；确认无误后 upgrade-check.py --write 刷新文档快照
```

> ⚠️ 改**流程本身**时四个文件必须同步（L22）：
> `AGENTS.md` / `README.md` / `MAINTAINERS.md` / `docs/DECISIONS.md`。

---

## 2. 加一条新教训

1. 在 `tools/audit.py` 里把能拦住这次事故的**门禁 code 实现出来**（不能只写文档）。
2. 在 `docs/LESSONS.md` 追加 `## L<n> <标题>`（**二级标题**；L6 是历史空号，继续往后编）。
3. 正文必须含五个小标题 —— `audit_lessons()` 会逐条校验缺哪个：
   `**现象**`（早期条目 `**现象/风险**` 也可）/ `**根因**`（**带源码路径**）/
   `**为什么没被拦住**` / `**修法**` / `**门禁**：`（**全角冒号、加粗、行首开始**）。
4. `**门禁**：` 行里写上第 1 步的 code（反引号包裹）；没有对应门禁就写「无」，
   **但必须写这一行**，否则报 `lesson_missing_gate_line`。
5. `python tools/audit.py` 应当能过。
6. **跑负向回归**：把用例登记进 `tools/negtest.py` 的 `CASES`
   —— **不要临时现写脚本、跑完就删**（那正是 L37「门禁可能是死的」没被发现的原因）。
   先确认它 ❌（新门禁还没实现时），实现后再确认 ✅。
7. `bash tools/check-all.sh` 应当能过。
8. 改**任何**文件用 `python tools/patch-text.py spec.json`，不要临时写 heredoc/python 重写
   —— 原子写 + 唯一锚点 + 不经 shell，三条各对应一次真实事故（L40）。

---

## 3. 改分流组 tag（铁律 20）

`🚀 Proxy` / `🤖 AI` / `🚫 AD` 是**契约**，不是标签。规范名逐字是
「emoji + **一个 ASCII 空格** + 名字」。

改 tag 必须端到端：

- `profiles/1.14/*-lazy.json`
- `templates/groups.json`
- `docs/PLATFORM-MATRIX.md` §4（如登记了相关行）
- `AGENTS.md` / `README.md` / `MAINTAINERS.md` / `docs/PROTOCOL-MAPPING.md` /
  `nodes/nodes.example.json`
- 仓库外 `local/` 下的运行配置

> **引用面必须靠 grep 列，不能靠记忆**（L35 事故）：这个 tag 出现的位置不止
> 「组定义 + `route.rules`」—— `dns.servers[].detour` 就是一个反直觉的落点。
> `grep -c '<tag>'` 全仓 JSON 逐个确认为止。

门禁：`group_tag_incomplete` / `template_group_tag_incomplete` 盯形态；
`template_profile_group_missing` / `profile_group_not_in_profile` 盯模板 ⟺ 配置一致；
`dns_server_detour_missing` / `domain_resolver_missing` 兜引用完整性。

---

## 4. 改平台差异（铁律 19）

**必须同时落三处，缺一就是静默失效**：

1. 改 `profiles/1.14/*-lazy.json`
2. 在 `docs/PLATFORM-MATRIX.md` §4 表里加**一行**
   （第一列必须是 `` `JSON 路径` ``，单元格必须是 `` `JSON 字面量` `` 或 `**删除**`；说明文字写在表外）
3. 需要时在 `tools/audit.py` 加门禁

`matrix_platform_stale` 逐格对账、`profile_drift` 反向兜底（§4 未登记的差异一律 ERROR）。

> ⚠️ 平台的能力清单（§1/§1a/§2/§2a）**无法机器核对**（没有可靠的官方机读源），
> 只能人工按「来源」一栏复核 —— 别误以为它也上了锁。

---

## 5. 工具自检与常见陷阱

`audit_tools()` 每次跑都会：

- 逐个 `compile()` `tools/*.py` → `tool_syntax_error`
- 对 `tools/diff_config.py` 的 `compare()` 做三组不变量测试 + `DIRECT_NON_EMPTY_KEYS` 语义断言
  → `tool_selftest_failed`
- 动机：**门禁只审配置、不审自己，静默失效比报错危险**（L25）

### 已被真实事故验证过的坑

| 坑 | 对策 |
|---|---|
| `open(p,"wb")` 先截断再算内容，中途异常文件只剩半截（audit.py 曾从 1919 行被截成 828 行） | 用 `patch-text.py`，原子写 |
| heredoc 里转义序列被 shell 改写，`\x00` 变真 NUL 字节 | 用 `patch-text.py`，不经 shell |
| 拿「某短 token 第一次出现」当锚点，命中的是文件里第一个 `try:` | `patch-text.py` 唯一锚点断言 |
| 同文件多条 patch 从「原始文本」算快照，第二条把第一条吞掉、还都打印 ✅ | 已修（L42）：逐条作用于上一条已应用后的文本 |
| 只看 `git ls-files`，漏掉新写的没 add 的文档 ⇒ 本地绿、CI 红 | 合并 `git ls-files --others --exclude-standard`（L29） |
| 「把要拦的 SHA 写进仓库」= 二次泄漏，递归无解 | 改用**时间切点** `LEAK_SCAN_START_DATE`（L24） |

### 跨工具行为必须一致

`find_singbox()` 的解析顺序（`bin/` → `local/.singbox-bin` → PATH）与
`tools/check-all.sh` 的 `resolve_singbox()` **必须一致** —— 两边不同会让人以为
「一边能跑一边不能」。改其中一个时，另一个一起改。

同理，`tools/mknode.py` 的分流组名表与 `tools/audit.py` 的 `GROUP_*` 常量、
`tools/share-link.py` 的 `VALID_SS_METHODS` 与 `audit.py` 的方法白名单，
都是**同一份事实的两处拷贝** —— 改一处必须改另一处。

---

## 6. 文件分工总览

```
AGENTS.md                     ← 司机入口（改配置）
MAINTAINERS.md                ← 本文件（改规则）
README.md                     ← 人类入口
singbox_version.txt           ← 当前正式版号 + 核查日期（唯一的版本真相）
docs/
  AI_SYNC_WORKFLOW.md         ← 总工作流（5 模块 / 触发 / 指令模板 / 异常处理）
  SINGBOX_UPGRADE.md          ← 模块 2：上游升级与新功能请示
  TEMPLATE_MIGRATION.md       ← 模块 3：模板语法迁移
  CLIENTS_IOS_ANDROID_WINDOWS.md ← 模块 4：三端差异与交付
  EXPERIENCES.md              ← 模块 5 + 排障 + 常见误区 + 经验总结
  LESSONS.md                  ← 事故台账【查时读，不是开工必读】现象/根因/为什么没拦住/修法/门禁
  DECISIONS.md                ← 决策记录【查时读】新功能为何启用或不启用、备选方案、前提风险
  PROTOCOL-MAPPING.md         ← 分享链接 → outbound 字段映射（手工拼节点时才需要）
  VERSION-MATRIX.md           ← 废弃/移除字段总表（由 version-matrix.json 生成，勿手改）
  version-matrix.json         ← 同上，机器可读（audit.py 的依据）
  PLATFORM-MATRIX.md          ← Android / iOS / Windows 能力差异表
  schema.json                 ← sing-box 官方 schema（字段白名单）
  upstream-*.md               ← 上游 deprecated / migration / changelog / tun 快照
  evidence/                   ← 事故证据存档（脱敏后入库）
profiles/1.14/                ← 可运行配置骨架（**只允许占位节点**）
templates/groups.json         ← 固定分流组骨架
nodes/nodes.example.json      ← 节点书写格式与分享链接对照示例
tools/
  mknode.py                   ← ★ 司机入口：链接 → 配置 → 门禁 → local/
  share-link.py               ← 链接 → outbound（mknode 调用它，不重复实现解码）
  audit.py                    ← 门禁：9 类配置风险 + 11 项仓库级对账
  negtest.py                  ← 门禁负向回归（故意改坏，确认门禁真的会响）
  check-all.sh                ← 一条命令跑完静态门禁 + 负向回归 + 启动级 + 逐份 check
  upgrade-check.py            ← 上游有新版本/新废弃项/未决策新功能时报告差异
  gen-docs.py                 ← 由 version-matrix.json 生成 VERSION-MATRIX.md
  diff_config.py              ← 两份配置的字段差异比对（铁律 0 的执行工具）
  patch-text.py               ← 安全文本改写（原子写 + 唯一锚点 + 不经 shell）
local/                        ← 【不提交】真实节点配置与 private 状态
archive/<大版本>/             ← 旧版本配置归档（只归档不删除）
```
