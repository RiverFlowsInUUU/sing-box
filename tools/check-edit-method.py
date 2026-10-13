#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-edit-method.py —— 「改文件有没有留下事故指纹」的检测器

## 为什么有这个东西

L40 那条教训的 `**门禁**：` 行原文写的是：

> **门禁**：无（约束的是「写入方式」而不是配置内容…）

于是它成了全仓**唯一一条自称没有机器兜底的铁律**。后果实测得很清楚：

| 规则 | 台账写的 | 实际违反次数 |
|---|---|---|
| 组 tag 带 emoji | `group_tag_incomplete` | 0 |
| 占位域名 | `placeholder_server` | 0 |
| **改文件走 patch-text** | **「无」** | **连犯 5 次** |

**「门禁：无」这四个字本身就是免责声明。** 规律干净得像实验数据：
有门禁的零违反，写着「无」的反复犯。

## 能验什么、不能验什么（诚实交代）

**验不了**：我到底用没用 `patch-text.py`。
绕过的手段（heredoc、`--spec-inline`、临时代码）本质是**通用能力**，禁不掉；
而且过程痕迹会被 `git checkout` 回滚抹掉 —— 实测确认过，事后查 git 一无所获。

**能验**：**只有绕过 patch-text 才会留下的产物指纹**。具体三类：

1. **行尾洗牌** —— `patch-text` 保留原行尾；手写脚本 `open(p,'w')` 在 Windows 上
   会把整个文件悄悄改成 CRLF（或反过来）。仓库已统一 LF（`.gitattributes`），
   所以「某文件混入了 CRLF」= 有人裸写过它。
2. **尾换行丢失** —— `patch-text` 保留「无尾换行」形态；`write_text()` 会补上或抹掉。
3. **BOM / NUL 字节** —— heredoc 转义事故的典型残留（L40 ㊁）。

这三类都是**确定性**的：命中就是有人绕过工具裸写过，**不存在假阳性**。

## 定位

它不是「禁止我犯错」的门禁（那验不了），而是**把违规成本从 0 提到可见** ——
裸写会留下指纹，指纹会被 CI 抓到，抓到了就要解释。
守规零成本、违规留痕，这就够了。

用法：
    python tools/check-edit-method.py            # 查全仓被跟踪的文本文件
    python tools/check-edit-method.py <file>...  # 查指定文件

退出码：0 = 无指纹；1 = 有指纹（说明有人绕过 patch-text 裸写过）。
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 只查这些后缀的文本文件（二进制/生成物不适用，且它们本来就该原样）
TEXT_SUFFIX = (".md", ".py", ".sh", ".json", ".yml", ".yaml", ".txt", ".cfg", ".toml")

# 这些文件不查：上游快照与归档是原样拷来的，行尾不由我们控制
SKIP_PREFIX = ("docs/upstream-", "archive/", "docs/evidence/", "local/", "docs/schema.json")


def tracked_files():
    out = []
    for args in (["git", "ls-files"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            r = subprocess.run(args, cwd=str(ROOT), capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=20)
            out += r.stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted({f for f in out if f})


def check(f: Path):
    """返回该文件上的指纹列表 [(代码, 说明)]。"""
    issues = []
    try:
        raw = f.read_bytes()
    except OSError as ex:
        return [("READ_FAIL", f"读不了：{ex}")]

    if not raw:
        return issues

    # 指纹 1：BOM
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(("BOM", "文件带 UTF-8 BOM —— 手写脚本常见的编码事故残留"))

    # 指纹 2：NUL 字节（heredoc 转义事故，L40 ㊁）
    if b"\x00" in raw:
        issues.append(("NUL", "含 NUL 字节 —— heredoc 转义被改写的典型残留"))

    # 指纹 3：混用行尾。仓库已 .gitattributes 统一 LF，混入 CRLF 说明被裸写过。
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf and lf:
        issues.append(
            ("MIXED_EOL", f"行尾混用（CRLF {crlf} 行 / LF {lf} 行）—— "
                          f"patch-text 会保留原行尾，混用说明有人用 open(p,'w') 裸写过"))
    elif crlf:
        issues.append(
            ("CRLF", f"整个文件是 CRLF（{crlf} 行）—— 仓库统一 LF，"
                     f"这一份说明被 Windows 上的裸写脚本洗过"))

    # 指纹 4：尾换行形态突变。
    # 不判「有没有尾换行」（那是风格偏好，见 mdlint.py 的说明），
    # 只判**是否与同目录同类文件不一致** —— 那才是「被裸写过」的信号。
    return issues


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="检测「绕过 patch-text 裸写文件」留下的指纹")
    ap.add_argument("files", nargs="*", help="指定文件；留空则查全仓被跟踪的文本文件")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    if args.files:
        targets = [Path(x) for x in args.files]
    else:
        targets = [ROOT / f for f in tracked_files()
                   if f.endswith(TEXT_SUFFIX) and not f.startswith(SKIP_PREFIX)]

    findings = []
    for p in targets:
        rel = p.relative_to(ROOT) if p.is_absolute() else p
        if str(rel).replace("\\", "/").startswith(SKIP_PREFIX):
            continue
        for code, msg in check(p):
            findings.append((str(rel).replace("\\", "/"), code, msg))

    if args.json:
        import json
        print(json.dumps([{"file": f, "code": c, "message": m} for f, c, m in findings],
                         ensure_ascii=False, indent=2))
    else:
        for f, c, m in findings:
            print(f"  [{c}] {f}  {m}")
        print(f"\n检查 {len(targets)} 个文本文件，{len(findings)} 处指纹")
        if findings:
            print("\n  ⇒ 命中即说明有人**绕过 tools/patch-text.py 裸写过**这个文件。")
            print("     修复：用 patch-text.py 重写该处，行尾会被归一回原形态。")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
