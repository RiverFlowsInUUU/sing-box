"""活文档 / CI 文件里不得硬编码**当前**的负向用例数。

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

判别不是「禁止所有数字」，而是「**这个数字在陈述当前值，还是在记述历史**」：

· 历史记述（「当时砍成 28/28 全绿的报告看不见」「29/29」）—— **豁免**。
  它们是**当时的事实**，改了就是篡改记载（本仓既有原则：历史台账豁免）。
· 陈述当前值（「实测是 67」「实际有 2 个用例」）—— **报错**。
  这类数字会漂，而且**没有任何东西会发现它漂了** —— 这正是本条存在的理由。

范围：`_tracked_files()` 里的活文档与 CI 文件；
`docs/LESSONS.md` / `docs/DECISIONS.md` 整文件豁免（追加型历史记录）。
**`tools/` 整目录排除** —— 门禁的实现与注释必须能写出「实测是 N 个用例」
这样的字面量才能描述它要抓什么，扫它就变成自噬（第三次踩这个坑）。

2026-10-19 单独成模块的原因：写进 `audit.py` 时两次被 shell heredoc 吃掉
反斜杠导致语法错误。**用编辑器直接写文件，绕过 shell 转义层。**
"""

import re

# 历史语气：出现这些词，说明该数字是「当时」而非「当前」
HISTORICAL = (
    "当时", "曾经", "以前", "历史", "那次", "早期", "原本", "过去",
    "全绿」的报告", "看不到", "此前", "已增至", "以前是", "曾为",
)

# 数字 + 用例语境
PAT = re.compile(
    r"\d+\s*/\s*\d+"
    r"|\d+\s*个用例"
    r"|用例数[^\n]{0,8}?\d+"
    r"|\d+\s*个\s*case"
)

CTX = ("用例", "negtest", "全绿", "CASES")

EXEMPT_FILES = ("docs/LESSONS.md", "docs/DECISIONS.md")


def scan(tracked_files, root):
    """返回 [(文件, 行号, 命中的数字串, 该行摘要)]。

    `tracked_files` 由调用方给（复用 audit.py 的 `_tracked_files()`，
    它同时含已跟踪与未 add 的新文件 —— L29）。
    """
    found = []
    for f in tracked_files:
        if f in EXEMPT_FILES:
            continue
        # 门禁自己的源码排除：它必须能写出被检字面量才能描述要抓什么。
        if f.startswith("tools/"):
            continue
        if not f.endswith((".md", ".yml", ".yaml")):
            continue
        try:
            text = (root / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not any(c in line for c in CTX):
                continue
            m = PAT.search(line)
            if not m:
                continue
            if any(h in line for h in HISTORICAL):
                continue
            found.append((f, i, m.group(0), line.strip()[:70]))
    return found
