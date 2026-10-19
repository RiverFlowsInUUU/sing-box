"""活文档 / CI 文件里不得把**当前**的负向用例数当成常量写下来。

## 事故

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

## 判据的演进（每一版都是被复核指出后重做）

v1 整行含历史词 ⇒ 整行豁免 → 第五轮：同一行的历史词能解掉当前值数字
v2 判到子句 + 混写单独报 → 实测更糟（误报正确文字、区分能力为零）→ 撤回
v3 只扫「显式声称当前值」的句式
v4 补比率与计数措辞（第六轮：`68/68 全部命中` 整类被放掉）
v5 ④ 加「位置 + 数值」约束（第七轮：写个日期就假报）
v6 补行级 CTX 的「命中/跑完/跑出来」（第八轮）→ 放进了新假报面（第九轮）
v7 **把「行级 CTX」与「④ 的语境依据」拆开设计**，④ 改判「位置关系」
v8 砍掉 `N 条` 支；「全绿」**位置化**（放进 AFTER，不是当专用词）

**v9（现在）：第十一轮复核 —— 用「空白容差」代替「指标名词黑名单」**

两处修（都由复核给出可落地方案并实测）：

| # | 病 | 修法 |
|---|---|---|
| ① | **新死代码 `_SEP_OK`**：定义了「④ 的紧邻容差」正则却从未接线 | **接上它**（不是删掉）—— 见 ③ |
| ③ | `OTHER_METRIC` 是**指标名词黑名单**，被 5/8 条对抗样例击穿（`个配置` / `条命令` / `个平台` / `份文档` / `个镜像`）| **换成白名单**：比率与子句词之间**只允许**空白 / 标点 / `全部` / `都`；出现别的字 ⇒ 该比率不算在说用例数 |

**黑名单 vs 白名单 —— 这是本条的根本**：

· 黑名单（`OTHER_METRIC`）要**枚举所有「不是用例数」的指标名词**——语言里枚举不完，
  复核实测 5 条新名词全部漏过，而且我举的例子（「个规则集」）还举错了
  （它恰好在枚举 `个规则` 里，本来就静默）。
· 白名单（`_SEP_OK`）只要求「中间没有别的东西」——**这才是「紧邻」的正确表述**，
  不需要枚举语言。

复核侧实测（把它接线后）：26 条矩阵 A **0** / B **8/8** / C **0**；
真实语料 28 个文件 **0** 命中（与接线前一致）。

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
# 「命中 / 跑完 / 跑出来 / 全绿」：只有在比率**之后且紧邻**才指向用例数
#
# ⚠️ 「全绿」这里有个来回（第十轮复核 P3-②(b)）：
#    · 我原来断言「全绿在本仓**只**用于负向回归」→ **断言错了**（没跑语料）
#      （`AI_SYNC_WORKFLOW.md:37`「工具语法错也能全绿」说的是整套门禁；
#       `PROTOCOL-MAPPING.md:264`「跑 audit.py … 全绿」也是）
#    · 但**不能因此整条删掉** —— `现在跑出来是 68/68 全绿。` 确实在说用例数
#      （删掉后回归立刻抓到：这句话变静默了）
#    → 它和「命中」是同一类词：**位置对时算**。故放进 AFTER。
#      （`20-整改` 报告 §三(b) 记了这个来回；本表头于第十一轮复核 P3-② 修正
#       —— 之前这里写的是「删掉这条断言」，与实现矛盾。）
CASE_CLAUSE_AFTER = ("命中", "跑完", "跑出来", "全绿")

# ★ ④(a) 的「紧邻」判据 —— **白名单**，不是指标名词黑名单
#
# ⚠️ 第十二轮复核 P3-①：第一版白名单只允许「空白 / 标点 / 全部 / 都」，
#    漏掉了本仓的自然写法（程度副词组合）：
#      `全部均已命中` / `均已命中` / `共命中` / `全部均命中` / `全部：命中` /
#      `全都命中` / `全命中`  —— 实测 7 种全部静默（原本会响）。
#    收口：扩成「**程度副词任意组合 + 标点**」（下面是复核已实测的方案）。
#    → 教训：**照别人的建议实现时，也要自测「这个建议会不会缩掉什么」。**
#      那条边界源自我上一轮引用的建议本身，但**行为变化是本轮引入的**，仍算我的。
#
# 第十一轮复核 P3-③：以前这里是一个 `OTHER_METRIC` 黑名单
# （枚举「个文件 / 个探测点 / 条路径 …」这类非用例指标名词）。
# 它被 5/8 条对抗样例击穿（`个配置` / `条命令` / `个平台` / `份文档` / `个镜像`）——
# 而**黑名单要枚举完语言里所有别的指标名词，做不到**。
#
# 改成白名单：比率与子句词之间**只允许**出现空白 / 标点 / 「全部」/「都」。
# 出现任何别的字 ⇒ 这个比率不是在说用例数。
#   ✓ `68/68 全部命中`    gap = " 全部"
#   ✗ `12/20 个配置全绿`  gap = " 个配置"
#
# 复核侧实测（接线后）：26 条矩阵 A 0 / B 8/8 / C 0；真实语料 28 文件 0 命中。
# ⚠️ 这个常量上一轮就定义了、却从未接线（第十一轮复核 P3-①：新死代码）——
#    它本来就是 ④(a) 需要的通用判据，只是我上一轮绕道去写黑名单了。
_SEP_OK = re.compile(
    r"^[\s，、：:（）()「」『』]*"
    r"(?:(?:全部|全都|都|全|均|共|已)[\s，、：:（）()「」『』]*)*"
    r"$"
)

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

    两种「算」：
      ① 子句里有明确用例指代（用例 / negtest / 负向回归 …）
      ② 子句里有「命中 / 跑完 / 跑出来 / 全绿」，且它在比率的**之后**，
         并且**中间只允许空白 / 标点 / 全部 / 都**（`_SEP_OK` 白名单）
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
        # ★ 白名单：gap 里只允许空白 / 标点 / 「全部」/「都」
        if _SEP_OK.fullmatch(gap):
            return True
        # gap 里有别的东西 ⇒ 这个比率在说别的指标，不算
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
