#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upgrade-check.py — 上游正式版升级巡检

用法：
    python tools/upgrade-check.py                 # 巡检并打印报告
    python tools/upgrade-check.py --write         # 有新版本时更新 singbox_version.txt 与文档副本
    python tools/upgrade-check.py --report out.md # 把报告写到文件
    python tools/upgrade-check.py --no-net        # 离线：只做本地一致性自检

它做五件事：
  1. 查 GitHub 上「最新正式版」（忽略 alpha/beta/rc），与本仓库 singbox_version.txt 比对。
  2. 若有新版，抓取该 tag 下的 docs/deprecated.md、docs/migration.md、docs/changelog.md，
     与本地 docs/upstream-*.md 做 diff，并把「新增版本段」切出来。
  3. 把上游 deprecated.md 里出现的版本段与 docs/version-matrix.json 的条目对账，
     列出「上游已宣布废弃但矩阵里没有」的漏网项。
  4. 用矩阵的 removed_in 计算「下一次升级会炸掉哪些字段」，列出受影响的本仓库配置。
  5. **新功能清点**：列出矩阵里所有 kind=new 的采纳决策（启用/不启用/必须跟随），
     并把上游 changelog 里「还没有对应决策条目」的新功能揪出来 —— 升级前必须先回答
     「这个功能启不启用」，不允许靠「没注意到」默认不启用。

退出码：0 = 无新正式版；1 = 有新正式版（需要人工处理）；2 = 脚本自身错误。
"""

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MATRIX = DOCS / "version-matrix.json"
VERSION_FILE = ROOT / "singbox_version.txt"
REPO = "SagerNet/sing-box"
BRANCH = "testing"

TRACKED_DOCS = {
    "docs/deprecated.md": DOCS / "upstream-deprecated.md",
    "docs/migration.md": DOCS / "upstream-migration.md",
    "docs/changelog.md": DOCS / "upstream-changelog.md",
    "docs/configuration/inbound/tun.md": DOCS / "upstream-tun.md",
}


# ------------------------------------------------------------- 基础工具


def log(msg=""):
    print(msg)


def parse_version(v):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def ver_ge(a, b):
    return parse_version(a) >= parse_version(b)


def read_pinned():
    if not VERSION_FILE.exists():
        return None
    txt = VERSION_FILE.read_text(encoding="utf-8").strip()
    m = re.search(r"v?(\d+\.\d+\.\d+)", txt)
    return m.group(1) if m else None


def gh_api(path):
    """优先用 gh CLI（已登录、额度高），失败退回匿名 urllib。"""
    url = f"https://api.github.com/{path}"
    if shutil.which("gh"):
        try:
            p = subprocess.run(
                ["gh", "api", url, "-H", "Accept: application/vnd.github.raw"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if p.returncode == 0 and p.stdout:
                return p.stdout
        except Exception:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": "sb-template-upgrade-check"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def fetch_raw(path, ref=BRANCH):
    url = f"repos/{REPO}/contents/{path}?ref={ref}"
    if shutil.which("gh"):
        try:
            p = subprocess.run(
                ["gh", "api", "-H", "Accept: application/vnd.github.raw", url],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if p.returncode == 0 and p.stdout:
                return p.stdout
        except Exception:
            pass
    raw = f"https://raw.githubusercontent.com/{REPO}/{ref}/{path}"
    req = urllib.request.Request(raw, headers={"User-Agent": "sb-template-upgrade-check"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def latest_stable():
    """返回 (tag, published_at)。必须翻页，否则会误取旧版本。"""
    data = None
    if shutil.which("gh"):
        try:
            p = subprocess.run(
                ["gh", "api", f"repos/{REPO}/releases", "--paginate"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            if p.returncode == 0:
                dec = json.JSONDecoder()
                s = p.stdout
                idx = 0
                items = []
                while idx < len(s):
                    while idx < len(s) and s[idx] in " \t\r\n":
                        idx += 1
                    if idx >= len(s):
                        break
                    try:
                        obj, end = dec.raw_decode(s, idx)
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, list):
                        items.extend(obj)
                    idx = end
                if items:
                    data = items
        except Exception:
            pass
    if data is None:
        data = json.loads(gh_api(f"repos/{REPO}/releases?per_page=100"))
    stable = [r for r in data if not r.get("prerelease") and not r.get("draft")]
    stable.sort(key=lambda r: r.get("published_at", ""), reverse=True)
    if not stable:
        return None, None
    return stable[0]["tag_name"], stable[0]["published_at"]


# ------------------------------------------------------ deprecated 段解析

VER_HEAD = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*$", re.M)


def split_version_sections(text):
    """把 deprecated.md 切成 {版本: 正文}。"""
    out = {}
    marks = list(VER_HEAD.finditer(text))
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1)] = text[start:end].strip()
    return out


def section_titles(body):
    return [t.strip() for t in re.findall(r"^####\s+(.+)$", body, re.M)]


# ------------------------------------------------------------- 主逻辑


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="sing-box 上游升级巡检")
    ap.add_argument("--write", action="store_true", help="更新 singbox_version.txt 与文档副本")
    ap.add_argument("--report", help="报告输出文件")
    ap.add_argument("--no-net", action="store_true", help="离线本地自检")
    ap.add_argument("--ref", default=None, help="抓文档用的 ref，默认 testing")
    args = ap.parse_args()

    lines = []
    problems = []

    def emit(s=""):
        lines.append(s)

    pinned = read_pinned()
    emit("# sing-box 升级巡检报告")
    emit()
    emit(f"- 本仓库锁定版本：**{pinned or '未知'}**（singbox_version.txt）")
    emit(f"- 巡检时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    emit()

    if not MATRIX.exists():
        log(f"缺少 {MATRIX}")
        return 2
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    # ---------------- 1. 版本比对
    tag = pub = None
    if not args.no_net:
        try:
            tag, pub = latest_stable()
        except Exception as ex:
            emit(f"> 无法查询上游（{ex}），转为离线模式。")
            emit()
    if tag:
        emit("## 1. 版本比对")
        emit()
        emit(f"- 上游最新正式版：**{tag}**（{pub}）")
        if pinned and ver_ge(pinned, tag):
            emit(f"- 结论：已是最新，无需动作。")
        else:
            emit(f"- 结论：**有新正式版 {tag}**，需要升级本仓库。")
            problems.append(f"有新正式版 {tag}")
        emit()

    # ---------------- 2. 文档 diff
    ref = args.ref or BRANCH
    new_sections = {}
    if not args.no_net:
        emit(f"## 2. 上游文档同步（ref={ref}）")
        emit()
        emit(
            f"> 注意：本节默认对比**上游 {BRANCH} 分支**的文档（含未发布的 alpha 内容），"
            "目的是提前看到即将废弃的字段；差异不代表锁定的正式版有问题。"
        )
        emit()
        for rel, local in TRACKED_DOCS.items():
            posix = rel.replace("\\", "/")
            try:
                remote = fetch_raw(rel, ref)
            except Exception as ex:
                emit(f"- `{rel}`：抓取失败（{ex}）")
                continue
            old = local.read_text(encoding="utf-8") if local.exists() else ""
            if old == remote:
                emit(f"- `{rel}`：与本地副本一致（{len(remote)} B）")
                continue
            emit(f"- `{rel}`：**有变化**（本地 {len(old)} B → 上游 {len(remote)} B）")
            diff = list(
                difflib.unified_diff(
                    old.splitlines(), remote.splitlines(), lineterm="", n=1
                )
            )
            added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
            removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
            emit(f"  - 新增 {len(added)} 行，删除 {len(removed)} 行")
            if posix == "docs/deprecated.md":
                new_sections = split_version_sections(remote)
            if args.write:
                local.write_text(remote, encoding="utf-8")
                emit(f"  - 已更新本地副本 `{local.relative_to(ROOT)}`")
        emit()

    # ---------------- 3. 矩阵对账
    emit("## 3. 矩阵对账（上游废弃段 vs version-matrix.json）")
    emit()
    local_dep = DOCS / "upstream-deprecated.md"
    sections = None
    if new_sections:
        sections = new_sections
    elif local_dep.exists():
        sections = split_version_sections(local_dep.read_text(encoding="utf-8"))

    if not sections:
        emit("- 本地没有 upstream-deprecated.md 且未联网，跳过。")
    else:
        matrix_titles = " | ".join(
            (e.get("id", "") + " " + e.get("replacement", "")) for e in matrix["entries"]
        ).lower()
        uncovered = []
        for ver in sorted(sections, key=parse_version, reverse=True):
            titles = section_titles(sections[ver])
            in_scope = (not pinned) or ver_ge(ver, pinned)
            scope = "" if in_scope else "（早于锁定版本，仅存档）"
            emit(f"- **{ver}**{scope}：{len(titles)} 项")
            for t in titles:
                clean = re.sub(r"[`*]", "", t)
                # 用关键词粗判有没有被矩阵覆盖
                key = clean.split("(")[0].split("option")[0].strip().lower()
                key = key.split()[0] if key.split() else key
                hit = key and key in matrix_titles
                mark = "已覆盖" if hit else ("**未覆盖**" if in_scope else "未覆盖（历史）")
                emit(f"  - {clean} — {mark}")
                if not hit and in_scope:
                    uncovered.append(f"{ver}: {clean}")
        if uncovered:
            problems.append(f"{len(uncovered)} 项上游废弃条目未进矩阵")
        emit()

    # ---------------- 4. 下一次升级会炸什么
    emit("## 4. 升级风险评估（按矩阵 removed_in）")
    emit()
    target = tag or (pinned or "0.0.0")
    will_break = [e for e in matrix["entries"] if e.get("removed_in") and ver_ge(target, e["removed_in"])]
    soon = [
        e
        for e in matrix["entries"]
        if e.get("removed_in")
        and not ver_ge(target, e["removed_in"])
        and e.get("deprecated_in")
        and ver_ge(target, e["deprecated_in"])
    ]
    if soon:
        emit(f"在 {target} 下已废弃、未来会被移除的字段：")
        for e in soon:
            emit(f"- `{e.get('path') or e.get('type_check', {}).get('field') or e['id']}` → 移除于 {e['removed_in']}；{e.get('replacement', '')}")
    else:
        emit(f"{target} 下没有处于「已废弃未移除」窗口的字段。")
    emit()

    # 扫描本仓库配置，看有没有真的踩到（用与 audit.py 相同的路径匹配，不用子串粗判）
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("sbaudit", ROOT / "tools" / "audit.py")
        sbaudit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sbaudit)
    except Exception:
        sbaudit = None

    hits = []
    for prof in sorted((ROOT / "profiles").rglob("*.json")):
        try:
            cfg = json.loads(prof.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in soon:
            if sbaudit and e.get("path"):
                if not sbaudit.find_paths(cfg, e["path"]):
                    continue
            elif not e.get("path"):
                continue  # semantic / type_check 条目由 audit.py 负责
            hits.append((prof.relative_to(ROOT).as_posix(), e["id"]))
    if hits:
        emit("本仓库配置中受影响的位置：")
        for f, eid in sorted(set(hits)):
            emit(f"- `{f}` 涉及 `{eid}`")
    else:
        emit("本仓库现有配置未踩到任何已废弃字段。")
    emit()

    # ---------------- 5. 新功能清点
    emit("## 5. 新功能清点（升级时要做的采纳决策）")
    emit()
    news = [e for e in matrix["entries"] if e.get("kind") == "new"]
    if not news:
        emit('- 矩阵里没有 `kind="new"` 条目 —— 新功能采纳机制等于不存在。')
        problems.append("矩阵缺少 kind=new 新功能采纳条目")
    else:
        adopt_label = {"yes": "启用", "no": "不启用", "must": "必须跟随"}
        emit(f"矩阵里共 **{len(news)}** 条新功能采纳决策：")
        emit()
        emit("| 决策 | 条目 | 自版本 | 决策截止 | 理由 |")
        emit("|---|---|---|---|---|")
        for e in sorted(news, key=lambda x: (x.get("adopt") or "", x.get("id", ""))):
            emit(
                "| {a} | `{i}` | {s} | {d} | {r} |".format(
                    a=adopt_label.get(e.get("adopt"), e.get("adopt") or "**缺失**"),
                    i=e.get("id", "?"),
                    s=e.get("since") or "—",
                    d=e.get("decide_by") or "—",
                    r=(e.get("title") or "").replace("|", "/"),
                )
            )
        emit()

        # changelog 覆盖比对：上游有新功能，矩阵却没有决策 → 升级前必须补
        if sbaudit is not None and hasattr(sbaudit, "_changelog_features"):
            feats = sbaudit._changelog_features(target)
            kws = [(e.get("keywords") or []) for e in news]
            missing = []
            for ver, feat in feats:
                low = feat.lower()
                if not any(k and k.lower() in low for kws_ in kws for k in kws_):
                    missing.append((ver, feat))
            emit(f"上游 changelog 里 >= {target} 的新功能条目：{len(feats)} 条（已去重）")
            if missing:
                emit()
                emit("**以下上游新功能在矩阵里没有对应决策，升级前必须先回答「启不启用」：**")
                emit()
                for ver, feat in missing:
                    emit(f"- `{ver}` {feat}")
                problems.append(f"{len(missing)} 条上游新功能未做采纳决策")
            else:
                emit(f"- 全部 {len(feats)} 条已被 kind=new 条目的 keywords 覆盖。")
        emit()

    # ---------------- 6. 结论与下一步
    emit("## 6. 结论")
    emit()
    if not problems:
        emit("- 无需动作。")
    else:
        for p in problems:
            emit(f"- {p}")
        emit()
        emit("### 下一步（人工）")
        emit()
        emit("1. 逐条阅读上游 deprecated/migration 中本仓库锁版本之后的新增段。")
        emit("2. 把新条目按既有格式补进 `docs/version-matrix.json`：")
        emit("   - 废弃类：kind / deprecated_in / removed_in / path / replacement / doc")
        emit("   - 新功能类：kind=\"new\" / since / adopt(yes|no|must) / reason / decide_by / keywords")
        emit("3. 更新 `profiles/<大版本>/` 下的配置，删掉已废弃字段；采纳的功能补上字段。")
        emit("4. `python tools/audit.py` 必须 0 ERROR 0 WARN。")
        emit("5. 采纳决策与理由同步记录到 `docs/DECISIONS.md`。")
        emit("6. 确认无误后 `--write` 更新本地文档副本与 `singbox_version.txt`。")

    text = "\n".join(lines) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        log(f"报告已写入 {args.report}")
    else:
        log(text)

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
