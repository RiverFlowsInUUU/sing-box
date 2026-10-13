#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rule-add.py —— 「加一条 route/dns 规则」的一站式工具

## 为什么有它

2026-10-13 实测：加一条 `route.rules` 花 28 分钟，其中**真正改配置不到 1 分钟**，
其余全耗在「手动同步到 4 份文档」和「反复跑全量校验」。

老板的比喻很准：**改配置应该像路上的车 —— 不违章就走得飞快，违章就撞墙。**
现状是**每条路都得自己铺**，所以再快也快不了。

这个工具把「铺路」这一步固定下来：

    一条命令 = 三端加规则 + 自动同步可生成文档 + 跑门禁

## 用法

    # 看能加什么
    python tools/rule-add.py --help

    # 加一条规则（按 **序号** 插入，序号含义见 CONFIG-ANATOMY §4）
    python tools/rule-add.py route --at 9 \
        --rule '{"domain_suffix":["example.com"],"action":"route","outbound":"🚀 Proxy"}' \
        --note "example.com 走代理"

    # 只预览，不写盘
    python tools/rule-add.py route --at 9 --rule '{...}' --dry-run

## 它自动做什么

1. **三端同步**：`profiles/1.14/{desktop,android,ios}-lazy.json` 同一位置插入同一条规则
2. **自动同步文档**（只同步「可生成」的部分，不碰散文）：
   - `docs/CONFIG-ANATOMY.md` §4 / §3.2 的规则表（从 JSON 重新生成）
   - `docs/PLATFORM-MATRIX.md` 里「N 条」的数字
3. **跑门禁**：`audit.py`（静态）+ 逐份 `sing-box check`

## 它**不**做什么（刻意的）

- **不写决策记录**（`DECISIONS.md`）—— 那是"为什么"，机器写不出来。
  工具会**提醒**你去写，并给出模板。
- **不加门禁** —— 「这条规则将来被删掉谁会发现」需要人判断。
  工具会**提醒**你考虑，并列出与它同类的已有门禁做参照。
- **不跑 `--run`**（启动级验证）—— 那要 85 秒，留给提交前跑一次。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles" / "1.14"
PLATFORMS = ("desktop", "android", "ios")

ANATOMY = ROOT / "docs" / "CONFIG-ANATOMY.md"
PMATRIX = ROOT / "docs" / "PLATFORM-MATRIX.md"


class RuleError(Exception):
    """用户可读的错误。"""


def load(plat):
    p = PROFILES / f"{plat}-lazy.json"
    if not p.exists():
        raise RuleError(f"找不到 {p.relative_to(ROOT)}")
    return p, json.loads(p.read_text(encoding="utf-8"))


def save(p, cfg):
    """原子写 + 保留 4 空格缩进 + 尾换行（与仓库既有风格一致）。"""
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + "\n",
                   encoding="utf-8", newline="")
    tmp.replace(p)


def insert_rule(sec_rules, at, rule):
    """在 `at` 位置插入；越界则报错（不猜）。"""
    if at < 0 or at > len(sec_rules):
        raise RuleError(f"位置 {at} 越界（当前 {len(sec_rules)} 条，合法范围 0..{len(sec_rules)}）")
    out = list(sec_rules)
    out.insert(at, rule)
    return out


# ── 文档同步：只重生成「可生成」的表格，不碰散文 ──────────────────

def _rule_desc(r):
    """把规则压成表格「内容」列的人读形式。"""
    act = r.get("action", "route")
    rest = {k: v for k, v in r.items() if k != "action"}
    if act == "route" and "outbound" in rest:
        ob = rest.pop("outbound")
        if rest:
            return f"{json.dumps(rest, ensure_ascii=False)} → `{ob}`"
        return f"→ `{ob}`"
    if rest:
        return json.dumps(rest, ensure_ascii=False)
    return "——"


def sync_anatomy_table(cfg, doc_text, section, at, new_rule):
    """在 §4（route）或 §3.2（dns）的表格里**插入一行**，并把后续行号顺延。

    ⚠️ **不整表重生成**：那张表是 **4 列**，最后一列「说明」是**人工写的**
    （如"封 QUIC/HTTP3"、"★ 必须在所有 route/reject 之前"）。
    机器重生成会抹掉它们 —— 那是信息损失，比不同步更坏。
    """
    if section == "route":
        head_re = r"## 4\. 路由层 `route\.rules`.*?\n\n\| # \| action \| 内容 \| 说明 \|\n\|[^\n]*\|\n"
    else:
        head_re = r"### 3\.2 `dns\.rules`.*?\n\n\| # \| action \| 匹配 \| 结果 \|\n\|[^\n]*\|\n"

    m = re.search(head_re, doc_text, re.S)
    if not m:
        raise RuleError(
            f"在 CONFIG-ANATOMY.md 里找不到 {section} 的规则表格（格式变了？）—— "
            "**未写盘**。请手工同步该表，或修正本工具的正则")

    head_end = m.end()
    # 收集现有数据行
    rows = []
    pos = head_end
    for line in doc_text[head_end:].splitlines(keepends=True):
        if not line.startswith("|"):
            break
        rows.append(line)
        pos += len(line)

    # 解析每行的 (序号, 内容) —— 说明列保留
    parsed = []
    for line in rows:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            raise RuleError(f"表格行格式异常（不足 4 列）：{line.strip()[:60]}")
        parsed.append(cells)

    # 插入新行：内容列由 JSON 生成，说明列留待补写
    desc = _rule_desc(new_rule)
    parsed.insert(at, [str(at), f"`{new_rule.get('action', 'route')}`", desc, "—— **待补写说明**"])

    # 序号统一顺延
    out_rows = "".join(
        "| " + " | ".join([str(i)] + c[1:]) + " |\n"
        for i, c in enumerate(parsed)
    )
    return doc_text[:head_end] + out_rows + doc_text[pos:]


def sync_count(text, path, label, quiet=False):
    """把「（N 条）」里的数字改成实际条数。"""
    n = len(path)
    new, cnt = re.subn(r"（\d+ 条）", f"（{n} 条）", text, count=1)
    if cnt and not quiet:
        print(f"    [自动] {label}: 条数 → {n}")
    return new


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT), **kw)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="加一条 route/dns 规则（三端同步 + 自动同步文档 + 跑门禁）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section", choices=("route", "dns"), help="加哪一层")
    ap.add_argument("--at", type=int, required=True, help="插入位置（0-based，含义见 CONFIG-ANATOMY）")
    ap.add_argument("--rule", required=True, help="规则 JSON（单行）")
    ap.add_argument("--note", help="一句话说明（仅用于提示语，不写进配置）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写盘")
    args = ap.parse_args()

    try:
        rule = json.loads(args.rule)
    except json.JSONDecodeError as ex:
        raise RuleError(f"--rule 不是合法 JSON：{ex}")
    if not isinstance(rule, dict):
        raise RuleError("--rule 必须是一个 JSON 对象")

    # 三端读入
    cfgs = {}
    for plat in PLATFORMS:
        p, cfg = load(plat)
        cfgs[plat] = (p, cfg)

    # 先校验三端结构一致（避免"只改了两端"这类事故）
    n0 = len(cfgs["desktop"][1][args.section]["rules"])
    for plat in PLATFORMS[1:]:
        n = len(cfgs[plat][1][args.section]["rules"])
        if n != n0:
            raise RuleError(f"三端 {args.section}.rules 条数不一致：desktop={n0} {plat}={n}"
                            " —— 先修好再来加规则")

    print(f"═══ 加规则 ═══")
    print(f"  层次   {args.section}")
    print(f"  位置   {args.at}")
    print(f"  规则   {json.dumps(rule, ensure_ascii=False)}")
    if args.note:
        print(f"  说明   {args.note}")
    print(f"  三端   当前 {n0} 条 → 插入后 {n0 + 1} 条")

    # 插入
    for plat in PLATFORMS:
        p, cfg = cfgs[plat]
        cfg[args.section]["rules"] = insert_rule(cfg[args.section]["rules"], args.at, dict(rule))

    if args.dry_run:
        print("\n--- dry-run：未写盘 ---")
        for plat in PLATFORMS:
            p, cfg = cfgs[plat]
            print(f"  {p.relative_to(ROOT)}")
            for i, r in enumerate(cfg[args.section]["rules"]):
                mark = " ← 新增" if i == args.at else ""
                print(f"     [{i:>2}] {json.dumps(r, ensure_ascii=False)[:76]}{mark}")
        return 0

    # ⚠️ **先算好全部要写的内容，任何一个失败就整体不写盘** ——
    # 原实现先写 JSON 再同步文档，文档同步一失败就留下「配置改了、文档没改」
    # 的半成品。这与 patch-text 的原子写是同一个道理：要么全成，要么全不动。
    print("\n═══ 准备改动（先验证，暂不落盘）═══")
    doc = ANATOMY.read_text(encoding="utf-8")
    doc2 = sync_anatomy_table(cfgs["desktop"][1], doc, args.section, args.at, rule)
    pm = PMATRIX.read_text(encoding="utf-8")
    pm2 = sync_count(pm, cfgs["desktop"][1][args.section]["rules"],
                     "PLATFORM-MATRIX.md", quiet=True)
    print("    [ok] 三端 JSON")
    print(f"    [{'ok' if doc2 != doc else '--'}] CONFIG-ANATOMY.md")
    print(f"    [{'ok' if pm2 != pm else '--'}] PLATFORM-MATRIX.md")

    # 全部算完，再落盘
    print("\n═══ 写盘 ═══")
    for plat in PLATFORMS:
        p, cfg = cfgs[plat]
        save(p, cfg)
        print(f"    [写] {p.relative_to(ROOT)}")
    if doc2 != doc:
        ANATOMY.write_text(doc2, encoding="utf-8", newline="")
        print("    [写] docs/CONFIG-ANATOMY.md")
    if pm2 != pm:
        PMATRIX.write_text(pm2, encoding="utf-8", newline="")
        print("    [写] docs/PLATFORM-MATRIX.md")

    # 门禁
    print("\n═══ 跑门禁 ═══")
    r = run([sys.executable, "tools/audit.py"])
    tail = [l for l in (r.stdout + r.stderr).splitlines() if "合计" in l or l.startswith("[E]")]
    for l in tail[:12]:
        print("   ", l)
    if r.returncode != 0:
        print("\n  ❌ 门禁未通过 —— 先看上面的 [E] 行")
        return 1
    print("    ✅ 静态门禁通过")

    # 提醒（机器做不了的部分）
    print("\n═══ 还需要你做的（机器判断不了）═══")
    print("  ① 决策记录：为什么加这条？被否决的备选？风险？")
    print("     → 写进 docs/DECISIONS.md（下一个编号）")
    print("  ② 门禁：「这条将来被删掉，谁会发现？」")
    print("     → 若答不上来，就该加门禁（参考 quic_block_missing 那对）")
    print("  ③ 提交前跑一次全量（含启动级）：")
    print("     bash tools/check-all.sh --run")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuleError as ex:
        print(f"[E] {ex}", file=sys.stderr)
        sys.exit(2)
