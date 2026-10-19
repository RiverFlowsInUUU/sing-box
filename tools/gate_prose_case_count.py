"""活文档 / CI 文件里不得把**当前**的负向用例数当成常量写下来。

## 事故

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

## 判据的四次演进（每次都是被复核指出后重做）

**第一版：整行含历史词 ⇒ 整行豁免。**
第五轮复核 P3-A 实测出可绕过的洞：同一行出现「当时 / 此前 / 看不到」
就能把当前值数字一起豁免。而且词表是照着当前语料凑的
（`看不到` 是从「…全绿的报告里是看不见的」里抠出来的），
**给的是「当前语料正好干净」的安全感，不是判据带来的保证。**

**第二版：豁免判到「数字所在的子句」+ 混写单独报。**
实测更糟 —— 误报了已存在的正确文字（`EXPERIENCES.md:118` 的「28/28 全绿」），
且 5 种注入全报同一结果（区分能力为零）。→ 撤回。

**第三版：不判语义，只扫「声称当前值」的显式句式。**
事故句「实测是 67」有一个不需要判断的特征 —— 它是显式的当前值措辞。
① `实测是 N` / `目前是 N` / `现在是 N` / `当前是 N`
② `已增至 N` / `增至 N`
③ `N 个用例` 且 `N != 真值`（计数措辞 + 真值可算 → 可证伪）

**第四版（现在）：补上比率写法与其余计数措辞。**
第六轮复核 P3-1 实测：本仓**最自然**的当前值写法是 `68/68 全部命中`
（CI 输出、报告里到处都是），而第三版整类放掉 —— 5 种写法全静默。
复核指出两处口径不一致：`audit.yml` 的规则文字是「不写进任何文本」（宽），
而门禁 docstring 说「比率不在判据里」（窄）—— **规则比实现宽**，
这正是第四轮那条 P3 的形状。

补第 ④ 条并扩 ③：

④ **当前口吻词 + `X/Y`（分母 ≠ 真值）→ 报。**
   「现在跑出来是 68/68 全绿」→ 有「现在」+ 分母 ≠ 真值 → 报
   「当时砍成 28/28 全绿」  → 无当前口吻词 → 豁免（历史记述）
   为什么纳入：比率里的**分母就是用例数**，只要它挂「现在/本轮」就一定会漂。
   （没有降规则去迁就实现 —— 规则本身是对的：用例数确实不该写进任何文本。）

③ 扩为：`N 个用例` / `N 个 case` / `N 条`（用例语境）且 `N != 真值` → 报。
   倒装（「负向用例 68 个」）也收 —— 数字与「用例」的先后不固定。

范围：`_tracked_files()` 里的活文档与 CI 文件；
`docs/LESSONS.md` / `docs/DECISIONS.md` 整文件豁免（追加型历史记录）。
**`tools/` 整目录排除** —— 门禁的实现与注释必须能写出被检字面量才能描述要抓什么，
扫它就是自噬。

真值来源：调用方传入（`audit.py` 用 `ast` 取 `CASES` 字面量长度，
见 P3-3）。拿不到真值时只做 ①②，**不做 ③④**（宁可少查，不要瞎报）。
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
# ⚠️「N 条」后面不必跟「用例」——「负向回归共 68 条，全部命中」是自然写法
#   （第六轮复核 P3-1 实测漏了这一种）。
#   但「N 条」必须是**用例语境**：本行已有 CTX 命中（用例/负向回归/全绿…）才算，
#   故这里不再要求「条」后跟「用例」。
COUNT = re.compile(
    r"(\d{1,5})\s*个\s*(?:用例|case)"
    r"|用例\s*(\d{1,5})\s*个"
    r"|(\d{1,5})\s*条"
)

# ④ 比率写法 + 当前口吻词
#
# ⚠️ 第七轮复核 P3-2：只看「有当前口吻词 + 本行有 X/Y」会**过报**——
#    「本轮（2026/10/19）复核完成」→ 把日期读成比率（分母 10 ≠ 真值）；
#    「现在 1/2 命中」→ 把别的比率读成用例数。
#    判据 ④ 的理由是「**比率的分母就是用例数**」，
#    所以必须验证两件事，缺一不可：
#      ③ 这个比率出现在**用例语境的子句**里（位置对）
#      ① 数值形态像用例数：num ≤ den，且 den 在 [10, 999]（数值对）
RATIO = re.compile(r"(\d{1,5})\s*/\s*(\d{1,5})")
CURRENT_WORDS = ("现在", "目前", "当前", "本轮", "本次", "这次")

# 用例语境的子句词：比率必须与它同处一个子句，才算「在说用例数」
CASE_CLAUSE_WORDS = ("用例", "negtest", "CASES", "负向回归", "负向用例",
                     "全绿", "命中", "跑完", "跑出来")

# 比率分母的合理区间（用例数不会是个位数，也不会到四位数）
_RATIO_DEN_MIN = 10
_RATIO_DEN_MAX = 999

# 子句切分：中文句读 + 括号。「本轮（2026/10/19）复核完成」里
# 日期在括号内、与「本轮」不同子句 → 天然被排除。
_CLAUSE_SPLIT = re.compile(r"[，。；;、（）()「」\[\]]")


def _clause_containing(line, pos):
    """返回包含 pos 的那个子句。"""
    start = 0
    for m in _CLAUSE_SPLIT.finditer(line):
        if m.end() <= pos:
            start = m.end()
        elif m.start() > pos:
            break
    end = len(line)
    for m in _CLAUSE_SPLIT.finditer(line):
        if m.start() > pos:
            end = m.start()
            break
    return line[start:end]

# ⚠️「全绿」必须在 CTX 里：本仓最自然的当前值写法是
#   「现在跑出来是 68/68 全绿」—— 这句里没有「用例」二字。
#   （第六轮复核 P3-1 实测：漏了它 → 整行被跳过。）
CTX = ("用例", "negtest", "CASES", "负向回归", "负向用例", "全绿")

# 整文件豁免：追加型历史记录（本仓既有原则）
EXEMPT_FILES = ("docs/LESSONS.md", "docs/DECISIONS.md")


def _first_int(*groups):
    for g in groups:
        if g:
            return int(g)
    return None


def scan(tracked_files, root, actual_count=None):
    """返回 [(文件, 行号, 命中的数字串, 该行摘要, 原因)]。

    原因：
      "assert_current"  句式①（显式声称当前值）
      "increased"       句式②（已增至）
      "count_mismatch"  句式③（计数措辞且 ≠ 真值）
      "ratio_mismatch"  句式④（当前口吻 + X/Y 分母 ≠ 真值）
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
            # ④ 当前口吻 + 比率分母 ≠ 真值
            if hit is None and any(w in line for w in CURRENT_WORDS):
                for m in RATIO.finditer(line):
                    num, den = int(m.group(1)), int(m.group(2))
                    # ① 数值形态得像用例数
                    if num > den or not (_RATIO_DEN_MIN <= den <= _RATIO_DEN_MAX):
                        continue
                    # ③ 这个比率必须与用例语境同处一个子句
                    cl = _clause_containing(line, m.start())
                    if not any(w in cl for w in CASE_CLAUSE_WORDS):
                        continue
                    if den != actual_count:
                        hit = (m.group(0).strip(), "ratio_mismatch")
                        break
            if hit:
                found.append((f, i, hit[0], line.strip()[:70], hit[1]))
    return found
