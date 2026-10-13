#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_rules_dupe.py —— 「同一条规则被两处各自完整陈述」的检测器

## 为什么有这个东西

本仓文档之间反复出现「两处定义漂移」：模块 2 的规则清单、三栏分类表、
完整克隆流程 —— 都曾在两个文件里**一字不差**各写一遍。

危害不是"啰嗦"，而是：**改一处忘另一处，两份开始打架，而没人知道哪份是对的。**
L46 记的那次门禁失效，成因就是"两处各写一份定义"。

## 判据（只报确定性情形）

抽每份文档里的**规则句**（含「必须/禁止/不得/严禁/一律/切勿/不要」的句子），
若**同一句的前 N 字**同时出现在 ≥2 份文件里 ⇒ 报。

白名单（**有意保留的重复**，必须写明理由，不许偷偷跳过）：
  · 「每次换设备…必须完整克隆」—— 这是**规则名**，入口与详版都要有
  · `git rev-parse --is-shallow-repository` —— 这是**判据命令**，入口必须可直接执行

## 用法

    python tools/audit_rules_dupe.py [--json]

退出码：0 = 无重复；1 = 有未豁免的重复。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 参与检查的「活文档」——历史台账（LESSONS/DECISIONS）与上游快照排除在外：
# 它们本来就要能引用旧名/旧话术，拿它们比对只会制造噪音。
DOCS = [
    "AI-ENTRY.md", "AGENTS.md", "MAINTAINERS.md",
    "docs/AI_SYNC_WORKFLOW.md", "docs/SINGBOX_UPGRADE.md",
    "docs/TEMPLATE_MIGRATION.md", "docs/CLIENTS_IOS_ANDROID_WINDOWS.md",
    "docs/EXPERIENCES.md", "docs/PROTOCOL-MAPPING.md",
]

RULE = re.compile(r"[^\n。；]*?(?:必须|禁止|不得|严禁|一律|切勿|不要)[^\n。；]*")
PREFIX = 12          # 取前 12 字判「同一句」

# 有意保留的重复：前缀 → 理由（必须写清楚，否则不许加）
EXEMPT_PREFIX = {
    "**每次换设备、换 AI":
        "规则名：入口(AGENTS §8)与详版(AI_SYNC §七)都要有，否则只读详版的人看不到它的地位",
    "git rev-parse":
        "判据命令：入口必须能直接执行，不该让人翻页去找；"
        "EXPERIENCES E1 里是**排障实例的复现步骤**（当时怎么确认是浅克隆的），"
        "属历史记录而非规则陈述，删了就复现不出来",
}


def collect():
    out = {}
    for f in DOCS:
        p = ROOT / f
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        out[f] = {s.strip() for s in RULE.findall(t) if len(s.strip()) > 8}
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="文档间规则重复检测")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rules = collect()
    seen = {}
    for f, rs in rules.items():
        for s in rs:
            seen.setdefault(s[:PREFIX], []).append((f, s))

    found, exempted = [], []
    for key, hits in seen.items():
        files = {f for f, _ in hits}
        if len(files) < 2 or len(hits) < 2:
            continue
        # ⚠️ 用**前缀匹配**而不是精确相等：EXEMPT 的 key 是人手写的，
        # 与 PREFIX 截断长度对齐这件事靠人记 —— 第一个版本就写错了
        # （key 写成 13 字符、实际取 12 字符，于是豁免永远不生效）。
        # 让 key 只要是规则前綴的一部分就算命中，长度不再需要人肉对齐。
        hit = next((k for k in EXEMPT_PREFIX if key.startswith(k[:8])), None)
        if hit:
            exempted.append((key, sorted(files), EXEMPT_PREFIX[hit]))
            continue
        found.append((key, sorted(files), [s for _, s in hits]))

    if args.json:
        print(json.dumps(
            {"duplicates": [{"prefix": k, "files": f} for k, f, _ in found],
             "exempted": [{"prefix": k, "files": f, "reason": r} for k, f, r in exempted]},
            ensure_ascii=False, indent=2))
        return 1 if found else 0

    for key, files, samples in found:
        print(f"  [RULES_DUPE] 「{key}…」同时出现在 {len(files)} 份文件：{', '.join(files)}")
        print(f"       例：{samples[0][:74]}")
    print(f"\n检查 {len(rules)} 份活文档，未豁免的跨文件重复规则：{len(found)} 组"
          f"（另 {len(exempted)} 组经豁免）")
    if found:
        print("\n  ⇒ 同一件事只应在一处完整陈述。请把正文收敛到它的**归属文档**，")
        print("     其余位置只留一句话 + 指针（见 AI-ENTRY.md 的「单一来源」原则）。")
        print("     确属必要重复的，加进本文件 EXEMPT_PREFIX 并写明理由。")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
