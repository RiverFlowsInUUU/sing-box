#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen-docs.py — 由 docs/version-matrix.json 生成 docs/VERSION-MATRIX.md（人读版）

用法：
    python tools/gen-docs.py            # 写入 docs/VERSION-MATRIX.md
    python tools/gen-docs.py --stdout   # 只打印

为什么要生成而不是手写：手写必然与 JSON 漂移，而 JSON 才是 audit.py 的依据。
改矩阵只改 JSON，然后重新生成本文件。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "version-matrix.json"
OUT = ROOT / "docs" / "VERSION-MATRIX.md"

KIND_LABEL = {
    "deprecated": "废弃中",
    "removed": "已移除",
    "platform": "平台限制",
    "semantic": "语义变更",
    "new": "新功能采纳",
    "info": "仅存档",
}

# kind=new 的采纳决策中文标签
ADOPT_LABEL = {
    "yes": "启用",
    "no": "不启用",
    "must": "必须跟随",
}


def parse_version(v):
    import re

    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    entries = data["entries"]

    L = []
    L.append("# VERSION-MATRIX.md — 字段生命周期总表")
    L.append("")
    L.append("> **本文件由 `tools/gen-docs.py` 从 `docs/version-matrix.json` 生成，请勿手改。**")
    L.append("> 要改内容请改 JSON，然后运行 `python tools/gen-docs.py`。")
    L.append("")
    L.append("`tools/audit.py` 读的就是那份 JSON；本文件只是给人看的快照。")
    L.append("")
    L.append("## 怎么用这张表")
    L.append("")
    L.append("- **废弃中**：当前正式版仍能用，但官方已宣布将来移除 → 新写的配置不要再用。")
    L.append("- **已移除**：用即 `FATAL`，配置起不来 → 必须按「替代写法」改。")
    L.append("- **平台限制**：字段本身合法，但目标客户端没实现 → `sing-box check` 不会报错，要靠人看。")
    L.append("- **语义变更**：字段名没变但默认行为变了 → 不报错，容易悄悄出错。")
    L.append("- **新功能采纳**：上游新增的能力 → **没有默认答案**；本仓库必须逐条写下「启用 / 不启用 / 必须跟随」与理由，留空即门禁 ERROR。")
    L.append("")
    L.append("## 一、按移除版本排序（越靠前越紧急）")
    L.append("")
    L.append("> 本表只含「存量字段的命运」（废弃/移除/平台/语义）；**新功能的采纳决策见第二节**。")
    L.append("")
    L.append("| 移除版本 | 废弃版本 | 类别 | 字段 | 替代写法 |")
    L.append("|---|---|---|---|---|")

    def sort_key(e):
        return (
            parse_version(e.get("removed_in") or "99.99.99"),
            e.get("id", ""),
        )

    for e in sorted([x for x in entries if x.get("kind") != "new"], key=sort_key):
        path = e.get("path")
        if not path and e.get("type_check"):
            tc = e["type_check"]
            path = f"{tc.get('where')}[].type = {tc.get('equals') or tc.get('in')}"
        if not path:
            path = e.get("semantic") or e["id"]
        L.append(
            "| {rem} | {dep} | {kind} | `{path}` | {repl} |".format(
                rem=e.get("removed_in") or "—",
                dep=e.get("deprecated_in") or "—",
                kind=KIND_LABEL.get(e.get("kind"), e.get("kind")),
                path=path,
                repl=(e.get("replacement") or "—"),
            )
        )

    L.append("")
    L.append("## 二、新功能采纳决策（kind=new）")
    L.append("")
    L.append("> 上游新增的能力**不带默认答案**。本仓库的铁律是：每个新功能都必须显式写下")
    L.append("> 「启用 / 不启用 / 必须跟随」与理由，否则 `tools/audit.py` 直接 ERROR。")
    L.append("> 升级前先看 `python tools/upgrade-check.py` 报告的第 5 节，它会列出还没做决策的新功能。")
    L.append("")
    pinned_ver = ""
    _pf = ROOT / "singbox_version.txt"
    if _pf.exists():
        pinned_ver = _pf.read_text(encoding="utf-8").strip().split()[0]
    news = [e for e in entries if e.get("kind") == "new"]
    if not news:
        L.append("**没有任何 `kind=new` 条目 —— 新功能采纳机制等于不存在。**")
    else:
        L.append("| 决策 | 自版本 | 决策截止 | 条目 | 说明 |")
        L.append("|---|---|---|---|---|")
        for e in sorted(news, key=lambda x: (ADOPT_LABEL.get(x.get("adopt"), "9"), x.get("id", ""))):
            db = e.get("decide_by")
            overdue = ""
            if db and pinned_ver and parse_version(pinned_ver) >= parse_version(db):
                overdue = " ⚠️已到期"
            L.append(
                "| {a} | {s} | {d} | `{i}` | {t} |".format(
                    a=ADOPT_LABEL.get(e.get("adopt"), e.get("adopt") or "**缺失**"),
                    s=e.get("since") or "—",
                    d=(db or "—") + overdue,
                    i=e.get("id", "?"),
                    t=(e.get("title") or "").replace("|", "/"),
                )
            )
        L.append("")
        L.append("决策含义：")
        L.append("")
        L.append("- **必须跟随**：旧写法被取代，不是「要不要开」而是「旧字段要删」（通常配套一条 `removed` 条目）。")
        L.append("- **启用**：功能已采纳，配置里应当有对应字段（矩阵里写 `expect: present`，门禁会验）。")
        L.append("- **不启用**：明确放弃，配置里必须**没有**该字段（矩阵里写 `expect: absent`，门禁会验）。")
    L.append("")
    L.append("## 三、本次锁定的正式版视角")
    L.append("")
    pinned_file = ROOT / "singbox_version.txt"
    pinned = ""
    if pinned_file.exists():
        pinned = pinned_file.read_text(encoding="utf-8").strip().split()[0]
    L.append(f"锁定版本：**{pinned or '未记录'}**")
    L.append("")
    soon = [
        e
        for e in entries
        if e.get("removed_in")
        and parse_version(e["removed_in"]) > parse_version(pinned)
        and e.get("deprecated_in")
        and parse_version(pinned) >= parse_version(e["deprecated_in"])
    ]
    if soon:
        L.append(f"### 在 {pinned} 下**已废弃但还没移除**的字段（新配置一律别用）")
        L.append("")
        for e in sorted(soon, key=sort_key):
            path = e.get("path") or e.get("semantic") or e["id"]
            L.append(f"- `{path}` — 将于 **{e['removed_in']}** 移除；改用：{e.get('replacement', '')}")
    else:
        L.append("没有处于「已废弃未移除」窗口的字段。")
    L.append("")

    L.append("## 四、完整明细（含说明与官方链接）")
    L.append("")
    for e in sorted(entries, key=lambda x: x.get("id", "")):
        L.append(f"### `{e['id']}`")
        L.append("")
        L.append(f"- 类别：{KIND_LABEL.get(e.get('kind'), e.get('kind'))}")
        if e.get("adopt"):
            L.append(f"- 采纳决策：{ADOPT_LABEL.get(e['adopt'], e['adopt'])}（`adopt={e['adopt']}`）")
        if e.get("since"):
            L.append(f"- 自版本：{e['since']}")
        if e.get("decide_by"):
            L.append(f"- 决策截止：{e['decide_by']}")
        if e.get("expect"):
            L.append(f"- 配置应有状态：`{e['expect']}`")
        if e.get("deprecated_in"):
            L.append(f"- 废弃于：{e['deprecated_in']}")
        if e.get("removed_in"):
            L.append(f"- 移除于：{e['removed_in']}")
        if e.get("path"):
            L.append(f"- 字段路径：`{e['path']}`")
        if e.get("type_check"):
            L.append(f"- 判定方式：outbounds/endpoints 中 `type` 等于 `{e['type_check']}`")
        if e.get("platforms"):
            L.append(f"- 受影响平台：{'、'.join(e['platforms'])}")
        if e.get("replacement"):
            L.append(f"- 替代写法：{e['replacement']}")
        if e.get("reason"):
            L.append(f"- 采纳理由：{e['reason']}")
        if e.get("keywords"):
            L.append(f"- 覆盖关键词：{', '.join('`'+k+'`' for k in e['keywords'])}")
        if e.get("note"):
            L.append(f"- 备注：{e['note']}")
        if e.get("doc"):
            L.append(f"- 官方：{e['doc']}")
        L.append("")

    L.append("## 五、怎么更新这张表")
    L.append("")
    L.append("```bash")
    L.append("python tools/upgrade-check.py          # 看上游新的废弃项 + 还没做决策的新功能")
    L.append("# 按报告把新条目写进 docs/version-matrix.json 的 entries[]")
    L.append("#   废弃类：kind / deprecated_in / removed_in / path / replacement")
    L.append("#   新功能：kind=new / since / adopt / reason / decide_by / keywords")
    L.append("python tools/gen-docs.py               # 重新生成本文件")
    L.append("python tools/audit.py                  # 门禁必须 0 ERROR")
    L.append("```")
    L.append("")

    text = "\n".join(L)
    if args.stdout:
        print(text)
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"已写入 {OUT}（{len(text)} 字符，{len(entries)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
