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
from ipaddress import ip_address, ip_network
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

# direct 出站里任何一个字段出现，就不算「空 direct」（不能作为规则集下载 detour）。
# 详见 docs/LESSONS.md L1：空 direct 会 FATAL "detour to an empty direct outbound makes no sense"。
# 注意 domain_strategy / network_strategy 已被 schema:"omit"，填了也不算数，不要加回来。
DIRECT_NON_EMPTY_KEYS = (
    "bind_interface", "inet4_bind_address", "inet6_bind_address",
    "bind_address_no_port", "protect_path", "routing_mark", "reuse_addr",
    "netns", "connect_timeout", "tcp_fast_open", "tcp_multi_path",
    "disable_tcp_keep_alive", "tcp_keep_alive", "tcp_keep_alive_interval",
    "udp_fragment", "domain_resolver", "network_strategy", "network_type",
    "fallback_network_type", "fallback_delay", "detour",
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

        elif kind == "new":
            # 新功能采纳：expect=present 要求配置里必须有，expect=absent 要求必须没有。
            # 注意与 deprecated 反向：这里检查的是「采纳后该字段在不在」，不是「有没有踩废弃」。
            since = e.get("since")
            if since and not ver_ge(target_version, since):
                continue  # 该版本还没这个功能
            has_path = bool(e.get("path"))
            expect = e.get("expect")
            if not has_path or expect not in ("present", "absent"):
                continue  # 无字段可检测（纯版本更新类）或数据不完整，由 audit_new_features 兜
            found = bool(find_paths(cfg, e["path"]))
            if expect == "absent" and found:
                rep.error(
                    e["id"],
                    f"[{e['id']}] 配置里出现了 {e['path']}，但本仓库对该新功能的决策是"
                    f"「不启用」（{e.get('title', '')}）—— 要么删掉字段，要么把矩阵里的 adopt 改掉并写明理由",
                )
            elif expect == "present" and not found:
                rep.error(
                    e["id"],
                    f"[{e['id']}] 矩阵要求配置里必须有 {e['path']}（adopt={e.get('adopt')}），但没找到——"
                    f"{e.get('title', '')}",
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

                def _empty(tag):
                    ob = by_tag.get(tag)
                    if not isinstance(ob, dict) or ob.get("type") != "direct":
                        return False
                    return not any(k in ob for k in DIRECT_NON_EMPTY_KEYS)

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

    def _empty_direct(tag):
        """返回 True 表示该出站是"空洞 direct"（不能作为下载 detour）。"""
        ob = by_tag.get(tag)
        if not isinstance(ob, dict) or ob.get("type") != "direct":
            return False
        return not any(k in ob for k in DIRECT_NON_EMPTY_KEYS)

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
                if o.get("tag") in NO_NESTING_GROUPS:
                    rep.warn(
                        "empty_group_skeleton",
                        f"outbounds[{i}] ({o.get('tag')}) 的 outbounds 为空：骨架模板允许，"
                        "真正生成的配置必须把节点加进去",
                    )
                else:
                    rep.error("empty_group", f"outbounds[{i}] ({o.get('tag')}) 的 outbounds 为空")
        if o.get("type") == "urltest" and not o.get("url"):
            rep.error("urltest_no_url", f"outbounds[{i}] ({o.get('tag')}) 是 urltest 但没有 url")

    # 3a) 组的类型与嵌套：Proxy / AI 必须是 urltest，AD 必须是 selector；组的 outbounds 里只放真实节点
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        want = GROUP_TYPES_REQUIRED.get(o.get("tag"))
        if want and o.get("type") != want:
            rep.error(
                "group_wrong_type",
                f"outbounds[{i}] ({o.get('tag')}) 必须是 {want}（当前 {o.get('type')}）："
                "Proxy 与 AI 是两个独立优选组、各自 urltest；AD 是 selector",
            )
        if o.get("tag") not in NO_NESTING_GROUPS:
            continue
        nested = [r for r in (o.get("outbounds") or []) if r in GROUP_TAGS]
        if nested:
            rep.error(
                "group_nesting",
                f"outbounds[{i}] ({o.get('tag')}) 引用了其它分流组 {nested}："
                "组的 outbounds 里只允许放真实节点，嵌套 urltest 会串联两次测速"
                "（m02132 用户要求 AI 直接是 urltest + 台湾节点，不要 Proxy 作子节点）",
            )

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

    # 4) AD 组只能放 block / direct；默认值必须是 block，否则整个去广告链路静默失效
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        if o.get("tag") != "AD":
            continue
        if o.get("type") == "selector":
            bad = [r for r in (o.get("outbounds") or []) if r not in ("block", "direct")]
            if bad:
                rep.error(
                    "ad_group_polluted",
                    f"AD 分流组包含非 block/direct 出站：{bad}；广告拦截组不得放入代理节点",
                )
            # 详见 docs/LESSONS.md L17：default 被改成 direct（或写了个不存在的 tag）时，
            # 规则照样命中 AD，但连接被放行 —— 没有任何报错，广告静默漏过。
            if o.get("default") != "block":
                rep.error(
                    "ad_group_default_not_block",
                    f"AD 分流组的 default = {o.get('default')!r}，必须是 \"block\"："
                    "广告规则命中 AD 后若默认出站不是 block，广告会静默直连放行",
                )

    # 4b) 用 block 出站拦广告时，日志级别会被 ERROR 刷屏（见 docs/LESSONS.md L16）
    has_block = any(
        isinstance(o, dict) and o.get("type") == "block" for o in outs
    )
    log_opts = cfg.get("log")
    if has_block and isinstance(log_opts, dict) and not log_opts.get("disabled"):
        level = str(log_opts.get("level", "info")).lower()
        if level not in ("fatal", "panic"):
            rep.info(
                "ads_block_log_noise",
                f"log.level = {level!r}（未被 disabled）：block 出站每拦一次连接会写一条 INFO "
                "+ 一条 ERROR（... using outbound/selector[AD]: operation not permitted）。"
                "这是拦截成功的正常现象、不是故障；嫌吵可把 log.level 设为 \"panic\" "
                "或 log.disabled=true（详见 docs/LESSONS.md L16）",
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

    # 6) IPv4-only 必须端到端：只写 dns.strategy 掐不死代理侧（见 docs/LESSONS.md L17）
    #    插件机制：route/route.go 的 actionResolve 只写 metadata.DestinationAddresses，
    #    route/conn.go:103-104 一旦 DestinationAddresses 非空就走 DialSerialNetwork，
    #    目标被换成 IP 字面量 → 代理只收到 IPv4。没有这一步时，域名会原样交给服务端解析，
    #    服务端可能给出 IPv6（ip.net.coffee 首页汇总就会出现 IPv6 出口 IP）。
    resolve_rules = [
        (i, r)
        for i, r in enumerate(route.get("rules", []))
        if isinstance(r, dict) and r.get("action") == "resolve"
    ]
    for i, r in resolve_rules:
        if r.get("strategy") != "ipv4_only":
            rep.error(
                "resolve_not_ipv4_only",
                f"route.rules[{i}] 的 resolve.strategy = {r.get('strategy')!r}，本项目要求 "
                '"ipv4_only"：resolve 会把解析结果写成出站拨号目标，用 prefer_ipv4 仍可能落到 IPv6；'
                "不写 strategy 则继承 dns.strategy（改一处就会静默退化）",
            )
    if cfg.get("dns", {}).get("strategy") == "ipv4_only" and not resolve_rules:
        rep.warn(
            "resolve_missing_ipv4_only",
            "dns.strategy = ipv4_only 但没有 route.rules 的 `{\"action\": \"resolve\", \"strategy\": "
            "\"ipv4_only\"}`：本地 DNS 只掐了 AAAA，目标域名仍会被原样交给代理服务端解析，"
            "服务端可能用 IPv6 出口（详见 docs/LESSONS.md L17）",
        )

    # 6b) resolve 必须在第一个 route/reject/hijack-dns/bypass 之前（见 docs/LESSONS.md L18）
    #     源码 route/route.go:670-705：只有 route / reject / hijack-dns / bypass 才 `break match`，
    #     resolve 是「继续匹配」的中间动作。所以放在末尾的 resolve **只会作用于前面所有规则都没命中的流量**
    #     （即最终落到 final 的那部分）。任何走 route(AI)/route(AD)/route(direct) 的连接
    #     都带着域名发给代理服务端，服务端可以自己选 IPv6 —— 这正是「配了 ipv4_only 却仍看到 IPv6 出口」的原因。
    if resolve_rules:
        rules = route.get("rules", [])
        # hijack-dns 本身也是终止动作，但它必须在 resolve 之前（DNS 流量先被劫持，无需解析）
        blocking_actions = ("route", "reject", "bypass")
        first_blocking = next(
            (
                i
                for i, r in enumerate(rules)
                if isinstance(r, dict)
                and (
                    str(r.get("action", "")) in blocking_actions
                    # 只写条件的规则默认动作就是 route（route/rule/rule_default.go），也算终止动作
                    or "action" not in r
                )
            ),
            None,
        )
        first_resolve = resolve_rules[0][0]
        if first_blocking is not None and first_resolve > first_blocking:
            rep.error(
                "resolve_not_first",
                f"route.rules[{first_resolve}] 是 resolve，但它排在 route.rules[{first_blocking}] "
                f"（{rules[first_blocking].get('action') or '条件规则默认 route'}）之后："
                "首个 route/reject/hijack-dns/bypass 命中即 break match，后面的 resolve 永远不会执行，"
                "命中 AI/AD/direct 的域名仍会被原样交给代理服务端解析（服务端可用 IPv6 出口）。"
                "resolve 必须紧跟 hijack-dns，排在所有 route/reject 之前（详见 docs/LESSONS.md L18）",
            )


GROUP_TYPES = ("selector", "urltest", "block", "dns")
# 分流组（骨架 tag 固定），任何一个配置文件都不得出现同名 tag 的重复语义
GROUP_TAGS = ("Proxy", "AI", "AD")
# 组的 outbounds 里只允许出现真实节点，不允许嵌套组（urltest 套 urltest 会串联两次测速）
NO_NESTING_GROUPS = GROUP_TAGS
# 固定组的类型不允许被改（m02132：AI 与 Proxy 一样是 urltest，不再是指向 Proxy 的 selector）
GROUP_TYPES_REQUIRED = {"Proxy": "urltest", "AI": "urltest", "AD": "selector"}


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
    if ai and ai.get("type") != "urltest":
        rep.error(
            "template_ai_not_urltest",
            f"AI 必须是 urltest（当前 {ai.get('type')}）——它与 Proxy 是两个独立的优选组",
        )
    if ai and not ai.get("url"):
        rep.error("template_ai_no_url", "AI (urltest) 必须有 url，否则节点测速无意义")
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


# ---------------------------------------------------------------- 新功能采纳

# 采纳决策的合法取值：yes=启用 / no=明确不启用 / must=必须跟随（旧写法被取代）
ADOPT_VALUES = ("yes", "no", "must")
# 有字段可检测的 kind=new 条目，expect 必须显式写；否则门禁无从判断
NEW_WITH_PATH_EXPECT = ("present", "absent")
CHANGELOG = ROOT / "docs" / "upstream-changelog.md"
# changelog 里这些行是噪音，不参与「新功能是否被矩阵覆盖」的比对
_CHANGELOG_NOISE = re.compile(
    r"^(fixes and improvements"       # 纯修补段
    r"|important changes since"        # 导言段
    r"|\*\*\d+\*\*\s*:|\*\*\d+\*\*\s*$"  # 脚注定义体（**1**: 这种行，尚未 lstrip）
    r"|\d+\*\*\s*:"                    # 脚注定义体（lstrip('*') 之后只剩 `1**:`）
    r"|https?://"                      # 裸链接行
    r"|see\s+\[)",                     # “See [XXX](...)” 这类脚注指引
    re.I,
)


def _changelog_features(floor_version: str):
    """从 docs/upstream-changelog.md 抽出「>= floor_version」的新功能条目。

    **故意包含 alpha / beta / rc 段**：这正是提前发现即将到来的新功能的唯一途径
    （正式版发布时这些条目会再出现一次，故按归一化文本去重）。
    版本号归一化：`1.15.0-alpha.7` → `1.15.0`。

    栏掉纯修补段（`Fixes and improvements`）与空行，返回去重后的 [(版本, 条目原文), ...]。
    """
    if not CHANGELOG.exists():
        return []
    text = CHANGELOG.read_text(encoding="utf-8")
    seen = set()
    out = []
    for m in re.finditer(r"^####\s+([0-9][0-9.\-a-zA-Z]*)\s*$", text, re.M):
        raw = m.group(1)
        base = re.match(r"(\d+\.\d+\.\d+)", raw)
        if not base:
            continue
        ver = base.group(1)
        if not ver_ge(ver, floor_version):
            continue
        end = text.find("\n####", m.end())
        body = text[m.end(): end if end != -1 else len(text)]
        for line in body.splitlines():
            s = line.strip()
            if not s.startswith("*"):
                continue
            feat = s.lstrip("*").strip()
            feat = re.sub(r"\s*\*\*\d+\*\*\s*$", "", feat).strip()  # 去掉脚注标记 **1**
            if not feat or _CHANGELOG_NOISE.match(feat):
                continue
            key = feat.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((ver, feat))
    return out


def audit_new_features(rep: Report, matrix, target_version: str):
    """新功能采纳台账校验（仓库级，每份配置都跑一次之外单独跑一次）。

    三道检查：
      1. 数据完整性：kind=new 必须有合法 adopt + 非空 reason；有 path 的还必须有 expect。
      2. 未卜先知：decide_by 已过期而 adopt 仍缺失/非法 → ERROR（不能靠「忘了」来默认不启用）。
      3. changelog 覆盖：上游 changelog 里 >= 锁定版本 的正式版新功能条目，必须被某条 kind=new
         的 keywords 覆盖；否则 ERROR —— 防止「上游加了新功能，仓库浑然不知」。
    """
    news = [e for e in matrix.get("entries", []) if e.get("kind") == "new"]
    if not news:
        rep.error(
            "new_feature_without_adoption",
            "version-matrix.json 里没有任何 kind=\"new\" 条目 —— 新功能采纳机制等于不存在"
            "（上游加了什么功能，仓库不会知道）",
        )
        return

    for e in news:
        eid = e.get("id", "?")
        adopt = e.get("adopt")
        # 1) adopt 必填且合法
        if adopt not in ADOPT_VALUES:
            rep.error(
                "new_feature_without_adoption",
                f"[{eid}] kind=new 但 adopt={adopt!r} 不合法（应为 {'/'.join(ADOPT_VALUES)} 之一）："
                f"{e.get('title', '')} —— 新功能必须写下「启用还是不启用」的明确决定，"
                f"不允许留空或写「待定」",
            )
        # 2) reason 必填
        if not str(e.get("reason") or "").strip():
            rep.error(
                "new_feature_without_adoption",
                f"[{eid}] kind=new 但没写 reason —— 决策没有理由，下一个人无法复核",
            )
        # 3) 有 path 的必须写 expect，且必须与 adopt 自洽
        if e.get("path"):
            if e.get("expect") not in NEW_WITH_PATH_EXPECT:
                rep.error(
                    "new_feature_expect_invalid",
                    f"[{eid}] 有 path 但 expect={e.get('expect')!r} 不合法"
                    f"（应为 {'/'.join(NEW_WITH_PATH_EXPECT)}）",
                )
            elif adopt == "no" and e.get("expect") != "absent":
                rep.error(
                    "new_feature_expect_invalid",
                    f"[{eid}] adopt=no（不启用）却写 expect={e['expect']!r} —— "
                    f"不启用就该要求配置里没有这个字段，应写 \"absent\"",
                )
        # 4) decide_by 过期仍未决策 → 不能靠「忘了」蒙混过关
        db = e.get("decide_by")
        if db and not ver_ge(db, target_version):
            rep.error(
                "new_feature_decision_overdue",
                f"[{eid}] 决策截止版本 {db} 已到（当前锁定 {target_version}）仍未落地："
                f"{e.get('title', '')} —— 请补上 adopt/reason，或把 decide_by 往后挪并说明原因",
            )

    # 5) changelog 覆盖比对
    feats = _changelog_features(target_version)
    if not feats:
        rep.info(
            "new_feature_covered",
            f"上游 changelog 中 >= {target_version} 没有可识别的新功能条目（可能全部是修补段），无需比对",
        )
        return
    uncovered = []
    for ver, feat in feats:
        low = feat.lower()
        hit = any(k and k.lower() in low for e in news for k in (e.get("keywords") or []))
        if not hit:
            uncovered.append((ver, feat))
    if uncovered:
        rep.error(
            "new_feature_uncovered",
            f"上游 changelog 里 >= {target_version} 的正式版新功能有 {len(uncovered)} 条没被矩阵覆盖"
            f"（keywords 比对）：" + "；".join(f"{v} {f}" for v, f in uncovered[:6])
            + (" …" if len(uncovered) > 6 else ""),
        )
    else:
        rep.info(
            "new_feature_covered",
            f"上游 changelog 中 >= {target_version} 的正式版新功能共 {len(feats)} 条，"
            f"全部被 {len(news)} 条 kind=new 条目的 keywords 覆盖",
        )


# ---------------------------------------------------------------- 教训台账校验

# 框架性/非配置类 code，不要求有 LESSONS 条目
LESSON_FRAMEWORK_CODES = {
    "json",
    "no_singbox",
    "skip_check_template",
    "run_skipped",
    "singbox_check",
    "singbox_run",
    "singbox_run_tun",
    "singbox_timeout",
}
LESSONS = ROOT / "docs" / "LESSONS.md"
LESSONS_GATE_RE = re.compile(r"`([a-z][a-z0-9_]{2,})`")
AUDIT_SRC = Path(__file__).resolve()


def _audit_gate_codes():
    """扫出 tools/audit.py 里所有真实的门禁 code（含 INFO 级，它们也是可追溯的通知）。"""
    src = AUDIT_SRC.read_text(encoding="utf-8")
    return set(re.findall(r'rep\.(?:error|warn|info)\(\s*"([a-z0-9_]+)"', src))


def _lessons_gate_codes():
    """扫出 docs/LESSONS.md 每条教训声明的门禁 code。"""
    if not LESSONS.exists():
        return None
    lines = LESSONS.read_text(encoding="utf-8").splitlines()
    declared = set()
    for line in lines:
        if line.startswith("**门禁**："):
            body = line.split("：", 1)[1]
            # 「无」= 明确声明这条教训没有门禁对应
            if body.strip().startswith("无"):
                continue
            for code in LESSONS_GATE_RE.findall(body):
                declared.add(code)
    return declared


def audit_lessons(rep: Report):
    """校验 docs/LESSONS.md 与 tools/audit.py 的门禁双向可追溯。

    方向一：LESSONS 里声明的门禁 code 必须在 audit.py 源码里真实存在。
    方向二：audit.py 里每个非框架 code 必须在某个 docs/*.md 里出现过。

    为什么需要：文档写了门禁但代码没实现 = 假装有防护；代码加了门禁但没记录教训 = 下次被误删。
    """
    if not LESSONS.exists():
        rep.error("lessons_missing", "docs/LESSONS.md 不存在：没有教训台账，历史踩过的坑会重犯")
        return
    real = _audit_gate_codes()
    declared = _lessons_gate_codes() or set()
    for code in sorted(declared - real):
        rep.error(
            "lessons_missing_gate",
            f"docs/LESSONS.md 声明了门禁 `{code}`，但 tools/audit.py 里没有实现——假装有防护",
        )
    docs_text = ""
    for p in sorted((ROOT / "docs").glob("*.md")):
        try:
            docs_text += p.read_text(encoding="utf-8")
        except Exception:
            pass
    for p in (ROOT / "AGENTS.md", ROOT / "README.md"):
        if p.exists():
            try:
                docs_text += p.read_text(encoding="utf-8")
            except Exception:
                pass
    for code in sorted(real - LESSON_FRAMEWORK_CODES):
        if code not in docs_text:
            rep.error(
                "gate_without_lesson",
                f"tools/audit.py 的门禁 `{code}` 在 docs/*.md、AGENTS.md、README.md 里都没有出处——"
                f"请在 docs/LESSONS.md 补一条教训条目说明它拦的是什么事故",
            )


# ---------------------------------------------------- 决策记录双向校验

DECISIONS = ROOT / "docs" / "DECISIONS.md"
DECISION_HEAD_RE = re.compile(r"^##\s+(D\d+)\s+(.+)$", re.M)


def audit_decisions(rep: Report, matrix, target_version: str):
    """校验 docs/DECISIONS.md 与矩阵里 kind=new 条目双向对得上。

    为什么需要：矩阵只存一行 `reason`，写不下背景 / 备选方案 / 代价权衡。
    升级后回头看「当初为什么不用 MASQUE」时答案在 DECISIONS.md。
    两边都写、都交叉检查，才不会出现「矩阵有决定、但没人知道为什么」。

    方向一：每条 kind=new 必须在 DECISIONS.md 有一个 D<n> 条目引用它的 id；
    方向二：DECISIONS.md 里引用的矩阵 id 必须真实存在（防止改矩阵后文档沦为谎言）。
    """
    if not DECISIONS.exists():
        rep.error(
            "decisions_missing",
            "docs/DECISIONS.md 不存在：新功能只写了结论没有理由，下一个人无法复核",
        )
        return
    text = DECISIONS.read_text(encoding="utf-8")
    ids_in_matrix = {e.get("id") for e in matrix.get("entries", [])}
    news = [e for e in matrix.get("entries", []) if e.get("kind") == "new"]

    # 抽出每个 D<n> 小节的正文（用于查它是否引用了某个矩阵 id）
    heads = list(DECISION_HEAD_RE.finditer(text))
    sections = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        sections.append((m.group(1), text[m.start():end]))

    # 方向一：矩阵条目必须被某个 D 小节引用
    for e in news:
        eid = e.get("id")
        if not any(eid in body for _, body in sections):
            rep.error(
                "decision_without_record",
                f"矩阵条目 [{eid}] 在 docs/DECISIONS.md 里没有对应的 D 条目 —— "
                f"请补一段写清「为什么这么决策 / 备选方案 / 前提风险」（{e.get('title', '')}）",
            )

    # 方向二：DECISIONS.md 的 D 条目里引用的 id 必须真实存在
    # （只扫 D 小节正文，不扫文首的格式模板 —— 模板里的占位 id 不是真实引用）
    refd = set()
    for _, body in sections:
        refd |= set(re.findall(r"`(new_[a-z0-9_]+)`", body))
    for eid in sorted(refd - ids_in_matrix):
        rep.error(
            "decision_references_unknown",
            f"docs/DECISIONS.md 引用了矩阵里不存在的条目 `{eid}` —— "
            f"可能是矩阵改过 id 或删了条目，文档已成谎言",
        )
    if not rep.ok():
        return  # 已有 ERROR 时不再报「一致」，避免在失败输出里混一条安慰信息
    if not news:
        rep.info(
            "decisions_ok",
            "矩阵里没有 kind=new 条目，无需决策记录"
            + (f"（本文件已有 {len(sections)} 条历史 D 条目）" if sections else ""),
        )
    else:
        rep.info(
            "decisions_ok",
            f"docs/DECISIONS.md 与矩阵双向一致：{len(news)} 条 kind=new 均有 D 条目收录",
        )


# ---------------------------------------------------------------- 防泄漏

# 有意保留在仓库里的公网 IP：全部人工审阅过，分三类 ——
#   1) 公共 DNS（配置里本来就要写）
#   2) 实测证据引用的目标站 / CDN 地址（不是我们的基础设施）
#   3) 上游文档里的示例
# 除此以外任何公网 IP 出现在被跟踪文件里 → ERROR（AGENTS.md 铁律 7）。
PUBLIC_IP_WHITELIST = {
    # 1) 公共 DNS
    "1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9", "149.112.112.112",
    "208.67.222.222", "208.67.220.220", "223.5.5.5", "223.6.6.6", "119.29.29.29",
    "114.114.114.114", "114.114.115.115", "180.76.76.76", "1.2.4.8", "210.2.4.8",
    "120.53.53.53", "1.12.12.12", "94.140.14.14", "76.76.2.0",
    # 2) 实测证据里的目标站 / CDN
    "160.79.104.10",    # claude.ai
    "34.160.111.145",   # ifconfig.me
    "172.67.75.172", "104.26.12.31", "104.26.13.31",  # ip.sb (Cloudflare)
    "104.16.132.249",   # cloudflare-dns.com（archive/ 里的 DoH 服务器）
    "162.159.141.147", "142.250.198.40", "142.250.198.0", "142.251.210.142",
    "172.217.112.4",    # Google 广告段（LESSONS L16 的拦截示例）
    "121.14.77.221",    # www.qq.com（LESSONS L18 的直连示例）
    # 3) 上游文档示例
    "128.0.0.0",
}

# 永不参与 IP 扫描的范围：RFC 私有 / 回环 / 链路本地 / 组播 / 保留 / 文档专用
_IP_EXEMPT_NETS = [
    ip_network(x)
    for x in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
        "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16",
        "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    )
]

# IPv6 侧只扫「全球单播 2000::/3」—— 真实节点地址只可能落在这里。
# 其余（8000::/1、4000::/3、6000::/3 等）都是 IETF 保留段；上游文档里的示例
# （如 migration.md 的 8000::/1 路由切换演示）用它们，不扫就不会误报。
_IP6_SCAN_NET = ip_network("2000::/3")

_IP_TOKEN = re.compile(
    # 尾部排除 `/`：CIDR（如 2000::/3、172.19.0.1/30）是路由表/网段声明，不是单主机地址，不参与扫查
    r"(?<![\w.:/])((?:\d{1,3}\.){3}\d{1,3}|(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4})(?![\w.:/])"
)

# 防泄漏扫查的「起点」：不追溯这个时刻之前的 commit message。
#
# 为什么用「时间」而不是「一份已泄漏 SHA 的清单」：**清单本身就是钥匙**。
# 要在仓库里拦住某个 SHA，就必须把那个 SHA 明文写进仓库；而 SHA 是能在 GitHub 上
# 直取旧对象的**指针**（分支重置也删不掉），写清单等于把钥匙重新泄漏一次。
# 这个递归无法用黑名单解决 —— 所以改用**单调递增、不需要点名任何 commit** 的常量：
# 「本门禁从此生效，之前的历史已知含泄漏、之后必须干净」。
#
# 取值规则（避免循环依赖）：取一个**手选、整齐、落在窗口内**的时刻 ——
#   窗口 = ( 已知最脏的 commit , 引入本门禁的 commit ]
# 窗口内任取一刻都对：早于窗口则把该拦的漏掉，晚于窗口则将来会误报无关的后续提交。
# 故意不取“引入本门禁那次提交的精确时间”：那样每改一次代码都要重取常量，形成自指循环。
# 此值只允许随真实时间前进，不得回调。
LEAK_SCAN_START_DATE = "2026-10-12 20:00:00"


def audit_tools(rep: Report):
    """工具自检：让「工具」也被自己的门禁检查一道。

    两次真实事故推动了这条：① 我在同一次会话里两次把 SyntaxError 写进工具
    （`audit.py` 的 `return    uncovered = []`、`gen-docs.py` 的 `UnboundLocalError`），
    都是靠手跑才发现 —— 而门禁自己在 CI 里跑，谁也检查不了它；
    ② `6a72411` 为了去硬编码把 `find_singbox()` 的本机兜底路径删了，
    本机 `--run` 从此静默降级为 WARN，看起来照样 PASS，
    但「真启动一次只筛 FATAL」那一层实际上没跑（CI 有 `SINGBOX_BIN`，所以 CI 仍真跑）。

    检查两类：① `tools/*.py` 能不能编译（语法错自己也是错）；
    ② 关键工具的不变量 —— `diff_config.compare()` 行为、`DIRECT_NON_EMPTY_KEYS` 语义。
    """
    tools_dir = ROOT / "tools"
    for p in sorted(tools_dir.glob("*.py")):
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as ex:
            rep.error("tool_syntax_error", f"{p.name} 无法编译：{ex}")

    # diff_config.compare 的不变量：门禁 import 它做自检，不能只“相信它没问题”
    try:
        sys.path.insert(0, str(tools_dir))
        import importlib
        dc = importlib.import_module("diff_config")
        same = dc.compare({"a": 1, "nest": {"b": [2]}}, {"a": 1, "nest": {"b": [2]}})
        if same["only_a"] or same["only_b"] or same["changed"]:
            rep.error("tool_selftest_failed", "diff_config.compare 把两份相同配置报成了差异")
        chg = dc.compare({"a": 1}, {"a": 2})
        if chg["changed"] != ["a"]:
            rep.error("tool_selftest_failed", f"diff_config.compare 漏报值变更：{chg['changed']}")
        add = dc.compare({"a": 1}, {"b": 1})
        if add["only_a"] != ["a"] or add["only_b"] != ["b"]:
            rep.error("tool_selftest_failed", "diff_config.compare 漏报新增/缺失字段")
    except Exception as ex:  # noqa: BLE001 — 自检本身失败也要报出来
        rep.error("tool_selftest_failed", f"无法对 diff_config 做自检：{ex!r}")

    # DIRECT_NON_EMPTY_KEYS 的语义守卫（对应 L1 那次真实事故）
    keys = DIRECT_NON_EMPTY_KEYS
    if len(set(keys)) != len(keys):
        rep.error("tool_selftest_failed", "DIRECT_NON_EMPTY_KEYS 里有重复项")
    # domain_strategy 被 schema:\"omit\"，填在 direct 上也仍然算「空 direct」（L1 就错在这）。
    if "domain_strategy" in keys:
        rep.error(
            "tool_selftest_failed",
            "DIRECT_NON_EMPTY_KEYS 不应包含 domain_strategy：它已被 schema 标 omit，"
            "填了也仍算空 direct（会 FATAL），详见 docs/LESSONS.md L1",
        )
    if "domain_resolver" not in keys:
        rep.error(
            "tool_selftest_failed",
            "DIRECT_NON_EMPTY_KEYS 缺了 domain_resolver：这是让 direct 非空、"
            "能当规则集下载 detour 的关键字段，详见 docs/LESSONS.md L1",
        )


def audit_redaction(rep: Report):
    """防泄漏扫查：被跟踪文件与（近期）commit message 里不许出现「未被审阅过」的公网 IP。

    这个门禁的由来是一次真实事故：L18 的证据文档写了 “实测” 二字，
    却把节点域名与它的 A/AAAA 记录（也就是用户服务器的真实地址）一起写进了公开仓库。
    当时所有门禁都通过了 —— 因为它们是按“字段”审的，而 IP 是写在散文里的。

    范围：`git ls-files` 的全部文件（含 docs/）+ commit message。
    commit message 也算“写进仓库的文本” —— 它同样公开、同样推不回来。
    但 commit message 只扫 LEAK_SCAN_START_DATE 之后的：历史里已知有泄漏，
    而“把要拦的 SHA 写进仓库”会重新泄漏一次（见该常量的说明）。
    `local/` 不跟踪、按规定就允许放真实节点，故跳过。
    豁免：- RFC 私有 / 回环 / 文档专用 / 组播 等范围
          - PUBLIC_IP_WHITELIST 里人工审阅过的公网 IP
    """
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError) as ex:
        rep.info("skip_check_template", f"无法取得 git 文件列表，跳过防泄漏扫查：{ex}")
        return
    files = [f for f in out.splitlines() if f.strip()]
    if not files:
        rep.info("skip_check_template", "git 未跟踪任何文件，跳过防泄漏扫查（可能不是 git 工作区）")
        return

    hits = {}

    def scan(text: str, label_of) -> None:
        """扫一段文本，收集未审阅的公网 IP。label_of(lineno) 给出定位串。"""
        for lineno, line in enumerate(text.splitlines(), 1):
            label = label_of(lineno)
            for m in _IP_TOKEN.finditer(line):
                raw = m.group(1)
                try:
                    addr = ip_address(raw)
                except ValueError:
                    continue
                if str(addr) in PUBLIC_IP_WHITELIST or raw in PUBLIC_IP_WHITELIST:
                    continue
                if addr.version == 6:
                    # 只看全球单播；其余保留段（::1 / fc00::/7 / fe80::/10 / 8000::/1）跳过
                    if addr not in _IP6_SCAN_NET or addr in ip_network("2001:db8::/32"):
                        continue
                elif any(addr in net for net in _IP_EXEMPT_NETS):
                    continue
                hits.setdefault(str(addr), []).append(label)

    for f in files:
        if f.startswith("local/"):
            continue  # 铁律 7：local/ 不跟踪，允许放真实节点
        p = ROOT / f
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scan(text, lambda lineno, f=f: f"{f}:{lineno}")

    # commit message 同样是公开、推不回来的文本 —— 一并扫，但只扫门禁启用之后的。
    # 不追溯更早的历史：见 LEAK_SCAN_START_DATE 的说明（写清单 = 重新泄漏）。
    try:
        log_text = subprocess.run(
            ["git", "log", f"--since={LEAK_SCAN_START_DATE}",
             "--format=%h|%s %b", "--no-color"], cwd=str(ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as ex:
        rep.info("skip_check_template", f"无法取得 git 日志，跳过 commit message 防泄漏扫查：{ex}")
        log_text = ""
    for line in log_text.splitlines():
        if not line.strip():
            continue
        sha7 = line.split("|", 1)[0]
        scan(line, lambda lineno, s=sha7: f"commit {s}（commit message）")

    if not hits:
        rep.info(
            "redaction_clean",
            f"防泄漏扫查通过：{len(files)} 个被跟踪文件，以及 {LEAK_SCAN_START_DATE} 之后的 "
            "commit message 中，没有未审阅的公网 IP",
        )
        return
    for ip, locs in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        rep.error(
            "sensitive_ip_in_repo",
            f"公网 IP {ip} 出现在被跟踪文件 {locs[0]}"
            + (f"（另有 {len(locs) - 1} 处）" if len(locs) > 1 else "")
            + "。仓库里不许出现未审阅的公网 IP（可能是真实节点地址）——"
            "请改成 RFC 5737/3849 文档地址（如 203.0.113.7 / 2001:db8::a）；"
            "确属公共 DNS 或目标站地址的，加入 tools/audit.py 的 PUBLIC_IP_WHITELIST",
        )


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
    cand = ROOT / "bin" / ("sing-box.exe" if os.name == "nt" else "sing-box")
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
    lessons_rep = Report("docs/LESSONS.md")
    audit_lessons(lessons_rep)
    if lessons_rep.items and not args.json:
        for lv, code, msg in lessons_rep.items:
            print(f"[{lv[0]}] docs/LESSONS.md: {msg}")
    if not lessons_rep.ok():
        failed = True

    # 新功能采纳台账是仓库级校验（不依赖具体配置），单独跑一次
    newfeat_rep = Report("docs/version-matrix.json")
    audit_new_features(newfeat_rep, matrix, version)
    if newfeat_rep.items and not args.json:
        for lv, code, msg in newfeat_rep.items:
            print(f"[{lv[0]}] docs/version-matrix.json: {msg}")
    if not newfeat_rep.ok():
        failed = True

    # 决策记录 ↔ 矩阵双向校验（同上，与具体配置无关）
    decisions_rep = Report("docs/DECISIONS.md")
    audit_decisions(decisions_rep, matrix, version)
    if decisions_rep.items and not args.json:
        for lv, code, msg in decisions_rep.items:
            print(f"[{lv[0]}] docs/DECISIONS.md: {msg}")
    if not decisions_rep.ok():
        failed = True

    # 防泄漏扫查（同上，与具体配置无关）：被跟踪文件里不许有未审阅的公网 IP
    redact_rep = Report("仓库防泄漏扫查（git ls-files）")
    audit_redaction(redact_rep)
    if redact_rep.items and not args.json:
        for lv, code, msg in redact_rep.items:
            print(f"[{lv[0]}] {msg}")
    if not redact_rep.ok():
        failed = True

    # 工具自检（同上，与具体配置无关）：工具也是代码，语法错与不变量失效同样要拦。
    # 只管 ERROR 不管 WARN：本机没有 sing-box 时 --run 会降级为 WARN，那是预期行为。
    tools_rep = Report("tools/*.py 自检")
    audit_tools(tools_rep)
    if tools_rep.items and not args.json:
        for lv, code, msg in tools_rep.items:
            print(f"[{lv[0]}] {msg}")
    if not tools_rep.ok():
        failed = True

    if args.files:
        # 显式传了文件就只查这些；仓库自检（无参数）时连带把 templates/groups.json
        # 送进同一套检查流程，避免出现“模板自己违规却没人管”。
        targets = [Path(f) for f in args.files]
    else:
        targets = sorted(PROFILES.rglob("*.json")) + [ROOT / "templates" / "groups.json"]

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
        # 骨架模板不是可运行配置，跳过 check / run
        is_template = t.resolve() == (ROOT / "templates" / "groups.json").resolve()
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
        if is_template:
            audit_template(rep)
        if binary and not is_template:
            run_singbox_check(binary, t, rep)
            if args.run:
                run_singbox_run(binary, t, rep, args.run_seconds)
        elif is_template:
            rep.info("skip_check_template", "templates/groups.json 是骨架模板，不是可运行配置，跳过 check / run")
        else:
            rep.info("no_singbox", "未指定 sing-box 可执行文件，已跳过 sing-box check")

        results.append((rep, platforms))
        if not rep.ok():
            failed = True

    ledger_results = [
        (lessons_rep, {"matrix"}),
        (newfeat_rep, {"new-features"}),
        (decisions_rep, {"decisions"}),
        (redact_rep, {"redaction"}),
        (tools_rep, {"tools"}),
    ]
    if args.json:
        all_results = ledger_results + results
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
                    for r, p in all_results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        # 台账/扫查的逐条输出已在各自跑完时打过；这里只补两行小结，避免重复
        for r, p in ledger_results:
            n_err, n_warn = len(r.errors), len(r.warns)
            status = "PASS" if r.ok() else "FAIL"
            print(f"  → {r.name}  [{status}]  {n_err} ERROR / {n_warn} WARN")
        for r, p in results:
            status = "PASS" if r.ok() else "FAIL"
            print(f"\n=== {r.name}  [{status}]  目标版本 {version}  平台 {'/'.join(sorted(p))}")
            for lv, c, m in r.items:
                mark = {"ERROR": "[E]", "WARN": "[W]", "INFO": "[i]"}[lv]
                print(f"  {mark} {m}")
            if r.ok() and not r.warns:
                print("  · 无问题")
        all_results = ledger_results + results
        total_err = sum(len(r.errors) for r, _ in all_results)
        total_warn = sum(len(r.warns) for r, _ in all_results)
        print(
            f"\n合计：{len(results)} 个配置文件 + {len(ledger_results)} 份台账/扫查，"
            f"{total_err} ERROR，{total_warn} WARN"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
