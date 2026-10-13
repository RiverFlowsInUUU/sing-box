#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mknode.py —— 一条命令：分享链接 → 可运行配置 → 门禁 → 落到 local/

用法：
    python tools/mknode.py 'vless://...' --platform ios --group proxy
    python tools/mknode.py 'vmess://...' 'ss://...' --platform android --group ai --name 香港节点
    python tools/mknode.py 'hy2://...' -p desktop -g proxy --keep-placeholders
    python tools/mknode.py 'vless://...' -p ios -g proxy --dry-run

它做四件事，一步不落：
    1. 解码链接（调 tools/share-link.py，不重复实现解码逻辑）
    2. 读 profiles/<ver>/<platform>-lazy.json 当骨架，换掉占位节点
    3. 把新节点 tag 加进指定分流组的 outbounds
    4. 跑 tools/audit.py 门禁（含 sing-box check），全绿才落盘

**默认写哪里**：`local/<platform>.json`（.gitignore 已忽略，永不提交）。
    `local/` 下只允许真实节点 —— 这是**正常且预期**的，audit.py 的
    `placeholder_server` 只对 `profiles/` 生效。

**为什么要有这个脚本**（详见 docs/DRIVER.md）：
    过去「给节点 → 出配置」是一次自由发挥：AI 得先把 6 万 token 的文档读一遍，
    再凭对铁律的记忆手拼 JSON，错了改、改了错。
    现在这条路是**铺好的**：链接格式对 ⇒ outbound 对（share-link.py）；
    骨架对、组名对、不删字段 ⇒ 配置对（本脚本的结构化改写）；
    真错 ⇒ audit.py 当场点名。

    「守交规就能快速通过」= 交规已经内置在收费站里，司机只要停车交钱（给链接）。

退出码：0 = 已生成且门禁全绿；1 = 有错（不会落盘）；2 = 用法/环境问题
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
LOCAL = ROOT / "local"
VERSION_FILE = ROOT / "singbox_version.txt"

# 与 audit.py 的 GROUP_* 常量逐字一致。组名写错等价于「tag 找不到」——
# check 不报，运行时报 outbound not found 或静默落到 final（AGENTS.md 铁律 20）。
GROUP_ALIASES = {
    "proxy": "🚀 Proxy", "🚀 proxy": "🚀 Proxy", "🚀": "🚀 Proxy",
    "ai": "🤖 AI", "🤖 ai": "🤖 AI", "🤖": "🤖 AI",
}
AD_GROUP = "🚫 AD"
PLATFORMS = ("desktop", "android", "ios")


class MkError(Exception):
    """用户可读的错误 —— 报出来，不要 traceback。"""


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def read_version() -> str:
    if not VERSION_FILE.exists():
        raise MkError(f"缺少 {VERSION_FILE}（它是唯一的版本真相）")
    return VERSION_FILE.read_text(encoding="utf-8").strip().split()[0]


def skeleton_path(version: str, platform: str) -> Path:
    major = ".".join(version.split(".")[:2])
    p = PROFILES / major / f"{platform}-lazy.json"
    if not p.exists():
        raise MkError(f"找不到骨架 {p.relative_to(ROOT)}（锁定版本 {version}）")
    return p


def decode_links(links: list) -> list:
    """调 share-link.py 拿 outbound 对象。解码逻辑只有一份，不复制。"""
    tool = ROOT / "tools" / "share-link.py"
    if not tool.exists():
        raise MkError(f"缺少 {tool.relative_to(ROOT)}（它负责链接 → outbound）")
    proc = _run([sys.executable, str(tool), "--ndjson", *links])
    if proc.returncode != 0:
        raise MkError("链接解码失败：\n" + (proc.stderr or "").strip())
    out = []
    for ln in proc.stdout.splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    if not out:
        raise MkError("没有解出任何节点")
    return out


def identify_placeholder(cfg: dict) -> list:
    """找出骨架里的占位节点，返回 [(index, tag, type), ...]。

    判据用 audit.py 的同一套 PLACEHOLDER_DOMAINS：`.example.com` 等。
    不去猜「Node-01 这种名字」——名字可以改，域名后缀是仓库契约。
    """
    suffix = (".example.com", ".example.org", ".example.net",
              ".invalid", ".test", ".localhost")
    idx = []
    for i, ob in enumerate(cfg.get("outbounds", [])):
        if not isinstance(ob, dict):
            continue
        srv = ob.get("server")
        if isinstance(srv, str) and srv and srv.endswith(suffix):
            idx.append((i, ob.get("tag"), ob.get("type")))
    return idx


def resolve_group(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in ("ad",):
        raise MkError(
            f"{AD_GROUP} 组只放 block，永远不放代理节点（铁律 6 / 13）。\n"
            "  广告拦截靠规则集分流，不需要把节点放进去。"
        )
    if key not in GROUP_ALIASES:
        raise MkError(
            f"不认识的分流组 {raw!r}。可用：proxy（{GROUP_ALIASES['proxy']}）、"
            f"ai（{GROUP_ALIASES['ai']}）。\n"
            f"  {AD_GROUP} 不接受节点：它的 outbounds 恒为 ['block']。"
        )
    return GROUP_ALIASES[key]


def build(version: str, platform: str, nodes: list, group: str,
          keep_placeholders: bool, names: list) -> tuple:
    skel = skeleton_path(version, platform)
    cfg = json.loads(skel.read_text(encoding="utf-8"))
    if "outbounds" not in cfg:
        raise MkError(f"{skel.relative_to(ROOT)} 里没有 outbounds")

    # ① 给节点起名：用户给了就用，否则用链接里的 tag，再不行用 type-platform-N
    used = {ob.get("tag") for ob in cfg["outbounds"] if isinstance(ob, dict)}
    for i, nd in enumerate(nodes):
        want = (names[i] if i < len(names) and names[i] else nd.get("tag") or "").strip()
        if not want:
            want = f"{nd['type']}-{platform}-{i + 1}"
        base, n = want, 2
        while want in used:
            want = f"{base} {n}"
            n += 1
        nd["tag"] = want
        used.add(want)

    # ② 占位节点怎么处理
    placeholder = identify_placeholder(cfg)
    old_tags = [t for _, t, _ in placeholder]
    if not keep_placeholders:
        drop = {i for i, _, _ in placeholder}
        cfg["outbounds"] = [ob for i, ob in enumerate(cfg["outbounds"]) if i not in drop]
        # 占位 tag 也要从每个组的 outbounds 里摘掉，否则留下悬空引用
        for ob in cfg["outbounds"]:
            if isinstance(ob, dict) and isinstance(ob.get("outbounds"), list):
                ob["outbounds"] = [t for t in ob["outbounds"] if t not in old_tags]

    # ③ 插节点：放在第一个组之前，保持「节点在前、组在后」的骨架排版
    insert_at = next(
        (i for i, ob in enumerate(cfg["outbounds"])
         if isinstance(ob, dict) and ob.get("type") in ("selector", "urltest")),
        len(cfg["outbounds"]),
    )
    cfg["outbounds"][insert_at:insert_at] = nodes

    # ④ 把新 tag 加进目标组
    target = next((ob for ob in cfg["outbounds"]
                   if isinstance(ob, dict) and ob.get("tag") == group), None)
    if target is None:
        raise MkError(f"骨架里找不到分流组 {group!r}——骨架结构变了？")
    if not isinstance(target.get("outbounds"), list):
        raise MkError(f"分流组 {group!r} 没有 outbounds 数组")
    for nd in nodes:
        if nd["tag"] not in target["outbounds"]:
            target["outbounds"].append(nd["tag"])

    # ⑤ 不允许留下空组 —— 这是**真内核**抓出来的一个 FATAL：
    #    `initialize outbound[N]: missing tags`（selector / urltest 的 outbounds 不能为空）。
    #    成因：骨架里两个 urltest 组都引用占位节点，删掉占位之后**没被指定的那个组**就空了。
    #    audit.py 对骨架只报 WARN（"骨架模板允许"），所以这里必须自己兜住。
    empties = [
        ob["tag"] for ob in cfg["outbounds"]
        if isinstance(ob, dict)
        and ob.get("type") in ("selector", "urltest")
        and not ob.get("outbounds")
    ]

    return cfg, skel, old_tags, empties


def run_audit(path: Path, platform: str) -> tuple:
    tool = ROOT / "tools" / "audit.py"
    proc = _run([sys.executable, str(tool), str(path), "--platform", platform])
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="分享链接 → 可运行配置 → 门禁 → local/<platform>.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例子：\n"
            "  python tools/mknode.py 'vless://...' -p ios -g proxy\n"
            "  python tools/mknode.py 'vmess://...' 'ss://...' -p desktop -g ai --name 香港\n"
            "\n"
            "产物落 local/<platform>.json（已 gitignore，永不提交）。\n"
            "默认删掉骨架里的占位节点；要保留加 --keep-placeholders。\n"
        ),
    )
    ap.add_argument("links", nargs="+", help="一条或多条分享链接")
    ap.add_argument("-p", "--platform", required=True,
                    choices=PLATFORMS, help="目标平台")
    ap.add_argument("-g", "--group", required=True,
                    help="落哪个分流组：proxy / ai（ad 不接受节点）")
    ap.add_argument("-n", "--name", action="append", default=[],
                    help="节点名，可重复（按顺序对应链接）；不写则用链接里的 tag")
    ap.add_argument("--out", help="输出路径，默认 local/<platform>.json")
    ap.add_argument("--keep-placeholders", action="store_true",
                    help="保留骨架里的占位节点（默认删掉）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只预览，不写盘、不跑门禁")
    ap.add_argument("--no-audit", action="store_true",
                    help="跳过门禁（不推荐；只在你明确知道自己在干什么时用）")
    args = ap.parse_args()

    try:
        version = read_version()
        group = resolve_group(args.group)
        nodes = decode_links(args.links)
        cfg, skel, old_tags, empties = build(
            version, args.platform, nodes, group,
            args.keep_placeholders, args.name,
        )
    except MkError as ex:
        print(f"[E] {ex}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as ex:
        print(f"[E] JSON 解析失败：{ex}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else (LOCAL / f"{args.platform}.json")
    text = json.dumps(cfg, ensure_ascii=False, indent=4) + "\n"

    print(f"版本   {version}")
    print(f"骨架   {skel.relative_to(ROOT)}  ({args.platform})")
    print(f"分流组 {group}")
    for ob in cfg["outbounds"]:
        if isinstance(ob, dict) and ob.get("tag") == group:
            print(f"        outbounds = {ob['outbounds']}")
    print(f"新节点 {[ob['tag'] for ob in nodes]}")
    if old_tags:
        verb = "保留" if args.keep_placeholders else "移除"
        print(f"占位节点 {verb}：{old_tags}")

    # 没被指定的那个组会空掉 —— 空组是真 FATAL（missing tags），不能就这么发出去
    if empties and not args.keep_placeholders:
        print(f"\n[!] 这几个组本来只引用占位节点，删掉占位后会空：{empties}")
        if args.group in empties:
            print(f"[E] 目标组 {args.group!r} 自己就是空的 —— 不应该发生，请报 bug", file=sys.stderr)
            return 2
        print(f"    已把新节点同时放进这些组（否则 sing-box 启动即 FATAL: missing tags）。")
        for ob in cfg["outbounds"]:
            if isinstance(ob, dict) and ob.get("tag") in empties:
                ob["outbounds"] = [n["tag"] for n in nodes]
        text = json.dumps(cfg, ensure_ascii=False, indent=4) + "\n"

    print(f"输出   {out}")

    if args.dry_run:
        print("\n--- dry-run：配置预览（未写盘）---")
        print(text)
        return 0

    if args.no_audit:
        print("\n[!] 已跳过门禁（--no-audit）。跑 `python tools/audit.py <file> --platform "
              f"{args.platform}` 自己补上。", file=sys.stderr)

    # ── 门禁：先写盘再查（audit.py 要读文件；写的是 gitignore 掉的 local/）──
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    if not args.no_audit:
        print()
        rc, output = run_audit(out, args.platform)
        print(output.strip())
        if rc != 0:
            print(f"\n[E] 门禁未全绿 —— 配置在 {out}，但**先别发出去**，看上面的 [E] 行。",
                  file=sys.stderr)
            return 1
        print(f"\n[OK] 门禁全绿。配置：{out}")

    print("\n下一步：把这份 JSON 导入 sing-box 客户端。")
    print("  · 它含真实节点 —— 别 commit、别 push（local/ 已 gitignore）")
    print("  · 想复核改了什么：python tools/diff_config.py <你原来的配置> " + str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
