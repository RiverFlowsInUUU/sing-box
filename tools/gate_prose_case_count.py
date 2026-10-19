"""活文档 / CI 文件里不得把**当前**的负向用例数当成常量写下来。

## 事故

2026-10-19 第四轮复核 P3：`eab4135` 把「用例数不写进任何文本」立成了规则，
但**下一轮的 `audit.yml` 就在这条规则的正下方一行又写了数字**（「实测是 67」），
而且那个数字当时已经漂成 68 —— 它正在批评的那种「会漂的数」，自己就是。

## 判据的三次演进（每次都是被复核指出后重做）

**第一版：整行含历史词 ⇒ 整行豁免。**
第五轮复核 P3-A 实测出可绕过的洞：同一行里出现「当时 / 此前 / 看不到」
就能把**当前值**数字一起豁免。而且词表是照着当前语料凑的
（`看不到` 是从「…全绿的报告里是看不见的」里抠出来的），
**给的是「当前语料正好干净」的安全感，不是判据带来的保证。**

**第二版：豁免判到「数字所在的子句」+ 混写单独报。**
实测更糟 —— 误报了已存在的正确文字（`EXPERIENCES.md:118` 的「28/28 全绿」，
那是**当时那次 CI 报告**的数字，是历史事实），
且 5 种注入全部报成同一个结果（**区分能力为零**）。
→ 撤回。**层次越多，误报与漏报的耦合越难预测。**

**第三版（现在）：不判语义，只扫「声称当前值」的显式句式。**

理由：**「这句话是当前还是历史」是语义判断，靠词表和切分只能逼近。**
而事故句「实测是 67」有一个不需要判断的特征 —— **它是显式的当前值措辞**。
所以把判据换成「可枚举的句式 + 可算的真值」，不做任何语气推断：

| # | 判据 | 为什么不可绕 |
|---|---|---|
| ① | `实测是 N` / `实测为 N` / `目前是 N` / `当前是 N` / `现在是 N` | 这是**声称当前值**的显式措辞，写了就是当前值 |
| ② | `已增至 N` / `增至 N` | 同上，天然是当前口吻 |
| ③ | `N 个用例` 且 `N != 真值` | 计数措辞 + 真值可算（`negtest` 自报）→ **可证伪** |

**比率措辞（`28/28` / `29/29`）不在这条判据里** —— 它是一对数字，
不是一个「计数」，且绝大多数是「当时那次报告」的标题。放宽它换取的是判据可信。

**真值来源**：调用方传入（`negtest.py` 里就是 `len(CASES)`），
这样门禁不依赖跑一次 negtest，也就不会互相递归。
拿不到真值时只做 ①②，**不做 ③**（宁可少查，不要瞎报）。
"""

import re

# ① 显式「声称当前值」的措辞 —— 写了就报，不做任何历史推断。
#    这些都是「此刻的值」，不可能是历史记述。
ASSERT_CURRENT = re.compile(
    r"(实测|实测值)?\s*(是|为|达到|有)\s*(\d{1,5})\s*(个)?\s*用例"
    r"|(现在|目前|当前)\s*(是|为|有)\s*(\d{1,5})\s*(个)?\s*用例"
    r"|用例数\s*(是|为|达到)\s*(\d{1,5})"
)

# ② 「已增至」类 —— 天然当前口吻
INCREASED = re.compile(r"(已增至|增至|增加到|提升到)\s*(\d{1,5})")

# ③ 计数措辞 + 真值比对
COUNT = re.compile(r"(\d{1,5})\s*个\s*用例")

CTX = ("用例", "negtest", "CASES")

# 整文件豁免：追加型历史记录（本仓既有原则）
EXEMPT_FILES = ("docs/LESSONS.md", "docs/DECISIONS.md")


def scan(tracked_files, root, actual_count=None):
    """返回 [(文件, 行号, 命中的数字串, 该行摘要, 原因)]。

    原因："assert_current"（句式①）/ "increased"（句式②）/ "count_mismatch"（句式③）。
    `actual_count` 为 None 时不做 ③ —— 宁可少查，不要瞎报。
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
            text = (root / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not any(c in line for c in CTX):
                continue
            for pat, why in ((ASSERT_CURRENT, "assert_current"),
                             (INCREASED, "increased")):
                m = pat.search(line)
                if m:
                    found.append((f, i, m.group(0).strip(),
                                  line.strip()[:70], why))
                    break
            else:
                if actual_count is None:
                    continue
                for m in COUNT.finditer(line):
                    n = int(m.group(1))
                    if n != actual_count:
                        found.append((f, i, m.group(0), line.strip()[:70],
                                      "count_mismatch"))
                        break
    return found
