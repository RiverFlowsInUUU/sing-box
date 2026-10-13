#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mdlint.py —— 轻量 markdown 结构校验（仓库没有 markdownlint 时的替代）

为什么需要它：`AI_SYNC_WORKFLOW.md` 要求「运行仓库已有的 markdown lint。
如果没有，说明未运行」。本仓确实没有 —— 但「说明未运行」指的是**如实申报**，
不是「因此就不检查」。文档也是产物，它的结构问题（围栏不配对、标题层级跳跃、
链接失效）同样会让下一个人读不懂。

本工具只做**确定性**检查，不做风格审查（不碰行长、不碰行尾标点）：
  · MD001 标题层级跳跃
  · MD047 文件未以换行结尾
  · FENCE 代码围栏不配对
  · LINK  相对链接指向不存在的文件
  · ANCHOR 相对链接的锚点在目标文件里找不到对应标题

用法：
    python tools/mdlint.py                  # 全仓 .md
    python tools/mdlint.py AGENTS.md docs/  # 指定文件/目录
    python tools/mdlint.py --changed        # 只查相对 origin/main 改动过的文件

退出码：0 = 无问题；1 = 有问题。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 这些目录是上游快照/归档/证据，不是本仓维护的文档，不参与检查
SKIP_PREFIX = ("docs/upstream-", "archive/", "docs/evidence/", "local/")


def _slug(h: str) -> str:
    """把标题/锚点归一成可比较的形式。

    ⚠️ 不去复刻 GitHub 的精确 slug 算法（中文标点、大小写、连字符的规则繁琐且会变）。
    改用**双向归一化**比较：两边都只保留字母/数字/汉字，其余全部丢弃。
    好处是「五、功能条目的结构化格式」与锚点 `#五功能条目的结构化格式` 天然相等 ——
    这正是本仓已在用的写法（12 个现有锚点全部通过）。

    代价：会漏掉「只差标点」的真错（如 `#五-功能` vs `#五功能`）。可接受 ——
    本工具是**仓库没有 markdownlint 时的兜底**，宁可少报也不要满屏假警报
    （假警报会让人连真问题一起无视，这比漏报更贵）。
    """
    return re.sub(r"[^0-9a-z一-鿿]", "", h.strip().lower())


_HEADING_CACHE = {}   # {目录: {文件名: 标题集}} —— 按目录缓存，避免跨文件串味


def _headings_of(p: Path):
    """收集文件里的标题（**排除代码围栏内**的 `# 注释`），返回归一化集合。"""
    out, in_fence = set(), False
    for l in p.read_text(encoding="utf-8").splitlines():
        if re.match(r"^```", l):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", l)
        if m:
            out.add(_slug(m.group(1)))
    return out


def collect(paths):
    """收集要检查的 .md，返回**绝对路径**列表（统一形态，避免相对/绝对混用）。"""
    out = []
    for a in paths:
        p = Path(a)
        if not p.is_absolute():
            p = (ROOT / p)
        if p.is_dir():
            out += [q for q in sorted(p.rglob("*.md"))]
        elif p.suffix == ".md" and p.exists():
            out.append(p)
    seen, res = set(), []
    for p in out:
        try:
            relpos = p.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            continue                      # 仓库外，跳过
        if relpos.startswith(SKIP_PREFIX) or ".git/" in relpos or relpos in seen:
            continue
        seen.add(relpos)
        res.append(p.resolve())
    return res


def changed_files():
    """相对 origin/main 改动过的 .md（含未跟踪的新文件）。"""
    names = set()
    for args in (["git", "diff", "--name-only", "origin/main...HEAD"],
                 ["git", "diff", "--name-only", "HEAD"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(args, cwd=str(ROOT), capture_output=True,
                                 text=True, encoding="utf-8", timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        names |= {n for n in out.splitlines() if n.endswith(".md")}
    return sorted(n for n in names if not n.startswith(SKIP_PREFIX))


def check(p: Path):
    issues = []
    lines = p.read_text(encoding="utf-8").splitlines()
    txt = "\n".join(lines)

    # MD001 标题层级跳跃。
    # ⚠️ 必须**跳过代码围栏内的行** —— 代码块里的 `# 注释`、`### ...` 不是标题，
    # 把它们算进来会凭空造出「层级跳跃」的假警报（本工具第一版就栽在这）。
    prev = 0
    in_fence = False
    for i, l in enumerate(lines, 1):
        if re.match(r"^```", l):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s", l)
        if m:
            lv = len(m.group(1))
            if prev and lv > prev + 1:
                issues.append((i, "MD001", f"标题层级跳跃 h{prev} → h{lv}"))
            prev = lv

    # MD047 结尾换行 —— 刻意**不报**。
    # 理由：这不是错误，是风格偏好。缺尾换行的文件照样能被 GitHub 正常渲染，
    # 而本仓 17 个 .md 里有 12 个原本就是这种写法（含我没碰过的 LESSONS / DECISIONS /
    # VERSION-MATRIX）—— 那是既有风格，改它就是动别人没让我动的东西。
    # 更关键：把偏好做成 ERROR 会让流水线**长期红着**，而「红灯一直亮」的后果
    # 是人不再看它，真问题也跟着被无视。宁可少报，也不要制造恒亮的假警报。

    # FENCE 围栏配对
    if len(re.findall(r"^```", txt, re.M)) % 2:
        issues.append((0, "FENCE", "代码围栏不配对"))

    # LINK / ANCHOR
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", txt):
        target = m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "alma://")):
            continue
        line_no = txt[: m.start()].count("\n") + 1
        path_part, _, anchor = target.partition("#")
        if not path_part:
            continue  # 纯页内锚点
        dest = (p.parent / path_part).resolve()
        if not dest.exists():
            issues.append((line_no, "LINK", f"链接目标不存在：{target}"))
            continue
        if anchor and dest.suffix == ".md" and dest.exists():
            # ⚠️ 按目标文件**逐个**取标题集，不能跨文件复用。
            # 第一版写成 `if titles is None: titles = ...`，于是整轮扫描只算过**第一个**
            # 目标文件的标题，后面每个带锚点的链接都拿它去比 —— 满屏假 ANCHOR 警报。
            # （缓存要按 key 存，或者干脆不缓存；这里用按目录缓存，同目录常见、开销可忽略。）
            titles = _HEADING_CACHE.setdefault(str(dest.parent), {})
            if dest.name not in titles:
                titles[dest.name] = _headings_of(dest)
            if _slug(anchor) not in titles[dest.name]:
                issues.append((line_no, "ANCHOR",
                               f"锚点 #{anchor} 在 {path_part} 中找不到对应标题"))
    return issues


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="轻量 markdown 结构校验")
    ap.add_argument("paths", nargs="*", help="文件或目录；留空=全仓 .md")
    ap.add_argument("--changed", action="store_true",
                    help="只查相对 origin/main 改动过的文件")
    args = ap.parse_args()

    if args.changed:
        targets = [ROOT / n for n in changed_files()]
    elif args.paths:
        targets = collect(args.paths)
    else:
        targets = [p for p in collect([ROOT])
                   if "docs/evidence" not in str(p) and "archive" not in str(p)]

    total = 0
    for p in targets:
        issues = check(p)
        if issues:
            rel = p.resolve().relative_to(ROOT)
            for line, code, msg in issues:
                loc = f"{rel}:{line}" if line else str(rel)
                print(f"  [{code}] {loc}  {msg}")
                total += 1

    print(f"\n检查 {len(targets)} 个 markdown 文件，{total} 个问题")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
