# -*- coding: utf-8 -*-
"""_negdoc_funcs.py —— `doc` 作用域用例的破坏函数（占位体）

## 为什么这些函数体是空的

`doc` 作用域的破坏**不在配置对象上做**，而是在**真实文件**上做文本替换 ——
内容全在 `negdoc_mutations.DOC_MUTATIONS` 里（`run_case_doc` 按用例名去取）。

`negtest.py` 的用例表统一是 `(名字, 破坏函数, 期望code, 级别, 作用域)` 五元组，
第 2 位必须是个可调用对象，所以这里提供一批「只用来占位、跑不到」的函数：
`run_case_doc` 只拿 `name` 去查表，**永远不会调用**传进来的 `mutate`。

## 为什么单独成文件

与 `negdoc_mutations.py` 同一理由：这个文件会通过 `Write` 工具落盘，
**不经过 shell / JSON 的转义层** —— 之前三次尝试用 heredoc 写它们，
函数体里没有转义字符所以没问题，但同批次的 `DOC_MUTATIONS` 每次都被改坏。
把两者放一起写，省得再踩。

## 维护提示

新增 doc 用例时：① 在 `negdoc_mutations.DOC_MUTATIONS` 加 (锚点, 替换)；
② 在这里加同名 `m_xxx`；③ 在 `negdoc_mutations.cases()` 登记。
`audit.py` 的反向对账会检查 ①③ 与这里的 `m_*` 是否一一对应。
"""


def m_matrix_entry_missing_field(cfg):
    """矩阵条目缺必填字段（adopt）。判据在矩阵文件上，见 DOC_MUTATIONS。"""


def m_new_feature_expect_invalid(cfg):
    """adopt=no 却 expect=present（自相矛盾）。"""


def m_coverage_window_missing(cfg):
    """矩阵不声明覆盖窗口起点。"""


def m_matrix_path_unprobeable(cfg):
    """矩阵 path 含通配，无法构造探针。"""


def m_matrix_version_mismatch(cfg):
    """矩阵自报版本与内核自报不一致。"""


def m_lessons_missing_gate(cfg):
    """教训声明的门禁 code 在代码里不存在。"""


def m_lesson_missing_gate_line(cfg):
    """教训条目缺 `**门禁**：` 行（或格式不合规）。"""


def m_lesson_missing_element(cfg):
    """教训条目缺五要素之一。"""


def m_decision_references_unknown(cfg):
    """DECISIONS.md 引用了矩阵里不存在的条目。"""


def m_tool_selftest_failed(cfg):
    """工具自检失败（此处是破坏 negtest 的反向对账）。"""
