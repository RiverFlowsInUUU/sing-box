#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-shell-escapes.py —— 换设备/换 Agent 后的**第 0 步环境自检**

## 它测什么

测「命令行参数里的反斜杠，穿过本机的调用链后还剩几个」。

2026-10-13 在本机实测的结果（**这张表是量出来的，不是推的**）：

    发出（个）  收到（个）
    ─────────   ─────────
        1           1
        2           1      ← 丢了一个
        3           2
        4           2
        5           3
        6           3

**⇒ 收到 ≈ ⌈发出 / 2⌉（折半向上取整）。**

这意味着：**你用两个反斜杠想写出「一个字面反斜杠」，实际到手只有一个 —— 内容静默变了。**
`\\n` 会变成真换行、`\\x00` 会变成真 NUL 字节、markdown 表格会被劈断，
而这一切**从命令输出里看不出来**。我在本仓为此回滚过 7 次。

## 关键认知：配环境治不了它

实测三层：

  · Bash / shell  —— **正常**（`<<'EOF'` 原样透传）
  · Python        —— **正常**（`\\n` 是它该有的转义，不是 bug）
  · **调用链那一层** —— ❌ **折半发生在这里**

所以在 Windows 上配 `chcp` / `$OutputEncoding` / `PYTHONIOENCODING` / `core.autocrlf`
**全都治不到它**。与其配一堆设置，不如**换设备后先量一下倍率**，据此决定用法。

## 怎么用

    python tools/check-shell-escapes.py

  · `转义无损`  → 可以放心用命令行传含反斜杠的内容
  · `转义被改写` → **内容必须走文件**（`find_file` / `replace_file`）；
                  `patch-text.py` 已对 inline 反斜杠做**拒绝执行**，会把你拽回正轨

退出码：0 = 无损；1 = 被改写。

## ⚠️ 本工具早期的错误（留档，别再犯）

第一版让探针**自己起一个 python 子进程**去传参 —— 那条路绕开了真正会改写的那一层，
于是永远报「无损」，是个**测错地方的假绿灯**。
现在改成：检查器**自己检查自己收到的探测值**，由调用方（CI / 人或 Agent）传参进来，
测的才是真实链路。
"""

import argparse
import sys

BS = chr(92)          # 一个反斜杠字符

# 本机实测基准表：发出 n 个 → 期望收到几个。
# 若实际与「无损」不符，说明这一层会改写；具体倍率请以**你机器上量出来的**为准。
def expected_if_lossless(n: int) -> int:
    return n


def measure(argv):
    """返回 [(发出数, 收到数), ...] —— 由调用方把探测串作为参数传进来。"""
    out = []
    for i, raw in enumerate(argv, start=1):
        out.append((i, raw.count(BS)))
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="转义层自检（换设备/换 Agent 后的第 0 步）")
    ap.add_argument("probes", nargs="*",
                    help="探测串，由调用方传入；每个串的反斜杠个数即为「发出数」")
    args = ap.parse_args()

    if not args.probes:
        print("═══ 转义层自检 ═══\n")
        print("  需要由调用方传入探测串（本工具只负责「数」，不自己造串 ——")
        print("  自己造串会绕开真正会改写的那一层，测出假绿灯）。\n")
        print("  用法示例（在 **Bash 工具**里逐条跑，把结果喂回来）：")
        print()
        for n in (1, 2, 3, 4):
            s = BS * n
            print(f"    python tools/check-shell-escapes.py '{s}'   # 发出 {n} 个")
        print()
        print("  或者直接看下面的自检提示。")
        return 0

    rows = measure(args.probes)
    print("═══ 转义层自检（换设备/换 Agent 后的第 0 步）═══\n")
    print(f"  {'序':>3}  {'收到（个）':>10}")
    got = []
    for idx, cnt in rows:
        got.append(cnt)
        print(f"  {idx:>3}  {cnt:>10}")

    # 调用方按 1,2,3,4 个反斜杠传入时，无损应为 1,2,3,4
    lossless = all(c == i for i, c in rows)

    print()
    if lossless:
        print("  ⇒ **转义无损**：这一层原样透传。")
        print("     （仍推荐内容走文件 —— 它同时规避了批次覆盖、锚点错位等其它坑。）")
        return 0
    print("  ⇒ **转义被改写**。实测形态是「折半向上取整」：")
    print("       发出 1→1   2→1   3→2   4→2   5→3   6→3")
    print("     ⇒ 你用两个反斜杠想写「一个字面反斜杠」，到手只有一个，**内容静默变了**。")
    print()
    print("     ⚠️ 这一层在调用链里，**配 shell / Python / Windows 编码都治不到**。")
    print("     ⇒ 唯一可靠做法：**内容只走文件**，命令行只传文件名 ——")
    print("        用 `patch-text.py` 的 `find_file` / `replace_file`")
    print("        （工具已对 inline 反斜杠做**拒绝执行**）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
