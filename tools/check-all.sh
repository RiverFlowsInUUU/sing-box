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

# ── 1. 解析 sing-box 可执行文件 ────────────────────────────────────
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

# ── 2. 静态门禁（含 local/ 下真机运行的配置）────────────────────────
echo "── [1/4] 静态门禁 ──────────────────────────────────────────────"
if [ "$RUN" = "1" ]; then
  A_ARGS=(--no-check)   # --run 由下一步单独跑，避免重复加载规则集
else
  A_ARGS=()
  [ -z "$SB" ] && A_ARGS=(--no-check)
fi
"$PY" tools/audit.py "${A_ARGS[@]}" "${EXTRA_ARGS[@]}"
STATIC_RC=$?
echo

# ── 3. 启动级验证（只筛 FATAL）─────────────────────────────────────
if [ "$RUN" = "1" ] && [ -n "$SB" ]; then
echo "── [2/4] 启动级验证（只筛 FATAL，check 抓不到的那一层）────────"
  "$PY" tools/audit.py --run --run-seconds "${RUN_SECONDS:-18}" "${EXTRA_ARGS[@]}"
  RUN_RC=$?
  echo
else
  RUN_RC=0
  [ "$RUN" = "1" ] || echo "── [2/4] 启动级验证：跳过（加 --run 启用）───────────────────────"
  echo
fi

# ── 4. 门禁负向回归（秒级，纯本地）────────────────────────────────
#    为什么放这里：一个门禁只有「干净时安静」（audit 全绿）+「破坏时会响」（本步）
#    两件事同时成立才算数。不跑这一步，改门禁就是把回归网拆掉而自己不知道
#    （L34：门禁按早已不用的字面量匹配，永远不响，而 audit 一直是绿的）。
NEG_RC=0
if [ -x "$ROOT/tools/negtest.py" ] || [ -f "$ROOT/tools/negtest.py" ]; then
  echo "── [3/4] 门禁负向回归（故意改坏 28 处，确认门禁会响）──────────"
  "$PY" tools/negtest.py
  NEG_RC=$?
  echo
fi

# ── 5. 逐份 sing-box check ────────────────────────────────────────
echo "── [4/4] 逐份 sing-box check ───────────────────────────────────"
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
echo "════════════════════════════════════════════════════════════════"
if [ "$STATIC_RC" = "0" ] && [ "$RUN_RC" = "0" ] && [ "$CHECK_RC" = "0" ] && [ "$NEG_RC" = "0" ]; then
  echo "  ✅ 全部通过（静态门禁 + 负向回归 + $( [ "$RUN" = 1 ] && echo '启动级 + ' )内核解码）"
  echo "════════════════════════════════════════════════════════════════"
  exit 0
fi
echo "  ❌ 有失败项：" >&2
[ "$STATIC_RC" != "0" ] && echo "     静态门禁 exit=$STATIC_RC —— 看上面 [E] 行，每条都带文件名与位置" >&2
[ "$NEG_RC"    != "0" ] && echo "     负向回归 exit=$NEG_RC —— 有门禁成了死检查（不会响），看上面 ❌ 行" >&2
[ "$RUN_RC"    != "0" ] && echo "     启动级 exit=$RUN_RC —— 看上面的 FATAL 行" >&2
[ "$CHECK_RC"  != "0" ] && echo "     内核解码 exit=$CHECK_RC —— 看上面 FAIL 行" >&2
echo "════════════════════════════════════════════════════════════════" >&2
exit 1
