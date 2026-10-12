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
PLACEHOLDER_DOMAINS = (".example.com", ".example.org", ".example.net", ".invalid", ".test", ".localhost")
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

            elif e.get("semantic") == "empty_direct_as_download_detour":
                # 这条不扫规则集，而是扫 http_clients / download_detour 指向的 direct 出站。
                # 静态部分与 audit_repo_rules 的 1c) 重叠，这里提供的是矩阵驱动的统一入口。
                outs = cfg.get("outbounds", [])
                by_tag = {
                    o.get("tag"): o
                    for o in outs
                    if isinstance(o, dict) and o.get("tag")
                }
                NON_EMPTY = (
                    "bind_interface", "inet4_bind_address", "inet6_bind_address",
                    "bind_address_no_port", "protect_path", "routing_mark", "reuse_addr",
                    "netns", "connect_timeout", "tcp_fast_open", "tcp_multi_path",
                    "disable_tcp_keep_alive", "tcp_keep_alive", "tcp_keep_alive_interval",
                    "udp_fragment", "domain_resolver", "network_strategy", "network_type",
                    "fallback_network_type", "fallback_delay", "detour",
                )

                def _empty(tag):
                    ob = by_tag.get(tag)
                    if not isinstance(ob, dict) or ob.get("type") != "direct":
                        return False
                    return not any(k in ob for k in NON_EMPTY)

                route = cfg.get("route", {})
                for i, hc in enumerate(cfg.get("http_clients") or []):
                    if isinstance(hc, dict) and _empty(hc.get("detour")):
                        rep.error(
                            e["id"],
                            f"[{e['id']}] http_clients[{i}].detour={hc.get('detour')!r} 是空 direct 出站"
                            f" → {e.get('replacement')}",
                        )
                dflt = route.get("default_http_client")
                if dflt and _empty(dflt):
                    rep.error(e["id"], f"[{e['id']}] route.default_http_client={dflt!r} 是空 direct 出站")
                for i, rs in enumerate(route.get("rule_set", [])):
                    dd = rs.get("download_detour")
                    if dd and _empty(dd):
                        rep.error(e["id"], f"[{e['id']}] route.rule_set[{i}].download_detour={dd!r} 是空 direct 出站")


def _audit_jinx(route, rep: Report):
    """Jinx 广告/放行规则集的成对性与顺序（本仓库强规范）。

    官方要求（https://github.com/RiverFlowsInUUU/Jinx#-规则顺序）：
        1 jinx-direct   → direct  白名单先放行
        2 jinx-ads      → AD      拦截
        3 awanue-ads    → AD      拦截（秋风判定不同，会拦掉 Jinx 白名单的 8 个域，必须排后面）
        4 geosite-cn    → direct  常规分流，必须排在拦截之后
    """
    rss = route.get("rule_set") or []
    rs_tags = {r.get("tag") for r in rss if isinstance(r, dict)}
    rules = route.get("rules") or []

    tags_present = [t for t in ("jinx-direct", "jinx-ads", "awanue-ads") if t in rs_tags]
    if not tags_present:
        return
    if len(tags_present) != 3:
        missing = [t for t in ("jinx-direct", "jinx-ads", "awanue-ads") if t not in rs_tags]
        rep.error(
            "jinx_incomplete",
            f"Jinx 规则集不完整：缺 {missing}。三者必须同时存在，"
            "jinx-ads / awanue-ads 必须跟 jinx-direct 放行集配套使用。",
        )

    # URL 必须指向 Jinx / AWAvenue 官方仓库
    expect = {
        "jinx-direct": "RiverFlowsInUUU/Jinx@",
        "jinx-ads": "RiverFlowsInUUU/Jinx@",
        "awanue-ads": "TG-Twilight/AWAvenue-Ads-Rule@",
    }
    for i, rs in enumerate(rss):
        tag = rs.get("tag")
        if tag in expect and expect[tag] not in (rs.get("url") or ""):
            rep.error(
                "jinx_url",
                f"route.rule_set[{i}] ({tag}) 的 url 未指向约定仓库（应包含 {expect[tag]}）：{rs.get('url')}",
            )
        if tag in expect and rs.get("format") != "source":
            rep.error(
                "jinx_format",
                f"route.rule_set[{i}] ({tag}) 必须是 format='source'（Jinx 发布的是 JSON 源格式，非 .srs）",
            )

    # 广告规则集不得出现在 dns.rules 的 rule_set 里（那是 DNS 分流，不是拦截）
    for i, r in enumerate((route.get("rules") or [])):
        if not isinstance(r, dict):
            continue
        for t in ("jinx-ads", "awanue-ads"):
            if t in (r.get("rule_set") or []):
                ob = r.get("outbound")
                if ob != "AD" and r.get("action") != "reject":
                    rep.error(
                        "jinx_ads_target",
                        f"route.rules[{i}] 把 {t} 指向了 {ob or r.get('action')!r}，"
                        "广告拦截集只能落到 AD 组或直接 reject",
                    )

    # 顺序：直接用 rule_set 在 route.rules 里的首次出现位置判定
    def first_pos(tag):
        for i, r in enumerate(rules):
            if isinstance(r, dict) and tag in (r.get("rule_set") or []):
                return i
        return None

    pos = {t: first_pos(t) for t in ("jinx-direct", "jinx-ads", "awanue-ads", "geosite-cn")}
    order = [t for t in ("jinx-direct", "jinx-ads", "awanue-ads", "geosite-cn") if pos[t] is not None]
    for a, b in zip(order, order[1:]):
        if pos[a] > pos[b]:
            rep.error(
                "jinx_order",
                f"规则顺序错误：{a}（第 {pos[a]} 条）必须排在 {b}（第 {pos[b]} 条）之前。"
                "国内广告域名多数也算大陆域名，geosite-cn 排前面会先放行、广告规则失效。",
            )


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

    # 1b) profiles/ 下必须是占位值——公开仓库永不存真实节点
    try:
        rel = Path(str(rep.name)).resolve().relative_to(ROOT)
    except ValueError:
        rel = Path(str(rep.name))
    if rel.parts and rel.parts[0] == "profiles":
        for i, ob in enumerate(cfg.get("outbounds", [])):
            if not isinstance(ob, dict):
                continue
            srv = ob.get("server")
            if not isinstance(srv, str) or not srv:
                continue
            if not srv.endswith(PLACEHOLDER_DOMAINS):
                rep.error(
                    "placeholder_server",
                    f"outbounds[{i}] ({ob.get('tag')}) 的 server={srv!r} 不是占位域名。"
                    "profiles/ 只允许 xxx.example.com 这类占位值；"
                    "含真实节点的配置请放仓库外的 local/ 目录，不要提交",
                )

    route = cfg.get("route", {})

    # 1c) http_client / download_detour 指向的 direct 出站不能是"空"的
    #     典型坑：direct 出站写成 {"type":"direct","tag":"direct"} 就是空洞。
    #     空洞下载规则集会 FATAL:"detour to an empty direct outbound makes no sense"，
    #     而且 **只发生在 sing-box run，check 完全静默**（protocol/direct/outbound.go 的
    #     isEmpty = DeepEqual(DialerOptions, 只含 UDPFragmentDefault:true)）。
    #     注意：domain_strategy / network_strategy 已废弃、被 schema:"omit"，填了也不算。
    #     真正能让 direct 非空的是 bind_interface / inet4_bind_address / routing_mark /
    #     domain_resolver / connect_timeout 等。
    outbounds = cfg.get("outbounds", [])
    by_tag = {o.get("tag"): o for o in outbounds if isinstance(o, dict) and o.get("tag")}
    NON_EMPTY = (
        "bind_interface", "inet4_bind_address", "inet6_bind_address", "bind_address_no_port",
        "protect_path", "routing_mark", "reuse_addr", "netns", "connect_timeout",
        "tcp_fast_open", "tcp_multi_path", "disable_tcp_keep_alive", "tcp_keep_alive",
        "tcp_keep_alive_interval", "udp_fragment", "domain_resolver", "network_strategy",
        "network_type", "fallback_network_type", "fallback_delay", "detour",
    )

    def _empty_direct(tag):
        """返回 True 表示该出站是"空洞 direct"（不能作为下载 detour）。"""
        ob = by_tag.get(tag)
        if not isinstance(ob, dict) or ob.get("type") != "direct":
            return False
        return not any(k in ob for k in NON_EMPTY)

    hc_entries = cfg.get("http_clients") or []
    DL_TAG = "direct-download"
    for i, hc in enumerate(hc_entries):
        if not isinstance(hc, dict):
            continue
        dt = hc.get("detour")
        if not dt:
            continue
        if dt not in by_tag:
            rep.error(
                "dangling_download_detour",
                f"http_clients[{i}] ({hc.get('tag')}) 的 detour={dt!r} 指向不存在的出站",
            )
            continue
        if _empty_direct(dt):
            rep.error(
                "download_detour_empty_direct",
                f"http_clients[{i}] ({hc.get('tag')}) 的 detour={dt!r} 是一个空 direct 出站；"
                "规则集下载会 FATAL: 'detour to an empty direct outbound makes no sense'。"
                f"仓库约定：下载必须走 tag 为 {DL_TAG!r} 的专用 direct 出站，"
                "它至少带 domain_resolver（或 bind_interface / inet4_bind_address 等）",
            )
        elif dt != DL_TAG:
            rep.warn(
                "download_uses_main_direct",
                f"http_clients[{i}] ({hc.get('tag')}) 的 detour={dt!r} 不是专用的 {DL_TAG!r}；"
                "当前非空、能跑，但主 direct 一旦被改成裸的 {'type':'direct','tag':'direct'} 就会立刻 FATAL。"
                f"仓库约定统一用 {DL_TAG!r}",
            )
    if by_tag and DL_TAG not in by_tag and any(
        isinstance(hc, dict) and hc.get("detour") for hc in hc_entries
    ):
        rep.warn(
            "no_download_direct",
            f"仓库里定义了 http_clients 但没有 {DL_TAG!r} 出站；"
            "按约定每个 profile 都应该有它（带 domain_resolver），供规则集下载专用",
        )
    default_hc_tag = route.get("default_http_client")
    if default_hc_tag and _empty_direct(default_hc_tag):
        rep.error(
            "download_detour_empty_direct",
            f"route.default_http_client={default_hc_tag!r} 是一个空 direct 出站，同样会 FATAL；"
            "修法与 http_clients 相同",
        )
    for i, rs in enumerate(route.get("rule_set", [])):
        dd = rs.get("download_detour")
        if dd and _empty_direct(dd):
            rep.error(
                "download_detour_empty_direct",
                f"route.rule_set[{i}] ({rs.get('tag')}) 的 download_detour={dd!r} 是空 direct 出站，会 FATAL",
            )

    # 2) 远程规则集必须走允许的 CDN，且必须指定 http_client
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

    # 2b) Jinx 广告/放行规则集：必须成对存在，且顺序必须正确
    #     顺序错了等于没加：geosite-cn 排到拦截之前会先命中放行，广告规则再无机会执行。
    _audit_jinx(route, rep)

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


GROUP_TYPES = ("selector", "urltest", "block", "dns")


def audit_loopback_guard(cfg, rep: Report):
    """tun 场景必须防止出站流量回灌 tun，否则表现为「能启动但没网」。

    官方 docs/configuration/inbound/tun.md：To avoid traffic loopback, set
    `route.auto_detect_interface` or `route.default_interface` or `outbound.bind_interface`。

    为什么必须卡这一条（源码级）：common/dialer/default.go 的 NewDefault 里，只有
    `networkManager.AutoDetectInterface() && !disableDefaultBind` 成立时才会给
    dialer.Control / listener.Control 挂上 ProtectFunc()（Android = VpnService.protect）；
    没写这个字段 ⇒ 一个 Control 都不挂 ⇒ 出站 socket 被 VpnService 自己抓回隧道 ⇒
    回环：节点测速全部失败（无延迟）、只有上传没下载、连接数暴涨、内存飙升。
    在 Android 上 route.default_interface / outbound.bind_interface 都不可用
    （VpnService 托管环境），唯一可行的是 route.auto_detect_interface: true。
    """
    inbounds = cfg.get("inbounds") or []
    has_tun = any(isinstance(ib, dict) and ib.get("type") == "tun" for ib in inbounds)
    if not has_tun:
        return
    route = cfg.get("route") or {}
    if route.get("auto_detect_interface") is True:
        return
    if route.get("default_interface"):
        return
    outbounds = cfg.get("outbounds") or []
    dialing = [
        (i, ob)
        for i, ob in enumerate(outbounds)
        if isinstance(ob, dict) and ob.get("type") not in GROUP_TYPES
    ]
    if dialing and all(ob.get("bind_interface") for _, ob in dialing):
        return
    rep.error(
        "tun_without_auto_detect_interface",
        "有 tun 入站但 route.auto_detect_interface / route.default_interface / "
        "outbounds[].bind_interface 三者都没有：出站 socket 不会被 protect 或绑定网卡，"
        "流量会回灌 tun（症状：能启动但没网、节点全无延迟、只有上传没下载、内存暴涨）。"
        "请加 route.auto_detect_interface: true",
    )


def audit_template(rep: Report):
    """校 templates/groups.json（固定分流组骨架）。

    这份文件是每个 profile 的出站骨架，它自身写错了，生成的配置就会集体写错。
    重点：Proxy 必须是 urltest（m01246 起不再有单独的 Auto 组）。
    """
    path = ROOT / "templates" / "groups.json"
    if not path.exists():
        rep.error("template_missing", "templates/groups.json 不存在")
        return
    try:
        tpl = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        rep.error("template_json", f"templates/groups.json 解析失败：{ex}")
        return
    outbounds = tpl.get("outbounds") or []
    by_tag = {ob.get("tag"): ob for ob in outbounds if isinstance(ob, dict)}
    required = ("Proxy", "AI", "AD", "direct", "block", "direct-download")
    for tag in required:
        if tag not in by_tag:
            rep.error("template_group_missing", f"templates/groups.json 缺固定组 `{tag}`")
    if "Auto" in by_tag:
        rep.error(
            "template_legacy_auto",
            "templates/groups.json 里仍有 `Auto` 组：Proxy 本身就是 urltest，不再需要单独的 Auto",
        )
    proxy = by_tag.get("Proxy")
    if proxy and proxy.get("type") != "urltest":
        rep.error(
            "template_proxy_not_urltest",
            f"Proxy 必须是 urltest（当前 {proxy.get('type')}）——它是全局默认出口与兜底",
        )
    if proxy and not proxy.get("url"):
        rep.error("template_proxy_no_url", "Proxy (urltest) 必须有 url，否则节点测速无意义")
    ai = by_tag.get("AI")
    if ai and ai.get("default") != "Proxy":
        rep.warn("template_ai_default", "AI 的 default 建议指向 Proxy（跟随即全局优选）")
    ad = by_tag.get("AD")
    if ad and set(ad.get("outbounds") or []) - {"block", "direct"}:
        rep.error("template_ad_polluted", "AD 只允许 block / direct")


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
    if "android" in platforms:
        route = cfg.get("route") or {}
        if route.get("override_android_vpn") and not route.get("auto_detect_interface"):
            rep.warn(
                "android_override_vpn_no_adi",
                "route.override_android_vpn 需要 route.auto_detect_interface 才生效，当前未开",
            )


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


def run_singbox_run(binary: str, cfg_path: Path, rep: Report, seconds: int = 15):
    """真正跑一次 sing-box run 来抓 check 看不见的启动期 FATAL。

    为什么需要：`sing-box check` **只反序列化，不做任何初始化**，所以下面这些错
    它一律 exit=0：
      · 空的 direct 出站（'detour to an empty direct outbound makes no sense'）
      · 初始化规则集 / DNS 服务器 / 出站时才会暴露的引用与资源问题
    代价：会真的建立网络连接（拿规则集、连 DNS），所以默认不带 --run，由调用方按需开启。
    成功特征：进程活到超时被我仨杀。【致命错】只看是否出现 FATAL 字样。
    不能直接拿 run去验证 tun 入站（Windows 上会走 netstack 假接口），所以要先把 tun 替成 mixed。
    """
    import tempfile

    try:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    except Exception as ex:
        rep.warn("run_skipped", f"无法读取配置做 run 验证：{ex}")
        return

    # tun 入站换成 mixed，避免在 Windows 上建假网卡；没有 tun 就不动
    patched = 0
    free_port = 0
    for i, ib in enumerate(cfg.get("inbounds", [])):
        if isinstance(ib, dict) and ib.get("type") == "tun":
            free_port = _free_port()
            cfg["inbounds"][i] = {
                "type": "mixed",
                "tag": ib.get("tag", "tun-in"),
                "listen": "127.0.0.1",
                "listen_port": free_port,
            }
            patched += 1

    # cache_file 换个临时路径，免得污染工作目录（并避开 fi.le 锁冲突）
    with tempfile.TemporaryDirectory(prefix="sb-run-") as td:
        exp = cfg.setdefault("experimental", {})
        cf = exp.get("cache_file")
        if isinstance(cf, dict) and cf.get("enabled"):
            cf = dict(cf)
            cf["path"] = str(Path(td) / "cache.db")
            exp["cache_file"] = cf
        tmp_cfg = Path(td) / "run-check.json"
        tmp_cfg.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            p = subprocess.run(
                [binary, "run", "-c", str(tmp_cfg)],
                capture_output=True,
                text=True,
                timeout=seconds,
                cwd=td,
            )
            out = (p.stdout or "") + (p.stderr or "")
            timed_out = False
            if p.returncode == 0:
                out += "\n[未超时正常退出，可能主进程直接退了]"
        except subprocess.TimeoutExpired as ex:
            timed_out = True
            out = ((ex.stdout or b"").decode("utf-8", "replace") if isinstance(ex.stdout, bytes) else (ex.stdout or ""))
            out += (ex.stderr or b"").decode("utf-8", "replace") if isinstance(ex.stderr, bytes) else (ex.stderr or "")
        except FileNotFoundError:
            rep.warn("no_singbox", f"找不到可执行文件 {binary}，已跳过 sing-box run 验证")
            return

    fatal = [ln.strip() for ln in out.splitlines() if "FATAL" in ln]
    if fatal:
        for ln in fatal[:6]:
            rep.error("singbox_run", re.sub(r"\x1b\[[0-9;]*m", "", ln))
    else:
        if timed_out:
            rep.info("singbox_run", f"sing-box run 存活 {seconds}s 未报 FATAL（已主动终止）")
        else:
            rep.info("singbox_run", "sing-box run 未报 FATAL")
        if patched:
            rep.info("singbox_run_tun", f"run 验证时把 {patched} 个 tun 入站临时换成 mixed（{free_port}）")


def _free_port():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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
    ap.add_argument(
        "--run",
        action="store_true",
        help="额外真跑一次 sing-box run，抓 check 看不见的启动期 FATAL（如空 direct 出站）。"
        "会真的发起网络连接，默认关闭",
    )
    ap.add_argument("--run-seconds", type=int, default=15, help="--run 时跑多少秒，默认 15")
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
    failed = False
    if args.files:
        targets = [Path(f) for f in args.files]
    else:
        targets = sorted(PROFILES.rglob("*.json"))
        template_rep = Report("templates/groups.json")
        audit_template(template_rep)
        if template_rep.items:
            for lv, code, msg in template_rep.items:
                print(f"[{lv[0]}] templates/groups.json: {msg}")
        if not template_rep.ok():
            failed = True
    
    if not targets:
        print("没有找到任何配置文件", file=sys.stderr)
        return 2

    binary = None if args.no_check else find_singbox(args.singbox)
    results = []

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
        audit_loopback_guard(cfg, rep)
        if binary:
            run_singbox_check(binary, t, rep)
            if args.run:
                run_singbox_run(binary, t, rep, args.run_seconds)
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
