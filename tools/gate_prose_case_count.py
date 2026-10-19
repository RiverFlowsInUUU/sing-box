"""活文档 / CI 文件里不得把**当前**的负向用例数当成常量写下来。

## 事故

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

## 判据的演进（每一版都是被复核指出后重做）

v1 整行含历史词 ⇒ 整行豁免 → 第五轮 P3-A：同一行的历史词能解掉当前值数字
v2 判到子句 + 混写单独报 → 实测更糟（误报正确文字、区分能力为零）→ 撤回
v3 只扫「显式声称当前值」的句式
v4 补比率与计数措辞（第六轮 P3-1：`68/68 全部命中` 整类被放掉）
v5 ④ 加「位置 + 数值」约束（第七轮 P3-2：写个日期就假报）
v6 补行级 CTX 的「命中/跑完/跑出来」（第八轮 P3-2）
   → **但放进了新假报面**（第九轮 P3-①：`本轮命中 10/19` 等 5 条）
v7 **把「行级 CTX」与「④ 的语境依据」拆开设计**，④ 改判「位置关系」

**v8（现在）：第十轮复核发现还在用「词面邻近」代替「指代」——**

| 病 | 实测假报 | 修法 |
|---|---|---|
| ③ 的 `N 条` 完全没指代校验 | 6 条（`第 3 条门禁` / `新增 12 条规则` / `2 条失败` / `白名单 47 条` / `广告 3901 条` …） | **删掉这一支**，只保留 `N 条用例` |
| ④(a) 比率与「命中」之间夹了别的名词 | `12/20 个文件全部命中` / `12/20 个探测点命中` / `3/15 条路径全部命中` | 要求两者**相邻**（中间无别名词） |
| ④(b) 「全绿」当成负向回归专用词 | `本轮覆盖 12/20 个域名全绿` | **删掉这条断言** —— 它与语料不符 |

### 关于「删掉」而不是「继续加校验」的判断

③ 的 `N 条` 分支：假报面 6 条、**真实收益 0 条**（复核的 6 条全是别的指标；
活文档里指用例数时几乎总写成 `N 条用例`）。
→ **本仓对判据的验收标准是「干净时安静（false positive 为零）」**，
   所以砍掉一个「抓不到真、却抓一堆假」的分支，比给它加指代校验更符合标准。

④(b) 「全绿」：我在代码注释里断言「本仓**只**用于负向回归」——
**而这是一条没有跑过语料的断言**。复核去查了：
`docs/AI_SYNC_WORKFLOW.md:37`「工具语法错也能全绿」、
`docs/PROTOCOL-MAPPING.md:264`「跑 audit.py … 全绿」。
→ 与我在上一轮报告里立的「写进报告的行为声明，必须是跑出来的」直接冲突。
   **断言「某词只用于 X」之前，先 grep 一遍语料。**

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

# ③ 计数措辞：**只保留指代明确的两支**。
#    ⚠️ 第十轮复核 P3-①：以前这里有「`N 条`」一支，而「条」后面跟什么名词它不看。
#       实测 6 条假报（第 N 条门禁 / 新增 N 条规则 / N 条失败 /
#       白名单放行（47 条）/ 广告拦截（3901 条）…），**真实收益 0 条**。
#       → 砍掉。活文档里指用例数时几乎总写成「N 条用例」。
COUNT = re.compile(
    r"(?<![/\d])(\d{1,5})\s*个\s*(?:用例|case)"
    r"|用例\s*(\d{1,5})\s*个"
    r"|(?<![/\d])(\d{1,5})\s*条\s*用例"
)

# ④ 比率写法 + 当前口吻词
RATIO = re.compile(r"(\d{1,5})\s*/\s*(\d{1,5})")
CURRENT_WORDS = ("现在", "目前", "当前", "本轮", "本次", "这次")

# 行级前置过滤：宽（服务于 ①②③）
CTX = ("用例", "negtest", "CASES", "负向回归", "负向用例", "全绿",
       "命中", "跑完", "跑出来")

# ── ④ 专用的子句依据 ─────────────────────────────────────────
# 明确指向用例数的短语 → 无条件算
CASE_CLAUSE_WORDS = ("用例", "negtest", "CASES", "负向回归", "负向用例")
# 「命中」/「跑完」/「跑出来」/「全绿」：只有在比率**之后且紧邻**才指向用例数
#
# ⚠️ 「全绿」这里有个来回（第十轮复核 P3-②(b) 及其回归）：
#    · 我原来断言「全绿在本仓**只**用于负向回归」→ **断言错了**
#      （「工具语法错也能全绿」说的是整套门禁；
#       「跑 audit.py … 全绿」也是）
#    · 但**不能因此就把它整条删掉** ——  确实在说用例数。
#    → 它和「命中」是同一类词：**位置对时算，位置不对/中间夹名词时不算。**
#      故放进 AFTER（要求出现在比率之后且中间无别的指标名词）。
CASE_CLAUSE_AFTER = ("命中", "跑完", "跑出来", "全绿")

# ④ 的「紧邻」容差：比率之后到这之间，只允许出现这些（空白 / 标点 / 「全部」「都」）
_SEP_OK = re.compile(r"^[\s，、：:（）()「」『』]*?")

# 别的指标名词：出现在比率与「命中」之间 ⇒ 该比率说的不是用例数
OTHER_METRIC = ("个文件", "个探测点", "条路径", "个域名", "个节点", "条规则",
                "个规则", "个用例", "个 case", "项", "个包", "个设备")

# 比率分母的合理区间
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


def _ratio_is_about_cases(line, m):
    """④ 的语境判定：这个比率在说用例数吗？

    三种「算」：
      ① 子句里有明确用例指代（用例 / negtest / 负向回归 …）
      ② 子句里有「命中 / 跑完 / 跑出来」，且它在比率的**之后**
      ③ 且 ② 的那种情况下，**比率与那个词之间不能夹别的指标名词**
         （`12/20 个文件全部命中` ⇒ 说的是文件，不算）
    """
    a, b = _clause_span(line, m.start())
    cl = line[a:b]
    if any(w in cl for w in CASE_CLAUSE_WORDS):
        return True
    tail = line[m.end():b]
    for w in CASE_CLAUSE_AFTER:
        idx = tail.find(w)
        if idx < 0:
            continue
        gap = tail[:idx]
        # 中间夹了别的指标名词 ⇒ 不是用例数
        if any(o in gap for o in OTHER_METRIC):
            continue
        return True
    return False


def scan(tracked_files, root, actual_count=None):
    """返回 [(文件, 行号, 命中的数字串, 该行摘要, 原因)]。

    原因：
      "assert_current"  句式①（显式声称当前值）
      "increased"       句式②（已增至）
      "count_mismatch"  句式③（`N 个用例` / `N 条用例` 且 ≠ 真值）
      "ratio_mismatch"  句式④（当前口吻 + 指向用例数的 X/Y 且分母 ≠ 真值）
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
            m = ASSERT_CURRENT.search(line) or INCREASED.search(line)
            if m:
                why = ("assert_current" if ASSERT_CURRENT.search(line)
                       else "increased")
                found.append((f, i, m.group(0).strip(), line.strip()[:70], why))
                continue
            if actual_count is None:
                continue
            hit = None
            for m in COUNT.finditer(line):
                n = _first_int(*m.groups())
                if n is not None and n != actual_count:
                    hit = (m.group(0).strip(), "count_mismatch")
                    break
            if hit is None and any(w in line for w in CURRENT_WORDS):
                for m in RATIO.finditer(line):
                    num, den = int(m.group(1)), int(m.group(2))
                    if num > den or not (_RATIO_DEN_MIN <= den <= _RATIO_DEN_MAX):
                        continue
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
