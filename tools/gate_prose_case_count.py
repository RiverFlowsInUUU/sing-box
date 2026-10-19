"""活文档 / CI 文件里不得把**当前**的负向用例数当成常量写下来。

## 事故

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

## 判据的演进（每一版都是被复核指出后重做）

**v1 整行含历史词 ⇒ 整行豁免。** 第五轮 P3-A：同一行里出现「当时 / 此前 / 看不到」
就能把当前值数字一起豁免；词表是照着当前语料凑的。
**v2 判到子句 + 混写单独报。** 实测更糟：误报了已存在的正确文字，
5 种注入全报同一结果（区分能力为零）。→ 撤回。
**v3 不判语义，只扫「声称当前值」的显式句式。** 事故句「实测是 67」有
不需要判断的特征 —— 它是显式的当前值措辞。
**v4 补比率与计数措辞。** 第六轮 P3-1：`68/68 全部命中` 是本仓最自然的写法，
v3 整类放掉；且规则文字（「不写进任何文本」）比实现宽。
**v5 判据 ④ 加「位置 + 数值」两层约束。** 第七轮 P3-2：写个日期就假报。
**v6 补 CTX 的「命中/跑完/跑出来」。** 第八轮 P3-2：`本轮 68/68 全部命中` 被
行级前置过滤跳过。**但这一改放进了新假报面**（第九轮 P3-①）：
`本轮命中 10/19` / `现在命中 12/20 个探测点` / `本次跑完 3/15 条路径`
—— 5 条自然写法全部新报错，而它们都不是在说用例数。

**v7（现在）：把「④ 的语境依据」与「行级 CTX」分开设计。**

根本问题：**「命中」既是本仓口头禅（`68/68 全部命中`），也是别的指标的动词
（`命中 10/19 个探测点`）。** 光看「有没有这个词」分不出来，要看**它和比率的位置关系**：

| 写法 | 判定 |
|---|---|
| `本轮负向回归 68/68 全部命中。` | 子句有「负向回归」→ **明确指代** → 算 |
| `本轮 68/68 全部命中。` | 比率**在「命中」之前**，子句无别的名词 → 算 |
| `现在跑出来是 68/68 全绿。` | 「全绿」在本仓只用于负向回归 → 算 |
| `本轮命中 10/19，其它照旧。` | 「命中」**在比率之前** → 它在修饰比率（X/Y 的命中率）→ **不算** |
| `现在命中 12/20 个探测点。` | 同上，且「探测点」明示指标 → **不算** |
| `本次跑完 3/15 条路径。` | 「跑完」在比率之前 → **不算**（COUNT 也要排除 `3/15 条` 这种） |

**行级 `CTX` 维持宽** —— 它服务于 ①②③，那三条的语境由「句式」或
「真值比对」保证，不需要靠 CTX 判别是不是用例数。

范围：`_tracked_files()` 里的活文档与 CI 文件；
`docs/LESSONS.md` / `docs/DECISIONS.md` 整文件豁免（追加型历史记录）。
**`tools/` 整目录排除** —— 门禁的实现与注释必须能写出被检字面量才能描述要抓什么。

真值来源：调用方传入（`audit.py` 用 `ast` 取 `CASES` 字面量长度）。
拿不到真值时只做 ①②，**不做 ③④**（宁可少查，不要瞎报）。
"""

import re

# ① 显式「声称当前值」的措辞 —— 写了就报，不做任何历史推断。
ASSERT_CURRENT = re.compile(
    r"(实测|实测值)\s*(是|为|达到|有)\s*(\d{1,5})\s*(个)?\s*用例"
    r"|(现在|目前|当前)\s*(是|为|有|已经?有?)\s*(\d{1,5})\s*(个)?\s*用例"
    r"|用例数\s*(是|为|达到)\s*(\d{1,5})"
)

# ② 「已增至」类 —— 天然当前口吻
INCREASED = re.compile(r"(已增至|增至|增加到|提升到)\s*(\d{1,5})")

# ③ 计数措辞（正装 + 倒装 + 条/case）
#    ⚠️「N 条」排除「X/Y 条」那种分式（`3/15 条路径` 里的 `15 条` 不是清单计数）
COUNT = re.compile(
    r"(?<![/\d])(\d{1,5})\s*个\s*(?:用例|case)"
    r"|用例\s*(\d{1,5})\s*个"
    r"|(?<![/\d])(\d{1,5})\s*条"
)

# ④ 比率写法 + 当前口吻词
RATIO = re.compile(r"(\d{1,5})\s*/\s*(\d{1,5})")
CURRENT_WORDS = ("现在", "目前", "当前", "本轮", "本次", "这次")

# 行级前置过滤：宽（服务于 ①②③）。**不用于 ④ 的语境判定。**
CTX = ("用例", "negtest", "CASES", "负向回归", "负向用例", "全绿",
       "命中", "跑完", "跑出来")

# ── ④ 专用的子句依据（第九轮收紧）──────────────────────────────
# 明确指向用例数的短语 → 无条件算
CASE_CLAUSE_WORDS = ("用例", "negtest", "CASES", "负向回归", "负向用例")
# 「全绿」在本仓只用于负向回归 → 无条件算
CASE_CLAUSE_STRICT = ("全绿",)
# 「命中」/「跑完」：只有在比率**之后**才指向用例数
CASE_CLAUSE_AFTER = ("命中", "跑完", "跑出来")

# 比率分母的合理区间（用例数不会是个位数，也不会到四位数）
_RATIO_DEN_MIN = 10
_RATIO_DEN_MAX = 999

# 子句切分：中文句读 + 括号
_CLAUSE_SPLIT = re.compile(r"[，。；;、（）()「」\[\]]")


def _clause_span(line, pos):
    """返回包含 pos 的子句的 (start, end)。"""
    start = 0
    for m in _CLAUSE_SPLIT.finditer(line):
        if m.end() <= pos:
            start = m.end()
        elif m.start() > pos:
            return start, m.start()
    return start, len(line)


def _clause_containing(line, pos):
    a, b = _clause_span(line, pos)
    return line[a:b]


def _ratio_is_about_cases(line, m):
    """④ 的语境判定：这个比率在说用例数吗？

    三种「算」：
      ① 子句里有明确用例指代（用例 / negtest / 负向回归 …）
      ② 子句里有「全绿」（本仓只用于负向回归）
      ③ 子句里有「命中 / 跑完 / 跑出来」，**且它在比率的「之后」**
         （`68/68 全部命中` ✓  vs  `命中 10/19` ✗）
    """
    a, b = _clause_span(line, m.start())
    cl = line[a:b]
    if any(w in cl for w in CASE_CLAUSE_WORDS):
        return True
    if any(w in cl for w in CASE_CLAUSE_STRICT):
        return True
    # 比率在该子句内的相对位置（0 = 子句开头）
    rel_end = (m.end() - a)
    for w in CASE_CLAUSE_AFTER:
        idx = cl.find(w)
        if idx >= 0 and idx >= rel_end:
            return True
    return False


def scan(tracked_files, root, actual_count=None):
    """返回 [(文件, 行号, 命中的数字串, 该行摘要, 原因)]。

    原因：
      "assert_current"  句式①（显式声称当前值）
      "increased"       句式②（已增至）
      "count_mismatch"  句式③（计数措辞且 ≠ 真值）
      "ratio_mismatch"  句式④（当前口吻 + 语境指向用例数的 X/Y 且分母 ≠ 真值）
    """
    found = []
    for f in tracked_files:
        if f in EXEMPT_FILES:
            continue
        # 门禁自己的源码排除：实现与注释必须能写出被检字面量才能描述要抓什么。
        if f.startswith("tools/"):
            continue
        if not f.endswith((".md", ".yml", ".yaml")):
            continue
        try:
            with (root / f).open(encoding="utf-8", newline="") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not any(c in line for c in CTX):
                continue
            # ①② 无论真值是否可得都能判
            m = ASSERT_CURRENT.search(line) or INCREASED.search(line)
            if m:
                why = ("assert_current" if ASSERT_CURRENT.search(line)
                       else "increased")
                found.append((f, i, m.group(0).strip(), line.strip()[:70], why))
                continue
            if actual_count is None:
                continue
            # ③ 计数措辞 ≠ 真值
            hit = None
            for m in COUNT.finditer(line):
                n = _first_int(*m.groups())
                if n is not None and n != actual_count:
                    hit = (m.group(0).strip(), "count_mismatch")
                    break
            # ④ 当前口吻 + 语境指向用例数的比率分母 ≠ 真值
            if hit is None and any(w in line for w in CURRENT_WORDS):
                for m in RATIO.finditer(line):
                    num, den = int(m.group(1)), int(m.group(2))
                    # 数值形态得像用例数
                    if num > den or not (_RATIO_DEN_MIN <= den <= _RATIO_DEN_MAX):
                        continue
                    # 语境：这个比率在说用例数吗
                    if not _ratio_is_about_cases(line, m):
                        continue
                    if den != actual_count:
                        hit = (m.group(0).strip(), "ratio_mismatch")
                        break
            if hit:
                found.append((f, i, hit[0], line.strip()[:70], hit[1]))
    return found


def _first_int(*groups):
    for g in groups:
        if g:
            return int(g)
    return None


# 整文件豁免：追加型历史记录（本仓既有原则）
EXEMPT_FILES = ("docs/LESSONS.md", "docs/DECISIONS.md")
