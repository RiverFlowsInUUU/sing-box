#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py — sing-box 配置门禁（离线结构化审查 + 可选调用 sing-box check）

用法：
    python tools/audit.py                                  # 审查 profiles/ 下全部配置
    python tools/audit.py profiles/1.14/ios-lazy.json      # 审查单个文件
    python tools/audit.py --platform ios --version 1.14.3 <file>
    python tools/audit.py --singbox C:/path/to/sing-box.exe
    python tools/audit.py --json                           # 机器可读输出

设计依据：docs/version-matrix.json（字段生命周期）、docs/PLATFORM-MATRIX.md（平台能力）。
为什么需要它：`sing-box check` 只做字段解码，对「已废弃但未移除的字段」静默通过
（例如 download_detour），并且完全不校验平台能力（iOS 写 strict_route 也 exit=0）。
本脚本用来补这两个洞。

退出码：0 = 通过（可能带 WARN）；1 = 有 ERROR；2 = 脚本自身用法错误。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "version-matrix.json"
PROFILES = ROOT / "profiles"
ALLOWED_RULESET_PREFIXES = (
    "https://testingcf.jsdelivr.net/gh/",
    "https://cdn.jsdelivr.net/gh/",
    "https://fastly.jsdelivr.net/gh/",
    "https://gcore.jsdelivr.net/gh/",
)

# ---------------------------------------------------------------- 版本比较


def parse_version(v: str):
    """'1.14.3' -> (1,14,3)；'v1.15.0-alpha.12' -> (1,15,0, 'alpha', 12) 的宽松形式。

    我们只比较正式版数字部分，预发布后缀一律忽略（本仓库只面向正式版）。
    """
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        return (0, 0, 0)
    return tuple(int(x) for x in m.groups())


def ver_ge(a: str, b: str) -> bool:
    return parse_version(a) >= parse_version(b)


# ---------------------------------------------------------------- 路径匹配

SEG_RE = re.compile(r"^([A-Za-z0-9_\-]*)(\[([^\]]*)\])?$")


def _walk(node, segs, path, out):
    if not segs:
        out.append((path, node))
        return
    seg = segs[0]
    rest = segs[1:]

    if seg == "**":
        # 匹配零段
        _walk(node, rest, path, out)
        # 匹配一段后继续
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, segs, f"{path}.{k}" if path else str(k), out)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, segs, f"{path}[{i}]", out)
        return

    m = SEG_RE.match(seg)
    if not m:
        return
    key, has_filter, flt = m.group(1), m.group(2) is not None, m.group(3)

    cur = node
    if key:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
        path = f"{path}.{key}" if path else key

    if has_filter:
        if not isinstance(cur, list):
            return
        for i, v in enumerate(cur):
            if flt == "":
                _walk(v, rest, f"{path}[{i}]", out)
            elif "=" in flt:
                k, val = flt.split("=", 1)
                if isinstance(v, dict) and str(v.get(k)) == val:
                    _walk(v, rest, f"{path}[{i}]", out)
            elif flt == "any":
                _walk(v, rest, f"{path}[{i}]", out)
            # 其他过滤语法暂不支持
        return

    _walk(cur, rest, path, out)


def find_paths(cfg, path: str):
    """返回 [(实际路径, 该处节点对象)]"""
    out = []
    _walk(cfg, [s for s in path.split(".") if s != ""], "", out)
    return out


def resolve_owner(cfg, real_path: str):
    """从实际路径 'route.rules[3].ip_cidr' 取出所在容器对象（用于 require_* 判断）。"""
    container = real_path.rsplit(".", 1)[0] if "." in real_path else ""
    if not container:
        return None
    # 去掉末尾的 [i]
    m = re.match(r"^(.*)\[\d+\]$", container)
    if m:
        container = m.group(1)
    node = cfg
    for part in [p for p in container.split(".") if p]:
        mm = re.match(r"^([A-Za-z0-9_\-]+)\[(\d+)\]$", part)
        if mm:
            k, i = mm.group(1), int(mm.group(2))
            if not isinstance(node, dict) or k not in node:
                return None
            lst = node[k]
            if not isinstance(lst, list) or i >= len(lst):
                return None
            node = lst[i]
        else:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
    return node


# ---------------------------------------------------------------- 结果收集


class Report:
    def __init__(self, name):
        self.name = name
        self.items = []  # (level, code, message)

    def error(self, code, msg):
        self.items.append(("ERROR", code, msg))

    def warn(self, code, msg):
        self.items.append(("WARN", code, msg))

    def info(self, code, msg):
        self.items.append(("INFO", code, msg))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    @property
    def warns(self):
        return [i for i in self.items if i[0] == "WARN"]

    def ok(self):
        return not self.errors


# ---------------------------------------------------------------- 主审查


def audit_matrix(cfg, rep: Report, matrix, target_version: str, platforms):
    """按 version-matrix.json 检查废弃/移除/平台差异。"""
    for e in matrix["entries"]:
        kind = e.get("kind")

        if kind in ("deprecated", "removed"):
            dep, rem = e.get("deprecated_in"), e.get("removed_in")
            if dep and not ver_ge(target_version, dep):
                continue  # 该版本还没废弃
            hits = []

            if e.get("path"):
                for real, node in find_paths(cfg, e["path"]):
                    owner = resolve_owner(cfg, real)
                    req = e.get("require_present")
                    if req and not (isinstance(owner, dict) and all(k in owner for k in req)):
                        continue
                    absent = e.get("require_absent")
                    if absent and isinstance(owner, dict) and any(k in owner for k in absent):
                        continue
                    hits.append(real)

            tc = e.get("type_check")
            if tc:
                where = cfg.get(tc["where"], [])
                if isinstance(where, list):
                    wanted = tc.get("equals")
                    if wanted:
                        wanted = [wanted]
                    wanted = wanted or tc.get("in", [])
                    for i, ob in enumerate(where):
                        if isinstance(ob, dict) and ob.get("type") in wanted:
                            hits.append(f"{tc['where']}[{i}](type={ob.get('type')})")

            if not hits:
                continue

            removed = rem and ver_ge(target_version, rem)
            level = "ERROR" if removed else "WARN"
            verb = "已移除" if removed else "已废弃"
            for h in hits:
                msg = f"[{e['id']}] {h} {verb}于 {rem if removed else dep}"
                if rem and not removed:
                    msg += f"（将于 {rem} 移除）"
                if e.get("replacement"):
                    msg += f" → 改用：{e['replacement']}"
                (rep.error if removed else rep.warn)(e["id"], msg)

        elif kind == "platform":
            if not platforms & set(e.get("platforms", [])):
                continue
            for real, _ in find_paths(cfg, e["path"]):
                rep.error(
                    e["id"],
                    f"[{e['id']}] {real} 在 {'/'.join(e.get('platforms', []))} 上不可用"
                    f" → {e.get('replacement', '')}",
                )

        elif kind == "semantic":
            if e.get("semantic") == "remote_rule_set_without_http_client":
                dep, rem = e.get("deprecated_in"), e.get("removed_in")
                if dep and not ver_ge(target_version, dep):
                    continue
                has_default = bool(cfg.get("route", {}).get("default_http_client"))
                for i, rs in enumerate(cfg.get("route", {}).get("rule_set", [])):
                    if rs.get("type") != "remote":
                        continue
                    if rs.get("http_client") or has_default:
                        continue
                    removed = rem and ver_ge(target_version, rem)
                    msg = (
                        f"[{e['id']}] route.rule_set[{i}] 为远程规则集但既无 http_client，"
                        f"也无 route.default_http_client"
                    )
                    if removed:
                        rep.error(e["id"], msg + f"，隐式默认 HTTP client 已于 {rem} 移除")
                    else:
                        rep.warn(e["id"], msg + f"（隐式行为将于 {rem} 移除）")


def audit_repo_rules(cfg, rep: Report):
    """本仓库自己的规范（与上游无关）。"""

    # 1) cache_file.path 必须是工作目录内的相对文件名
    exp = cfg.get("experimental", {})
    cf = exp.get("cache_file") or {}
    path = cf.get("path")
    if cf.get("enabled") and path:
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            rep.warn(
                "cache_path_abs",
                f"experimental.cache_file.path = {path!r} 是绝对路径；"
                "三平台工作目录不同，建议用 'cache.db'",
            )
        if ".." in Path(path).parts:
            rep.error(
                "cache_path_parent",
                f"experimental.cache_file.path = {path!r} 含 '..'；"
                "sing-box 不会自动创建父目录，父目录不存在会直接 FATAL 启动失败",
            )

    # 2) 远程规则集必须走允许的 CDN，且必须指定 http_client
    route = cfg.get("route", {})
    default_hc = route.get("default_http_client")
    has_http_clients = bool(cfg.get("http_clients"))
    remote_count = 0
    for i, rs in enumerate(route.get("rule_set", [])):
        if rs.get("type") != "remote":
            continue
        remote_count += 1
        url = rs.get("url", "")
        if not url.startswith(ALLOWED_RULESET_PREFIXES):
            rep.warn(
                "ruleset_url",
                f"route.rule_set[{i}] ({rs.get('tag')}) url 不在允许的 CDN 列表内：{url}",
            )
        if url.startswith("https://raw.githubusercontent.com") or url.startswith(
            "http://raw.githubusercontent.com"
        ):
            rep.error(
                "ruleset_url_raw",
                f"route.rule_set[{i}] 使用 raw.githubusercontent.com（国内不可达），必须换成 jsdelivr CDN",
            )
        if not rs.get("http_client") and not default_hc:
            if has_http_clients:
                rep.error(
                    "ruleset_http_client",
                    f"route.rule_set[{i}] ({rs.get('tag')}) 未指定 http_client，"
                    "且 route.default_http_client 为空",
                )
            else:
                rep.error(
                    "ruleset_http_client",
                    f"route.rule_set[{i}] ({rs.get('tag')}) 未指定 http_client，"
                    "顶层也没有 http_clients",
                )
        if rs.get("download_detour"):
            rep.error(
                "ruleset_download_detour",
                f"route.rule_set[{i}] 使用了已废弃的 download_detour，改用 http_client",
            )
        if rs.get("type") == "remote" and not rs.get("format") and not re.search(
            r"\.(srs|json)$", url
        ):
            rep.warn(
                "ruleset_format",
                f"route.rule_set[{i}] url 未以 .srs/.json 结尾且未写 format：{url}",
            )

    # 3) 出站 tag 唯一 + 引用完整性
    outs = cfg.get("outbounds", [])
    tags = [o.get("tag") for o in outs if isinstance(o, dict)]
    dup = {t for t in tags if tags.count(t) > 1}
    if dup:
        rep.error("dup_tag", f"outbounds 存在重复 tag：{sorted(dup)}")
    tagset = set(tags)
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        if o.get("type") in ("selector", "urltest"):
            refs = o.get("outbounds") or []
            missing = [r for r in refs if r not in tagset]
            if missing:
                rep.error(
                    "dangling_ref",
                    f"outbounds[{i}] ({o.get('tag')}) 引用了不存在的出站：{missing}"
                    "（sing-box check 不校验这个）",
                )
            if not refs:
                rep.error("empty_group", f"outbounds[{i}] ({o.get('tag')}) 的 outbounds 为空")
        if o.get("type") == "urltest" and not o.get("url"):
            rep.error("urltest_no_url", f"outbounds[{i}] ({o.get('tag')}) 是 urltest 但没有 url")

    final = route.get("final")
    if final and final not in tagset:
        rep.error("final_missing", f"route.final = {final!r} 不在出站列表中")

    # 3b) 引用完整性：route.rules[].outbound / rule_set / default_domain_resolver
    rs_tags = {r.get("tag") for r in route.get("rule_set", []) if isinstance(r, dict)}
    for i, rule in enumerate(route.get("rules", [])):
        if not isinstance(rule, dict):
            continue
        ob = rule.get("outbound")
        if ob and ob not in tagset:
            rep.error(
                "rule_outbound_missing",
                f"route.rules[{i}].outbound = {ob!r} 不在出站列表中（sing-box check 不校验这个）",
            )
        for r in rule.get("rule_set", []) if isinstance(rule.get("rule_set"), list) else []:
            if r not in rs_tags:
                rep.error(
                    "rule_ruleset_missing",
                    f"route.rules[{i}] 引用了未定义的规则集 {r!r}（sing-box check 不校验这个）",
                )
    ddr = route.get("default_domain_resolver")
    dns_tags = {s.get("tag") for s in cfg.get("dns", {}).get("servers", []) if isinstance(s, dict)}
    if isinstance(ddr, dict) and ddr.get("server") and ddr["server"] not in dns_tags:
        rep.error(
            "ddr_missing",
            f"route.default_domain_resolver.server = {ddr['server']!r} 不在 dns.servers 中",
        )

    # 3c) DNS 规则与服务引用完整性
    for i, rule in enumerate(cfg.get("dns", {}).get("rules", [])):
        if not isinstance(rule, dict):
            continue
        srv = rule.get("server")
        if srv and srv not in dns_tags:
            rep.error(
                "dns_rule_server_missing",
                f"dns.rules[{i}].server = {srv!r} 不在 dns.servers 中（sing-box check 不校验这个）",
            )
        for r in rule.get("rule_set", []) if isinstance(rule.get("rule_set"), list) else []:
            if r not in rs_tags:
                rep.error(
                    "dns_rule_ruleset_missing",
                    f"dns.rules[{i}] 引用了未定义的规则集 {r!r}（sing-box check 不校验这个）",
                )
    dns_final = cfg.get("dns", {}).get("final")
    if dns_final and dns_final not in dns_tags:
        rep.error("dns_final_missing", f"dns.final = {dns_final!r} 不在 dns.servers 中")

    # 4) AD 组只能放 block / direct
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        if o.get("tag") == "AD" and o.get("type") == "selector":
            bad = [r for r in (o.get("outbounds") or []) if r not in ("block", "direct")]
            if bad:
                rep.error(
                    "ad_group_polluted",
                    f"AD 分流组包含非 block/direct 出站：{bad}；广告拦截组不得放入代理节点",
                )

    # 5) http_clients 与 download_detour 冲突
    if cfg.get("http_clients"):
        for i, rs in enumerate(route.get("rule_set", [])):
            if rs.get("download_detour"):
                rep.error(
                    "http_client_conflict",
                    f"route.rule_set[{i}] 同时存在 http_clients 与 download_detour，"
                    "sing-box 会报 'http_client is conflict with deprecated download_detour field'",
                )


def audit_platform_caps(cfg, rep: Report, platforms):
    if {"android", "ios"} & platforms:
        for i, ib in enumerate(cfg.get("inbounds", [])):
            if ib.get("type") == "tun" and "strict_route" in ib:
                rep.error(
                    "platform_strict_route",
                    f"inbounds[{i}].strict_route 在 Android / Apple 客户端未实现，请删除",
                )
    if "android" in platforms:
        for i, ob in enumerate(cfg.get("outbounds", [])):
            if isinstance(ob, dict) and ob.get("domain_resolver") == "dns-local":
                rep.warn("android_resolver", f"outbounds[{i}] 依赖 local DNS，Android 上不总能工作")


def run_singbox_check(binary: str, cfg_path: Path, rep: Report):
    try:
        p = subprocess.run(
            [binary, "check", "-c", str(cfg_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        rep.warn("no_singbox", f"找不到可执行文件 {binary}，已跳过 sing-box check")
        return
    except subprocess.TimeoutExpired:
        rep.error("singbox_timeout", "sing-box check 超时")
        return
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        for line in out.strip().splitlines():
            rep.error("singbox_check", line.strip())
    else:
        rep.info("singbox_check", "sing-box check EXIT=0")


# ---------------------------------------------------------------- 入口


def infer_platform(name: str):
    n = name.lower()
    if "android" in n:
        return {"android"}
    if "ios" in n or "apple" in n:
        return {"ios"}
    if "desktop" in n or "windows" in n or "win" in n:
        return {"desktop"}
    return {"desktop", "android", "ios"}


def find_singbox(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("SINGBOX_BIN")
    if env:
        return env
    for cand in (
        ROOT / "bin" / ("sing-box.exe" if os.name == "nt" else "sing-box"),
        Path("C:/Users/Administrator/Desktop/_probe/sing-box-1.14.3-windows-amd64/sing-box.exe"),
    ):
        if cand.exists():
            return str(cand)
    return shutil.which("sing-box")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="sing-box 配置门禁")
    ap.add_argument("files", nargs="*", help="要审查的配置文件；留空则审查 profiles/ 下全部")
    ap.add_argument("--platform", help="desktop | android | ios，默认按文件名推断")
    ap.add_argument("--version", default=None, help="目标 sing-box 正式版号，如 1.14.3")
    ap.add_argument("--singbox", default=None, help="sing-box 可执行文件路径")
    ap.add_argument("--no-check", action="store_true", help="跳过 sing-box check")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if not MATRIX.exists():
        print(f"缺少 {MATRIX}", file=sys.stderr)
        return 2
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    version = args.version
    if not version:
        vt = ROOT / "singbox_version.txt"
        if vt.exists():
            version = vt.read_text(encoding="utf-8").strip().split()[0]
        else:
            version = "0.0.0"

    targets = []
    if args.files:
        targets = [Path(f) for f in args.files]
    else:
        targets = sorted(PROFILES.rglob("*.json"))

    if not targets:
        print("没有找到任何配置文件", file=sys.stderr)
        return 2

    binary = None if args.no_check else find_singbox(args.singbox)
    results = []
    failed = False

    for t in targets:
        if not t.exists():
            print(f"文件不存在：{t}", file=sys.stderr)
            failed = True
            continue
        platforms = {args.platform} if args.platform else infer_platform(t.name)
        rep = Report(str(t))
        try:
            cfg = json.loads(t.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ex:
            rep.error("json", f"JSON 解析失败：{ex}")
            results.append((rep, platforms))
            failed = True
            continue

        audit_matrix(cfg, rep, matrix, version, platforms)
        audit_platform_caps(cfg, rep, platforms)
        audit_repo_rules(cfg, rep)
        if binary:
            run_singbox_check(binary, t, rep)
        else:
            rep.info("no_singbox", "未指定 sing-box 可执行文件，已跳过 sing-box check")

        results.append((rep, platforms))
        if not rep.ok():
            failed = True

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "file": r.name,
                        "platforms": sorted(p),
                        "version": version,
                        "status": "PASS" if r.ok() else "FAIL",
                        "items": [
                            {"level": lv, "code": c, "message": m} for lv, c, m in r.items
                        ],
                    }
                    for r, p in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for r, p in results:
            status = "PASS" if r.ok() else "FAIL"
            print(f"\n=== {r.name}  [{status}]  目标版本 {version}  平台 {'/'.join(sorted(p))}")
            for lv, c, m in r.items:
                mark = {"ERROR": "[E]", "WARN": "[W]", "INFO": "[i]"}[lv]
                print(f"  {mark} {m}")
            if r.ok() and not r.warns:
                print("  · 无问题")
        total_err = sum(len(r.errors) for r, _ in results)
        total_warn = sum(len(r.warns) for r, _ in results)
        print(f"\n合计：{len(results)} 个文件，{total_err} ERROR，{total_warn} WARN")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
