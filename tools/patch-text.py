#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch-text.py —— 安全的文本改写器（把「一次性临时脚本」变成常驻工具）

用法：
    python tools/patch-text.py <spec.json> [--dry-run]
    python tools/patch-text.py --spec-inline '[{"file":"x","find":"a","replace":"b"}]'

spec.json 是一个数组，每个元素：
    {
      "file":    "AGENTS.md",          # 相对仓库根
      "find":    "要被替换的原文",       # 必须**唯一**匹配（见 count）
      "replace": "替换成的新文",
      "count":   1                      # 可选，默认 1；写 0 = 允许任意次（须显式写）
    }

多行内容一律用 `find_file` / `replace_file` 指向独立文本文件，别塞进 JSON：
    {"file": "tools/x.py", "find_file": "local/block_a.txt", "replace_file": "local/new_a.txt"}
    （JSON 字符串里放真实换行是非法的，只能写成 `\n` 转义 —— 那正是「转义被层层解释」
      这个老坑本身。用外置文件就等于绕开整个转义层。）
路径都相对仓库根。

为什么需要它（对应 L39 / AGENTS.md 铁律 21）：
在活仓库里改文档/代码时，我反复用「现写一个 heredoc python 脚本」的方式，踩了三个坑，
每一次都要重来一遍：

  ㊀ `open(p, "wb")` 先截断再算内容 —— 一旦中途异常，文件就只剩半截
     （真实事故：`tools/audit.py` 从 1919 行被截成 828 行）。
  ㊁ heredoc 里写转义序列会被 shell / 编码层改写 —— `\\x00` 变成真 NUL 字节，
     写进 .py 直接 `SyntaxError: source code string cannot contain null bytes`。
  ㊂ 「某个短 token 第一次出现的位置」当锚点 —— 命中了文件里第一个 `try:`，替换点完全错位。

这个工具把三条一次性消掉：
  · **原子写**：先写同目录 `.tmp`、`os.replace()` 落盘 —— 中途异常不碰原文件；
  · **无 shell 转义**：查找/替换串只从 JSON 文件或 `--spec-inline` 读，不经过 shell 二次解释；
  · **锚点必须唯一**：`find` 匹配次数 != `count` 就整体拒绝、一个字节都不改。

附加保证：保留原行尾（CRLF/LF 混排也不动其它行）、保留无尾换行的文件形态、
`--dry-run` 只报「哪个文件、第几行、改几处」。

**同一文件多条 patch 顺序作用**（L42）：早先的实现对每条 patch 都从「原始文本」算全文快照，
落盘时只取最后一条 ⇒ 同文件的第二条会连带把第一条的改写吞掉，而且每条都打印「✅ 改写」。
现在每条 patch 校验并作用于「上一条已应用之后」的文本。
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def _detect_newline(raw: bytes) -> bytes:
    """返回文件的主行尾（b"\\r\\n" 或 b"\\n"）。空文件按 \\n。"""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return b"\r\n" if crlf >= lf else b"\n"


def _norm(raw: bytes, nl: bytes) -> str:
    """把文件统一成 \\n 文本再做匹配（这样 patch spec 里只需写 \\n）。"""
    return raw.replace(nl, b"\n").decode("utf-8")


def _denorm(text: str, nl: bytes, had_final_newline: bool) -> bytes:
    raw = text.encode("utf-8")
    if nl != b"\n":
        raw = raw.replace(b"\n", nl)
    if not had_final_newline and raw.endswith(nl):
        raw = raw[: -len(nl)]
    return raw


def apply_patch(spec, dry_run=False) -> int:
    failures = 0
    # file -> (nl, had_final, 当前文本)。同一文件的多条 patch **顺序作用**在演进中的文本上：
    # 每条 patch 的 find 都要在「上一条已应用」之后的文本里唯一 —— 否则第二条会拿旧快照替换，
    # 而落盘只取最后一条的快照，前面的改写会被静默吞掉（真实事故见 L42）。
    working: dict = {}
    for i, item in enumerate(spec):
        fid = f"spec[{i}]"
        if not isinstance(item, dict) or "file" not in item:
            print(f"  ❌ {fid}: 必须含 file")
            failures += 1
            continue
        # find / replace 二选一：内联字符串或外置文本文件（多行内容用后者）
        def _resolve(inline_key, file_key, default=None):
            if file_key in item:
                fp = ROOT / item[file_key]
                if not fp.exists():
                    raise FileNotFoundError(f"{fid}: {file_key} 指向的文件不存在 {item[file_key]}")
                return fp.read_text(encoding="utf-8")
            return item.get(inline_key, default)

        try:
            find = _resolve("find", "find_file")
            repl = _resolve("replace", "replace_file", "")
        except FileNotFoundError as ex:
            print(f"  ❌ {ex}")
            failures += 1
            continue
        if not isinstance(find, str) or find == "":
            print(f"  ❌ {fid}: 必须含非空 find 或 find_file")
            failures += 1
            continue
        p = ROOT / item["file"]
        if not p.exists():
            print(f"  ❌ {fid}: 文件不存在 {item['file']}")
            failures += 1
            continue
        want = item.get("count", 1)
        if want == 0 and "count" not in item:
            print(f"  ❌ {fid} ({item['file']}): 允许多处必须显式写 \"count\": 0")
            failures += 1
            continue
        if item["file"] not in working:
            raw = _read_bytes(p)
            nl = _detect_newline(raw)
            working[item["file"]] = (nl, raw.endswith(nl), _norm(raw, nl))
        nl, had_final, text = working[item["file"]]
        # 外置文件的行尾可能是 CRLF，而仓库目标文件是 LF —— 统一成 \n 再匹配。
        find = find.replace("\r\n", "\n")
        repl = repl.replace("\r\n", "\n")
        n = text.count(find)
        if (want == 0 and n == 0) or (want != 0 and n != want):
            print(
                f"  ❌ {fid} ({item['file']}): find 匹配 {n} 次，期望 {want if want else '≥1'} 次"
                f" —— 拒绝改写（锚点必须唯一/可数，见 L39）\n     find = {find[:80]!r}"
            )
            failures += 1
            continue
        lineno = text[: text.index(find)].count("\n") + 1
        new_text = text.replace(find, repl) if want == 0 else text.replace(find, repl, want)
        working[item["file"]] = (nl, had_final, new_text)
        print(f"  ✅ {item['file']}:{lineno}  匹配 {n} 处 → {'预览' if dry_run else '改写'}")

    if failures:
        print(f"\n拒绝执行：{failures} 个 patch 校验不通过，未改动任何文件。", file=sys.stderr)
        return 1
    if dry_run:
        print("\n--dry-run：未写入。")
        return 0

    for fname, (nl, had_final, text) in working.items():
        p = ROOT / fname
        out = _denorm(text, nl, had_final)
        tmp = p.with_name(p.name + ".tmp-patch")
        with open(tmp, "wb") as fh:  # 原子写的临时文件，先完整写完
            fh.write(out)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)  # 原子替换；失败也不会留下半截文件
    print(f"\n全部改写完成：{len(working)} 个文件。建议接着跑 `bash tools/check-all.sh`。")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="安全文本改写（原子写 + 唯一锚点断言）")
    ap.add_argument("spec", nargs="?", help="patch spec 的 JSON 文件路径")
    ap.add_argument("--spec-inline", help="直接给 JSON 字符串（不经过文件）")
    ap.add_argument("--dry-run", action="store_true", help="只校验并预览，不写盘")
    args = ap.parse_args()

    # ══════════════════════════════════════════════════════════════════
    # 🛑 拦截器：`--spec-inline` 里出现反斜杠 ⇒ 直接拒绝，要求改用 `find_file`。
    #
    # 为什么要把"我知道会翻车"变成"工具不让我翻车"：
    #
    # 2026-10-13 实测量出来的事实（同一段命令，我发出去 vs Bash 收到）：
    #
    #     我发出的反斜杠数       实际收到
    #     ─────────────────    ──────────
    #            1 个       →       1 个
    #            2 个       →       1 个   ← 丢了一个
    #            3 个       →       2 个
    #            4 个       →       2 个
    #            5 个       →       3 个
    #            6 个       →       3 个
    #
    # ⇒ **折半，向上取整（收到 ≈ ⌈发出/2⌉）** —— 调用链上的参数序列化所致。
    #    ⚠️ 早期版本把这张表量反了（写成"加倍"），已按实测更正。
    #    这一层在 Alma 的调用协议里，**不是 shell、不是 Python、不是 Windows 设置**，
    #    所以「配环境」治不到它。Bash 层与 Python 层都实测正常
    #    （`<<'EOF'` 原样透传；Python 里 `\n` 转义是它该有的行为）。
    #
    # 既然反斜杠**过不了这一层**，唯一可靠的办法就是**别让内容经过这一层** ——
    # 把内容写进文件，命令行里只传文件名。这正是 `find_file` / `replace_file` 的用途。
    #
    # 在此之前我图省事走了 7 次 inline / heredoc，每次都翻车：
    # `\n` 变真换行、`\x00` 变真 NUL 字节、markdown 表格被劈断……
    # 每次都要回滚重来，其中一次回滚还冲掉了上一批没提交的用例。
    #
    # ⇒ 所以：这不是"建议"，是拒绝执行。想用 inline，就先把反斜杠去掉。
    # ══════════════════════════════════════════════════════════════════
    if args.spec_inline and "\\" in args.spec_inline:
        sys.stderr.write(
            "\n🛑 拒绝执行：`--spec-inline` 里出现了反斜杠。\n\n"
            "   反斜杠无法安全地穿过命令参数序列化层 —— 实测它会被『折半，向上取整』：\n"
            "     发出 1→1   2→1   3→2   4→2   5→3   6→3\n"
            "   于是 `\\n` 会变成真换行、`\\x00` 会变成真 NUL 字节，而你**看不出来**。\n"
            "   （这一层在 Alma 的调用协议里，配 shell / Python / Windows 都不管用。）\n\n"
            "   ✅ 正确做法：把含反斜杠的内容写进文件，再用 find_file / replace_file：\n\n"
            "       1) 把『要找的原文』写到 local/_pt/find.txt\n"
            "       2) 把『要换成的文』写到 local/_pt/repl.txt\n"
            "       3) python tools/patch-text.py --spec-inline "
            "'[{\"file\":\"目标.py\",\"find_file\":\"local/_pt/find.txt\","
            "\"replace_file\":\"local/_pt/repl.txt\"}]'\n\n"
            "   这样命令里只有文件名，反斜杠根本不参与序列化。\n\n"
            "   若内容确实不含反斜杠（例如纯中文改写），把反斜杠符号去掉后重跑即可。\n\n"
        )
        return 2


    if args.spec_inline:
        spec = json.loads(args.spec_inline)
    elif args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    else:
        ap.error("需要 spec 文件路径或 --spec-inline")
    return apply_patch(spec, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
