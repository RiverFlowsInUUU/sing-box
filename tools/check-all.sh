#!/usr/bin/env bash
# check-all.sh —— 一条命令跑完全部验证，并汇总「哪里要改」。
#
# 为什么需要它：
#   完整验证原本要手敲三条命令（audit --no-check / audit --run / sing-box check），
#   而且 SINGBOX_BIN 没设时 --run 会**静默跳过**（只打一行 INFO 说"未指定 sing-box 可执行文件"），
#   于是"跑过了"和"根本没跑"看起来一样。这就是 L25 那类静默失效。
#   本脚本把 SINGBOX_BIN 的解析显式化，且解析不到就直接报错退出，不假装通过。
#
# 用法：
#   bash tools/check-all.sh           # 静态门禁 + sing-box check（秒级）
#   bash tools/check-all.sh --run     # 再加启动级验证（约 1 分钟，能抓到 check 抓不到的 FATAL）
#   bash tools/check-all.sh --json    # 机器可读输出
#
# SINGBOX_BIN 解析顺序：
#   ① 环境变量 SINGBOX_BIN
#   ② 仓库内 bin/sing-box[.exe]
#   ③ PATH 里的 sing-box
#   ④ 本机私有配置 local/.singbox-bin 的第一行
#      —— 这个文件在 .gitignore 覆盖的 local/ 下，所以本机绝对路径不会进仓库。
#      创建：mkdir -p local && echo '/abs/path/to/sing-box' > local/.singbox-bin
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN=0
EXTRA_ARGS=()
for a in "$@"; do
  case "$a" in
    --run) RUN=1 ;;
    *) EXTRA_ARGS+=("$a") ;;
  esac
done

PY="${PYTHON:-python}"

resolve_singbox() {
  if [ -n "${SINGBOX_BIN:-}" ] && [ -x "${SINGBOX_BIN}" ]; then echo "$SINGBOX_BIN"; return 0; fi
  local exe="sing-box"
  [ "${OS:-}" = "Windows_NT" ] && exe="sing-box.exe"
  if [ -x "$ROOT/bin/$exe" ]; then echo "$ROOT/bin/$exe"; return 0; fi
  if command -v sing-box >/dev/null 2>&1; then command -v sing-box; return 0; fi
  if [ -f "$ROOT/local/.singbox-bin" ]; then
    local p; p="$(head -n1 "$ROOT/local/.singbox-bin" | tr -d '\r\n')"
    if [ -n "$p" ] && [ -x "$p" ]; then echo "$p"; return 0; fi
  fi
  return 1
}

echo "════════════════════════════════════════════════════════════════"
echo "  仓库：$ROOT"
echo "  锁定版本：$(cat singbox_version.txt 2>/dev/null | tr -d '\r\n')"
echo "════════════════════════════════════════════════════════════════"

# 探测串：1/2/3/4 个反斜杠 —— 用 chr(92) 在 Python 侧生成后写入，避免源码里出现字面反斜杠
BS1='\'
BS2='\\'
BS3='\\\'
BS4='\\\\'

# ── 0. 解析 sing-box 可执行文件（准备步骤，不计入下面的编号）──────────
#    --run 必须有它；没解析到就退出，绝不静默降级。
SB=""
if SB_RESOLVED="$(resolve_singbox)"; then
  SB="$SB_RESOLVED"
  export SINGBOX_BIN="$SB"
  echo "  sing-box：$SB"
  echo "           $("$SB" version 2>/dev/null | head -n1)"
else
  echo "  ⚠️  没找到 sing-box 可执行文件。" >&2
  echo "      静态门禁仍会跑，但 **启动级验证与内核解码校验会被跳过**。" >&2
  echo "      要补齐，任选其一：" >&2
  echo "        export SINGBOX_BIN=/abs/path/to/sing-box" >&2
  echo "        mkdir -p local && echo /abs/path/to/sing-box > local/.singbox-bin" >&2
  if [ "$RUN" = "1" ]; then
    echo "      --run 明确要求启动级验证，但没有内核，无法进行。" >&2
    exit 3
  fi
fi
echo

# ── 1. 静态门禁（含 local/ 下真机运行的配置）────────────────────────
echo "── [1/7] 静态门禁 ──────────────────────────────────────────────"
if [ "$RUN" = "1" ]; then
  A_ARGS=(--no-check)   # --run 由下一步单独跑，避免重复加载规则集
else
  A_ARGS=()
  [ -z "$SB" ] && A_ARGS=(--no-check)
fi
"$PY" tools/audit.py "${A_ARGS[@]}" "${EXTRA_ARGS[@]}"
STATIC_RC=$?
echo

# ── 2. 启动级验证（只筛 FATAL）─────────────────────────────────────
if [ "$RUN" = "1" ] && [ -n "$SB" ]; then
echo "── [2/7] 启动级验证（只筛 FATAL，check 抓不到的那一层）────────"
  "$PY" tools/audit.py --run --run-seconds "${RUN_SECONDS:-18}" "${EXTRA_ARGS[@]}"
  RUN_RC=$?
  echo
else
  RUN_RC=0
  [ "$RUN" = "1" ] || echo "── [2/7] 启动级验证：跳过（加 --run 启用）───────────────────────"
  echo
fi

# ── 3. 门禁负向回归（秒级，纯本地）────────────────────────────────
#    为什么放这里：一个门禁只有「干净时安静」（audit 全绿）+「破坏时会响」（本步）
#    两件事同时成立才算数。不跑这一步，改门禁就是把回归网拆掉而自己不知道
#    （L34：门禁按早已不用的字面量匹配，永远不响，而 audit 一直是绿的）。
NEG_RC=0
if [ -x "$ROOT/tools/negtest.py" ] || [ -f "$ROOT/tools/negtest.py" ]; then
  echo "── [3/7] 门禁负向回归（故意改坏配置，确认门禁会响）──────────"
  "$PY" tools/negtest.py
  NEG_RC=$?
  echo
fi

# ── 4. markdown 结构校验（秒级，纯本地）───────────────────────────
#    为什么需要：本仓**没有** markdownlint 配置（AI_SYNC_WORKFLOW.md 要求
#    「运行仓库已有的 markdown lint；如果没有，说明未运行」——但「说明未运行」
#    指的是**如实申报**，不是「因此就不检查」）。文档也是产物，它的问题
#    （围栏不配对 / 标题层级跳跃 / 相对链接指向不存在的文件或锚点）
#    靠肉眼极难发现，却让下一个人读不懂。
#    这是兜底工具，不是风格审查：只报**确定性**错误，不碰行长/标点。
MD_RC=0
if [ -f "$ROOT/tools/mdlint.py" ]; then
  echo "── [4/7] markdown 结构校验（围栏 / 标题层级 / 链接 / 锚点）─────"
  # 不加 --changed：干净分支上 --changed 会退化成「检查 0 个文件」，等于没查。
  # 全量扫描只多几百毫秒（17 个文件），换来的是「每次都真的在看」。
  "$PY" tools/mdlint.py
  MD_RC=$?
  echo
fi

# ── 5. 改文件方式指纹（秒级，纯本地）──────────────────────────────
#    L40 那条铁律原文写着「门禁：无」—— 于是它成了全仓唯一一条没有机器兜底的规则，
#    而我连犯 5 次。规律干净得像实验数据：有门禁的零违反，写着「无」的反复犯。
#    「改文件用没用 patch-text」验不了（绕过手段是通用能力，过程痕迹会被回滚抹掉），
#    但**绕过它才会留下的产物指纹**能验：BOM / NUL / 行尾混用 / 整文件 CRLF。
#    守规零成本、违规留痕 —— 这就够了。
EDIT_RC=0
if [ -f "$ROOT/tools/check-edit-method.py" ]; then
  echo "── [5/7] 改文件方式指纹（BOM / NUL / 行尾）─────────────────────"
  "$PY" tools/check-edit-method.py
  EDIT_RC=$?
  echo
fi

# ── 转义层自检【本脚本内已移除，不是一步】────────────────────────────
#    曾在这里加过一步，跑 tools/check-shell-escapes.py。**已移除**，原因：
#    实测发现「反斜杠折半」**只发生在 Agent 手敲命令那条路径上**——
#      · 经 Bash 工具（手敲）      → 折半 2→1、3→2     ❌
#      · 经子进程 / 脚本内部调用   → 无损 1、2、3、4     ✅
#    而本脚本内部调用走的正是「无损」那条路，所以放这里**永远报无损**，
#    看起来像放行、实际什么都没验证 —— 又一个假绿灯。
#
#    ⇒ 它被降级为**换设备时手敲一次**的自检（见 AGENTS.md §8）。
#      要结论，就手敲：python tools/check-shell-escapes.py '\' '\\' '\'' '\\\\'
#      手敲才反映真实路径。

# ── 6. 文档规则重复检测（秒级，纯本地）────────────────────────────
#    为什么：本仓反复出现「同一条规则被两处各自完整陈述」——
#    模块 2 规则清单、三栏分类表、完整克隆流程，都曾一字不差各写一遍。
#    危害不是啰嗦，而是**改一处忘一处、两份开始打架、没人知道哪份对**
#    （L46 那次门禁失效就是这个成因）。
DUPE_RC=0
if [ -f "$ROOT/tools/audit_rules_dupe.py" ]; then
  echo "── [6/7] 文档规则重复检测（单一来源原则）───────────────────────"
  "$PY" tools/audit_rules_dupe.py
  DUPE_RC=$?
  echo
fi

# ── 7. 逐份 sing-box check ────────────────────────────────────────
echo "── [7/7] 逐份 sing-box check ───────────────────────────────────"
CHECK_RC=0
if [ -n "$SB" ]; then
  shopt -s nullglob
  for f in profiles/*/*.json local/*.json; do
    case "$(basename "$f")" in
      groups.json) continue ;;   # 骨架模板带 _comment，必然 FATAL，由 audit 单独跳过
    esac
    if out="$("$SB" check -c "$f" 2>&1)"; then
      printf '  OK    %s\n' "$f"
    else
      printf '  FAIL  %s\n        %s\n' "$f" "$(echo "$out" | head -n3 | tr '\n' ' ')"
      CHECK_RC=1
    fi
  done
else
  echo "  （无内核，跳过）"
fi
echo

# ── 汇总 ───────────────────────────────────────────────────────────
# ⚠️ 这里必须**逐个列出**每一个步骤的退出码。早先只判 STATIC/RUN/CHECK/NEG 四个，
#    MD_RC / EDIT_RC / DUPE_RC 收下来了却没进条件 —— 于是 markdown 围栏不配对、
#    文件带 BOM/CRLF 指纹、文档规则重复，三项**任一失败都会被吞掉**：脚本照样打印
#    「✅ 全部通过」并 exit 0。而失败分支里明明写着 MD_RC 那一行，说明本意是要算的。
#    这就是本仓反复栽的「假绿灯」：门禁跑了、报错了、汇总把它咽了。
#    新增步骤时，**加一行 RC 变量就必须在这里加一个判断**。
echo "════════════════════════════════════════════════════════════════"
if [ "$STATIC_RC" = "0" ] && [ "$RUN_RC" = "0" ] && [ "$CHECK_RC" = "0" ] \
   && [ "$NEG_RC" = "0" ] && [ "$MD_RC" = "0" ] && [ "$EDIT_RC" = "0" ] \
   && [ "$DUPE_RC" = "0" ]; then
  echo "  ✅ 全部通过（静态门禁 + 负向回归 + markdown 结构 + 改文件指纹 + 文档重复$( [ "$RUN" = 1 ] && echo ' + 启动级' ) + 内核解码）"
  echo "════════════════════════════════════════════════════════════════"
  exit 0
fi
echo "  ❌ 有失败项：" >&2
[ "$STATIC_RC" != "0" ] && echo "     静态门禁 exit=$STATIC_RC —— 看上面 [E] 行，每条都带文件名与位置" >&2
[ "$NEG_RC"    != "0" ] && echo "     负向回归 exit=$NEG_RC —— 有门禁成了死检查（不会响），看上面 ❌ 行" >&2
[ "$RUN_RC"    != "0" ] && echo "     启动级 exit=$RUN_RC —— 看上面的 FATAL 行" >&2
[ "$CHECK_RC"  != "0" ] && echo "     内核解码 exit=$CHECK_RC —— 看上面 FAIL 行" >&2
[ "$MD_RC"     != "0" ] && echo "     markdown 结构 exit=$MD_RC —— 看上面 [MDxxx]/[LINK]/[ANCHOR] 行" >&2
[ "$EDIT_RC"   != "0" ] && echo "     改文件指纹 exit=$EDIT_RC —— 看上面 BOM/NUL/行尾 行" >&2
[ "$DUPE_RC"   != "0" ] && echo "     文档规则重复 exit=$DUPE_RC —— 看上面「未豁免的跨文件重复规则」行" >&2
echo "════════════════════════════════════════════════════════════════" >&2
exit 1
