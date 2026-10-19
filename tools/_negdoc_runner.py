# -*- coding: utf-8 -*-
"""_negdoc_runner.py —— `doc` 作用域的实现（被 negtest.py import）

单独成文件的两个理由：
1. **避开转义层**：`DOC_MUTATIONS` 里全是 `\\n` 与引号，任何经过 shell / JSON 的
   传递方式都会把它们改坏（实测被坑三次）。import 不做转义解释 —— 干净。
2. **让「改了哪份真文件」在一处读完**：与 `patch-text.py` 的 spec 表同一思路，
   `negtest.py` 的注释里也写了「表比分支好读」。
"""

from pathlib import Path

# 与 negtest.py 共享的常量
ROOT = Path(__file__).resolve().parent.parent


def make_doc_runner(doc_mutations, audit_codes, register=None, unregister=None):
    """返回 `run_case_doc(name, mutate, base_text, level)`。

    注入 `doc_mutations` 与 `_audit_codes` 而不是直接 import negtest，
    避免循环依赖（negtest → _negdoc_runner → negtest）。

    `register` / `unregister` 同样注入：它们是 negtest 里的**安全网登记表**
    （信号/退出时兜底还原）。不注入就会又变成循环 import。
    不给时退化为空操作 —— 但生产路径必须给，否则被 SIGTERM 时会留脏文件
    （2026-10-19 实测过：docs/version-matrix.json 被永久改坏）。
    """
    _register = register or (lambda *a, **k: None)
    _unregister = unregister or (lambda *a, **k: None)

    def run_case_doc(name, mutate, base_text, level, use_kernel=False):
        """临时改一份**真实**仓库文档/工具文件，跑整仓审计，再立即还原。

        ⚠️ 纪律（同 `run_case_repo` / `run_case_matrix`）：
          · 锚点必须在目标文件里**恰好出现 1 次** —— 否则拒绝执行，不猜位置；
          · `finally` 里还原并**校验字节一致**，不一致就抛错让人手工恢复；
          · 绝不留下半改状态 —— 这些是入库文件，改坏了会直接进历史。
        """
        target_rel, old_anchor, new_anchor = doc_mutations[name]
        target = ROOT / target_rel
        original = target.read_bytes()
        text = original.decode("utf-8")
        n = text.count(old_anchor)
        if n != 1:
            raise RuntimeError(
                f"❗ {target_rel} 里找不到唯一锚点（出现 {n} 次）：{old_anchor[:60]!r}"
            )
        _register(target, original)        # 信号/退出时兜底还原
        try:
            target.write_bytes(
                text.replace(old_anchor, new_anchor, 1).encode("utf-8")
            )
            # use_kernel=True 时**不带** --no-check：矩阵探针类门禁依赖真内核，
            # 否则只会报 matrix_probe_skipped（看起来像"门禁没响"，其实是没跑）。
            return audit_codes(None, level, no_check=not use_kernel)
        finally:
            target.write_bytes(original)
            _unregister(target)
            if target.read_bytes() != original:
                raise RuntimeError(
                    f"❗ 还原 {target_rel} 失败 —— 请手工 `git checkout -- {target_rel}`"
                )

    return run_case_doc
