# -*- coding: utf-8 -*-
"""negdoc_mutations.py —— 「仓库级台账类门禁」的负向破坏表

## 为什么单独一个文件

这些门禁的判据在**文档与代码的交叉一致性**上：

  · 教训台账的 `**门禁**：` 行  ↔  `audit.py` 里真实存在的 code
  · 决策记录（`DECISIONS.md`）  ↔  矩阵里 `kind="new"` 的条目
  · 矩阵的 `path` / 版本号      ↔  内核自报

单文件负向样本**根本触发不到**它们 —— 在这张表出现之前，这批门禁
从被写出来那天起就**没被验证过会不会响**。

## 为什么不用内联字符串

本文件的每一条 `(锚点, 替换)` 都含 `\\n` 与 `"`。
早先三次尝试用 heredoc / `--spec-inline` 传递它们，**三次都被转义层改写**
（`\\n` 变真换行、`\\"` 降级成 `"`），每次都要回滚重来 —— 而回滚又冲掉了
上一批还没提交的用例，白干一次。
⇒ 内容**直接从文件读**，不经过任何一层转义。import 不做转义解释。

## 每条锚点都实测过（不是照着 code 名猜）

猜错四次，都记在这里，免得后人重犯：

  · `matrix-entry-missing-field`：删 `adopt` 报的其实是
    **`new_feature_without_adoption`**（同一条门禁，code 名不同）—— 期望值改对即可。
  · `new-feature-expect-invalid`：`expect` 写成 `"present"` **是合法值**，
    必须写成非法值（如 `"maybe"`）才触发。
  · `matrix-path-unprobeable`：通配路径确实不可探，但
    ① 必须是 `deprecated_in <= 目标版本` 的条目才会进入可达性判定（`tun_stack` 是 1.15.0，被跳过）；
    ② **必须有真内核** —— `--no-check` 时整个探针被跳过，只会报 `matrix_probe_skipped`。
    所以这条用例的作用域是 `doc_kernel`（要真跑内核）。
  · `lesson-missing-element`：校验的只有 `**根因` / `**为什么` / `**修法` 三项，
    **不含 `**现象**`** —— 改坏「现象」不会响，要改「根因」。
  · `decision-references-unknown`：它扫的是 D 小节正文里 **反引号包裹的 `new_xxx`**，
    改标题没用，要在正文里插一个不存在的 id。

## 纪律

锚点必须在目标文件里**恰好出现 1 次** —— `run_case_doc()` 会断言，不满足就拒绝执行
（同 `patch-text.py` 的唯一锚点原则，见 L39）。跑完由 `finally` 还原并校验字节一致。
"""

# {用例名: (目标文件, 锚点, 替换)}
DOC_MUTATIONS = {
    # ── 矩阵类 ──────────────────────────────────────────────────
    # 删掉 kind=new 条目的 adopt ⇒ 报 new_feature_without_adoption（同一门禁）
    "matrix-entry-missing-field": (
        "docs/version-matrix.json",
        '      "adopt": "yes",\n      "reason": "启用。缓存条目过期但仍在窗口（默认 3d）内时先返回旧值、后台刷',
        '      "reason": "启用。缓存条目过期但仍在窗口（默认 3d）内时先返回旧值、后台刷',
    ),
    # expect 写成非法值（"present"/"absent" 都是合法的，写别的才触发）
    "new-feature-expect-invalid": (
        "docs/version-matrix.json",
        '      "expect": "present",\n      "adopt": "yes",\n      "reason": "启用。缓存条目过期但仍在窗口（默认 3d）内时先返回旧值、后台刷',
        '      "expect": "maybe",\n      "adopt": "yes",\n      "reason": "启用。缓存条目过期但仍在窗口（默认 3d）内时先返回旧值、后台刷',
    ),
    # 窗口起点声明整行删掉 ⇒ coverage_window_missing
    "coverage-window-missing-a": (
        "docs/version-matrix.json",
        '    "coverage_floor": "1.14.0",\n',
        "",
    ),
    # path 改成不可探的通配形态。
    # ⚠️ 必须选 deprecated_in ≤ 目标版本的条目（download_detour: 1.14.0），
    #    否则会被「只对已存在字段做可达性判定」跳过；且需要真内核。
    "matrix-path-unprobeable": (
        "docs/version-matrix.json",
        '"deprecated_in": "1.14.0",\n      "removed_in": "1.16.0",\n      "path": "route.rule_set[].download_detour"',
        '"deprecated_in": "1.14.0",\n      "removed_in": "1.16.0",\n      "path": "**.totally.**.made.up.**.path"',
    ),
    # ── 教训台账 ────────────────────────────────────────────────
    # 声明一个代码里不存在的门禁 code
    "lessons-missing-gate": (
        "docs/LESSONS.md",
        "**门禁**：`download_detour_empty_direct`, `dangling_download_detour`,",
        "**门禁**：`no_such_gate_code_at_all`, `dangling_download_detour`,",
    ),
    # 把 `**门禁**：` 行改成不合格式的写法 ⇒ lesson_missing_gate_line
    "lesson-missing-gate-line": (
        "docs/LESSONS.md",
        "**门禁**：`tun_without_auto_detect_interface`, `android_override_vpn_no_adi`",
        "门禁(格式已坏)：`tun_without_auto_detect_interface`",
    ),
    # 改坏 `**根因**`（校验的三要素之一）⇒ lesson_missing_element。
    # 注意两点：
    #   ① `**现象**` **不在**校验列表里（只查 `**根因`/`**为什么`/`**修法`），改它不会响；
    #   ② 锚点必须带上下文的代码引用才唯一 —— 光写 `**根因**` 全仓出现 32 次，
    #      不唯一时 run_case_doc 会**拒绝执行**（这正是唯一锚点原则该有的行为，见 L39）。
    "lesson-missing-element": (
        "docs/LESSONS.md",
        "**根因**\n\n- `common/dialer/detour.go`",
        "**原因**\n\n- `common/dialer/detour.go`",
    ),
    # ── 决策记录 ────────────────────────────────────────────────
    # 在 D 小节正文里插一个矩阵不存在的 id（扫的是反引号包裹的 new_xxx）
    "decision-references-unknown": (
        "docs/DECISIONS.md",
        "## D1 sing-tun 自带 TCP/IP 栈 —— 必须跟随\n",
        "## D1 sing-tun 自带 TCP/IP 栈 —— 必须跟随\n\n"
        "（本行由负向用例插入，用于验证 decision_references_unknown）"
        "参考矩阵条目：`new_definitely_not_in_matrix`\n",
    ),
    # ── 工具自检 ────────────────────────────────────────────────
    # 往 negtest 里塞一个没登记的 m_* ⇒ 反向对账抓（这正是 L47 的对策）
    "tool-selftest-failed": (
        "tools/negtest.py",
        "# (用例名, 破坏函数, 期望的 code, 期望级别, 作用范围)",
        "def m_deliberately_unregistered_probe(cfg):\n"
        '    """故意不登记，验反向对账。"""\n'
        "\n\n"
        "# (用例名, 破坏函数, 期望的 code, 期望级别, 作用范围)",
    ),
}


def cases():
    """返回本表对应的 CASES 片段。

    第 5 位「作用域」：
      · `doc`        —— 改真文件，跑整仓，**不带内核**（audit --no-check）
      · `doc_kernel` —— 改真文件，跑整仓，**要真内核**（矩阵探针类门禁必须）

    只有 `matrix_path_unprobeable` 需要内核：其余几条的判据都在纯文本层面。
    """
    return [
        ("matrix-entry-missing-field", "m_matrix_entry_missing_field",
         "new_feature_without_adoption", "ERROR", "doc"),
        ("new-feature-expect-invalid", "m_new_feature_expect_invalid",
         "new_feature_expect_invalid", "ERROR", "doc"),
        ("coverage-window-missing-a", "m_coverage_window_missing",
         "coverage_window_missing", "ERROR", "doc"),
        ("matrix-path-unprobeable", "m_matrix_path_unprobeable",
         "matrix_path_unprobeable", "WARN", "doc_kernel"),
        ("lessons-missing-gate", "m_lessons_missing_gate",
         "lessons_missing_gate", "ERROR", "doc"),
        ("lesson-missing-gate-line", "m_lesson_missing_gate_line",
         "lesson_missing_gate_line", "ERROR", "doc"),
        ("lesson-missing-element", "m_lesson_missing_element",
         "lesson_missing_element", "ERROR", "doc"),
        ("decision-references-unknown", "m_decision_references_unknown",
         "decision_references_unknown", "ERROR", "doc"),
        ("tool-selftest-failed", "m_tool_selftest_failed",
         "tool_selftest_failed", "ERROR", "doc"),
    ]
