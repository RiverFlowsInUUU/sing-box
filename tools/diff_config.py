#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_config.py — 逐叶子节点比对两份 sing-box 配置 JSON。

用途：用户给了一份已有配置让你改时，必做字段差异比对（见 docs/LESSONS.md L4）。
每一个差异都必须能说出为什么；说不出原因的，按原始配置保留。

用法：
    python tools/diff_config.py 用户原始.json 改完.json      # 人读报告
    python tools/diff_config.py 用户原始.json 改完.json --state   # 机器读（供门禁/脚本判空）

退出码：
    0  两份配置完全一致或仅有差异（差异不是错误）
    2  参数或文件错误

--state 输出紧凑 JSON：{"only_a": [...], "only_b": [...], "changed": [...]}
另一份调用方式是 import：`from diff_config import compare` —— 门禁用它做不变量自检。
"""

import json
import sys

# L37：Windows 上 stdout 重定向到管道时默认回退 GBK，
# 本文件到处是 ✅/❌，一 `| tee` 就 UnicodeEncodeError 崩掉
# —— 管道里崩正是「本地绿、CI 红」的温床。故 import 后立即 reconfigure。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass          # 极端环境（无 stdout）下不影响主流程

from pathlib import Path


def walk(o, prefix=""):
    """把嵌套 dict/list 展平成 {路径: 值}，路径用 a.b[0].c 形式。"""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{prefix}[{i}]")
    else:
        yield prefix, o


def compare(a, b):
    """比对两个已解析的配置，返回 {"only_a", "only_b", "changed"}（均为已排序列表）。

    单独抽出来是为了让门禁能 import 它做不变量自检，
    而不是只“相信这段代码没问题”（见 tools/audit.py 的 audit_tools()）。
    """
    A = dict(walk(a))
    B = dict(walk(b))
    return {
        "only_a": sorted(set(A) - set(B)),
        "only_b": sorted(set(B) - set(A)),
        "changed": sorted(k for k in set(A) & set(B) if A[k] != B[k]),
        "values_a": A,
        "values_b": B,
    }


def main():
    argv = [x for x in sys.argv[1:] if x != "--state"]
    as_state = "--state" in sys.argv[1:]
    if len(argv) != 2:
        print("用法: python tools/diff_config.py <原始.json> <改完.json> [--state]", file=sys.stderr)
        return 2
    try:
        a = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        b = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        print(f"读取失败：{ex}", file=sys.stderr)
        return 2

    r = compare(a, b)
    A, B = r["values_a"], r["values_b"]

    if as_state:
        print(json.dumps({k: r[k] for k in ("only_a", "only_b", "changed")},
                         ensure_ascii=False))
        return 0

    print(f"原始: {argv[0]}  ({len(A)} 个叶子字段)")
    print(f"改完: {argv[1]}  ({len(B)} 个叶子字段)")
    print()
    print(f"只在原始配置里（可能被我删了）: {len(r['only_a'])} 条")
    for k in r["only_a"]:
        print(f"  - {k}: {A[k]!r}")
    print()
    print(f"只在生成配置里（可能是我加的）: {len(r['only_b'])} 条")
    for k in r["only_b"]:
        print(f"  + {k}: {B[k]!r}")
    print()
    print(f"两边都有但值变了: {len(r['changed'])} 条")
    for k in r["changed"]:
        print(f"  ~ {k}: {A[k]!r} -> {B[k]!r}")
    if not (r["only_a"] or r["only_b"] or r["changed"]):
        print("两份配置完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
