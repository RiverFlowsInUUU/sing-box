#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_config.py — 逐叶子节点比对两份 sing-box 配置 JSON。

用途：用户给了一份已有配置让你改时，必做字段差异比对（见 docs/LESSONS.md L4）。
每一个差异都必须能说出为什么；说不出原因的，按原始配置保留。

用法：
    python tools/diff_config.py 用户原始.json 改完.json
"""

import json
import sys
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


def main():
    if len(sys.argv) != 3:
        print("用法: python tools/diff_config.py <原始.json> <改完.json>", file=sys.stderr)
        return 2
    a = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    b = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    A = dict(walk(a))
    B = dict(walk(b))

    only_a = sorted(set(A) - set(B))
    only_b = sorted(set(B) - set(A))
    changed = sorted(k for k in set(A) & set(B) if A[k] != B[k])

    print(f"原始: {sys.argv[1]}  ({len(A)} 个叶子字段)")
    print(f"改完: {sys.argv[2]}  ({len(B)} 个叶子字段)")
    print()
    print(f"只在原始配置里（可能被我删了）: {len(only_a)} 条")
    for k in only_a:
        print(f"  - {k}: {A[k]!r}")
    print()
    print(f"只在生成配置里（可能是我加的）: {len(only_b)} 条")
    for k in only_b:
        print(f"  + {k}: {B[k]!r}")
    print()
    print(f"两边都有但值变了: {len(changed)} 条")
    for k in changed:
        print(f"  ~ {k}: {A[k]!r} -> {B[k]!r}")
    if not (only_a or only_b or changed):
        print("两份配置完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
