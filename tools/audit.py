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
import tempfile
from ipaddress import ip_address, ip_network
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "version-matrix.json"
PROFILES = ROOT / "profiles"
# local/ 不进仓库（.gitignore），但里面的配置是**用户真机实际运行的**。
# 门禁必须覆盖它，否则「仓库全绿、真机炸」会持续发生（L35）。
LOCAL = ROOT / "local"
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

SEG_RE = re.compile(r"^([A-Za-z0-9_$\-]*)(\[([^\]]*)\])?$")


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
    """审计报告。每条消息可选带 `where`（`文件:行号`）——

    为什么加 `where`（七条改造第 6 条「门禁输出『改哪里』而不是『哪里错』」）：
    门禁原本只说 `§4 说 desktop 的 …`，读的人还得回去搜行号。带上定位后，
    IDE/终端可以直接点开。它同时是**修法提示**：不说位置，等于把查找成本转给人。
    格式统一 `相对路径:行号`（与编译器输出同形，便于 `grep` 与编辑器识别）。
    """

    def __init__(self, name):
        self.name = name
        self.items = []  # (level, code, message, where)

    def error(self, code, msg, where=None):
        self.items.append(("ERROR", code, msg, where))

    def warn(self, code, msg, where=None):
        self.items.append(("WARN", code, msg, where))

    def info(self, code, msg, where=None):
        self.items.append(("INFO", code, msg, where))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    @property
    def warns(self):
        return [i for i in self.items if i[0] == "WARN"]

    def ok(self):
        return not self.errors


def _loc(path, line=None) -> str:
    """拼一个「文件:行号」定位串（相对仓库根，统一用 `/`）。"""
    p = str(path).replace("\\", "/")
    if p.startswith(str(ROOT).replace("\\", "/") + "/"):
        p = p[len(str(ROOT).replace("\\", "/")) + 1:]
    return f"{p}:{line}" if line else p


# ---------------------------------------------------------------- 主审查


def audit_matrix(cfg, rep: Report, matrix, target_version: str, platforms, is_template: bool = False):
    """按 version-matrix.json 检查废弃 / 移除 / 平台差异 / 新功能采纳。

    `is_template=True` 用于 `templates/groups.json`：它是**骨架**，只放出站与策略组的骨架，
    不含 `dns` / `inbounds` / `route` 的全量字段。「矩阵要求某新字段必须在配置里」
    （kind=new / expect=present）这类断言在骨架上无从满足，硬跑只会得到一个假 ERROR（L43）——
    所以跳过那一支，并回传跳过了哪些条目，由调用方打一条 INFO，
    避免「静默跳过」又变成新的盲区。

    返回：被跳过的 expect=present 条目 id 列表。
    """
    new_present_skipped = []
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
            if expect == "absent":
                if found:
                    rep.error(
                        e["id"],
                        f"[{e['id']}] 配置里出现了 {e['path']}，但本仓库对该新功能的决策是"
                        f"「不启用」（{e.get('title', '')}）—— 要么删掉字段，要么把矩阵里的 adopt 改掉并写明理由",
                    )
            elif is_template:
                # 骨架模板没有 dns / inbounds / route 全量字段，不参与 present 断言。
                new_present_skipped.append(e["id"])
            elif not found:
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
    return new_present_skipped


def _audit_jinx(route, rep: Report):
    """Jinx 广告/放行规则集的成对性与顺序（本仓库强规范）。

    官方要求（https://github.com/RiverFlowsInUUU/Jinx#-规则顺序）：
        1 jinx-direct   → direct  白名单先放行
        2 jinx-ads      → 🚫 AD 组  拦截（🚫 AD 的唯一出口是 block）
        3 awanue-ads    → 🚫 AD 组  拦截（秋风判定不同，会拦掉 Jinx 白名单的 8 个域，必须排后面）
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

    # route 层：广告拦截集只能落到去广告组（唯一出口是 block）或直接 reject
    #     （DNS 层另有一套约束，见 _audit_dns_adblock / docs/LESSONS.md L28）
    for i, r in enumerate((route.get("rules") or [])):
        if not isinstance(r, dict):
            continue
        for t in ("jinx-ads", "awanue-ads"):
            if t in (r.get("rule_set") or []):
                ob = r.get("outbound")
                if ob != GROUP_AD and r.get("action") != "reject":
                    rep.error(
                        "jinx_ads_target",
                        f"route.rules[{i}] 把 {t} 指向了 {ob or r.get('action')!r}，"
                        f"广告拦截集只能落到 {GROUP_AD} 组或直接 reject",
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


DNS_AD_SETS = ("jinx-ads", "awanue-ads")


def _audit_dns_adblock(cfg, rep: Report):
    """DNS 层广告拦截（可选启用）的成对性与顺序约束 —— docs/LESSONS.md L28。

    启用形态（本项目约定）：

        { "rule_set": ["jinx-direct"],            "action": "route",      "server": "dns-cn"  }
        { "rule_set": ["jinx-ads", "awanue-ads"], "action": "predefined", "rcode": "NXDOMAIN" }

    为什么要单独校验：`dns.rules` 与 `route.rules` 是**两份独立的顺序表**，改一处极易忘另一处，
    而两处错误都是**静默**的 ——
      · 白名单排到拦截之后：白名单失效（实测 47 条域 100% 被拦截集覆盖），
        微信 / 推送 / 统计类域名集体 NXDOMAIN；
      · 拦截排到 `geosite-cn` 之后：国内广告域名先被 `route dns-cn` 放行，DNS 拦截永不生效。
    """
    dns = cfg.get("dns") or {}
    rules = dns.get("rules") or []
    if not isinstance(rules, list):
        return

    def sets_of(r):
        v = r.get("rule_set") if isinstance(r, dict) else None
        return v if isinstance(v, list) else []

    ad_idx = [
        i
        for i, r in enumerate(rules)
        if any(t in sets_of(r) for t in DNS_AD_SETS)
    ]
    wl_idx = [i for i, r in enumerate(rules) if "jinx-direct" in sets_of(r)]
    if not ad_idx and not wl_idx:
        return  # 未启用 DNS 层广告拦截，不约束

    # 1) 拦截集必须有白名单配套（缺白名单 = 全量拦截，属事故）
    if ad_idx and not wl_idx:
        rep.error(
            "dns_ad_without_whitelist",
            f"dns.rules 引入了广告拦截集 {[t for t in DNS_AD_SETS]}（第 {ad_idx} 条），"
            "却没有配套的 jinx-direct 白名单。Jinx 发布的白名单是拦截集的豁免名单，"
            "缺了它会把本就该放行的域名一起拦掉。补一条 "
            '`{"rule_set": ["jinx-direct"], "action": "route", "server": "dns-cn"}` 并排在拦截之前',
        )

    # 2) 动作必须正确：白名单放行(route)、拦截集拦截(predefined/reject)
    for i in wl_idx:
        if rules[i].get("action") != "route":
            rep.error(
                "dns_ad_target",
                f"dns.rules[{i}] 用 jinx-direct 白名单但 action="
                f"{rules[i].get('action')!r}，白名单必须是 route（放行到 dns-cn）",
            )
    for i in ad_idx:
        act = rules[i].get("action")
        if act not in ("predefined", "reject"):
            rep.error(
                "dns_ad_target",
                f"dns.rules[{i}] 用广告拦截集但 action={act!r}；DNS 层拦截只能落在 "
                "predefined（如 rcode=NXDOMAIN）或 reject，"
                "写成 route 只会把广告域名送去某个 DNS 服务器解析，等于没拦",
            )
        if act == "route":
            rep.error(
                "dns_ad_target",
                f"dns.rules[{i}] 把广告拦截集 route 到了 server={rules[i].get('server')!r}，等于没拦",
            )

    # 3) 顺序：白名单 → 拦截 → geosite-cn（两级都是「先命中先终止」，排错即静默失效）
    pos_cn = None
    for i, r in enumerate(rules):
        if "geosite-cn" in sets_of(r):
            pos_cn = i
            break
    if wl_idx and ad_idx and min(wl_idx) > min(ad_idx):
        rep.error(
            "dns_ad_order",
            f"dns.rules 顺序错误：白名单 jinx-direct 在第 {min(wl_idx)} 条，"
            f"却排在广告拦截集（第 {min(ad_idx)} 条）之后。"
            "实测 Jinx 白名单 47 条域 100% 被拦截集覆盖（如 gm.mmstat.com ← mmstat.com），"
            "白名单必须排在拦截之前",
        )
    if ad_idx and pos_cn is not None and min(ad_idx) > pos_cn:
        rep.error(
            "dns_ad_order",
            f"dns.rules 顺序错误：广告拦截集在第 {min(ad_idx)} 条，"
            f"却排在 geosite-cn（第 {pos_cn} 条）之后。"
            "国内广告域名多数也算大陆域名，会先被 geosite-cn 放行、拦截永不生效",
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
    # 2c) DNS 层广告拦截（可选）：route 层与 dns 层是两份独立的顺序表，各自校一遍
    _audit_dns_adblock(cfg, rep)

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

    # 3a) 组的类型与嵌套：见 GROUP_TYPES_REQUIRED；组的 outbounds 里只放真实节点
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        want = GROUP_TYPES_REQUIRED.get(o.get("tag"))
        if want and o.get("type") != want:
            rep.error(
                "group_wrong_type",
                f"outbounds[{i}] ({o.get('tag')}) 必须是 {want}（当前 {o.get('type')}）："
                f"{GROUP_PROXY} 与 {GROUP_AI} 是两个独立优选组、各自 urltest；{GROUP_AD} 是 selector",
            )
        if o.get("tag") not in NO_NESTING_GROUPS:
            continue
        nested = [r for r in (o.get("outbounds") or []) if r in GROUP_TAGS]
        if nested:
            rep.error(
                "group_nesting",
                f"outbounds[{i}] ({o.get('tag')}) 引用了其它分流组 {nested}："
                "组的 outbounds 里只允许放真实节点，嵌套 urltest 会串联两次测速"
                f"（m02132 用户要求 {GROUP_AI} 直接是 urltest + 台湾节点，不要 {GROUP_PROXY} 作子节点）",
            )

    # 3bis) 三个组的 tag 必须逐字等于规范名（emoji + 一个空格 + 名字）。
    # 它们是 route.final、route.rules[].outbound、DNS 规则与规则集的引用目标，
    # 一个字符不同就等价于「tag 找不到」；同时它也是客户端策略组列表里的显示名。
    for i, o in enumerate(outs):
        if isinstance(o, dict) and o.get("tag") in GROUP_TAGS:
            if not GROUP_TAG_RE.match(o["tag"]):
                rep.error(
                    "group_tag_incomplete",
                    f"outbounds[{i}] 的分流组 tag {o['tag']!r} 不是「emoji + 一个 ASCII 空格 + 名字」的形式；"
                    f"规范名是 {GROUP_TAGS}",
                )

    # ⚠️ 这里按 *裸 ASCII* 的旧名反查（"Proxy" / "AI" / "AD"），
    # 而不是在 GROUP_TAGS 里找 —— 漏改的结果恰恰是「tag 退回了旧名」，
    # 在集合里根本发现不了（与 audit_platform_caps 里同一门禁互补）。
    legacy = {"Proxy", "AI", "AD"}
    for i, o in enumerate(outs):
        if isinstance(o, dict) and o.get("tag") in legacy:
            rep.error(
                "group_tag_incomplete",
                f"outbounds[{i}] 的分流组 tag {o['tag']!r} 是旧名（裸 ASCII）："
                f"规范名必须逐字是 {GROUP_TAGS}",
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
    # 3b-bis) 出站 / 规则集 / HTTP 客户端的 domain_resolver.server 也是引用 dns.servers 的 tag。
    #          ⚠️ 骨架模板（templates/groups.json）没有 dns 段，此时 dns_tags 为空，
    #          不能把「引用了尚未声明的 DNS 服务」当成错误 —— 只有定义了 dns.servers 才校验。
    #          写错了 sing-box check 依旧 exit=0（它只反序列化、不做任何初始化）；
    #          真跑起来那条出站就解析不了自己的 server 域名。
    if dns_tags:
        # 三个位置都挂 domain_resolver：出站自身、规则集下载、HTTP 客户端。
        holders = [(f"outbounds[{i}]", o.get("tag"), o.get("domain_resolver")) for i, o in enumerate(outs) if isinstance(o, dict)]
        holders += [(f"route.rule_set[{i}]", rs.get("tag"), rs.get("domain_resolver"))
                    for i, rs in enumerate(route.get("rule_set", [])) if isinstance(rs, dict)]
        holders += [(f"http_clients[{i}]", hc.get("tag"), hc.get("domain_resolver"))
                    for i, hc in enumerate(cfg.get("http_clients", []) or []) if isinstance(hc, dict)]
        for where, tag, dr in holders:
            if isinstance(dr, dict) and dr.get("server") and dr["server"] not in dns_tags:
                rep.error(
                    "domain_resolver_missing",
                    f"{where} ({tag}) 的 domain_resolver.server = {dr['server']!r} 不在 dns.servers 中",
                )

    # 3c) DNS 规则与服务引用完整性
    #     ⚠️ dns.servers[].detour 也在这里校 —— 它同样是「tag 拼写错了也不报错」的引用：
    #     组改名（铁律 20）时漏改 detour，dns-proxy 就会指向一个不存在的出站。
    #     sing-box check 对此 exit=0，只有真跑起来才会在查解析阶段默默退化。
    for i, s in enumerate(cfg.get("dns", {}).get("servers", [])):
        if not isinstance(s, dict):
            continue
        dt = s.get("detour")
        if dt and dt not in tagset:
            rep.error(
                "dns_server_detour_missing",
                f"dns.servers[{i}] ({s.get('tag')}) 的 detour = {dt!r} 不在出站列表中"
                "（sing-box check 不校验这个）",
            )
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

    # 4) 去广告组只能放 block（m07194：删掉 direct）；默认值必须是 block，否则整个去广告链路静默失效
    for i, o in enumerate(outs):
        if not isinstance(o, dict):
            continue
        if o.get("tag") != GROUP_AD:
            continue
        if o.get("type") == "selector":
            bad = [r for r in (o.get("outbounds") or []) if r not in GROUP_AD_OUTBOUNDS]
            if bad:
                rep.error(
                    "ad_group_polluted",
                    f"{GROUP_AD} 分流组只能放 {GROUP_AD_OUTBOUNDS}，不能放 {bad}；"
                    f"广告拦截组不得放入代理节点，也不要放 direct（m07194：{GROUP_AD} 只要 {GROUP_AD_DEFAULT} 作出口）",
                )
            # 详见 docs/LESSONS.md L17：default 被改成 direct（或写了个不存在的 tag）时，
            # 规则照样命中 🚫 AD 组，但连接被放行 —— 没有任何报错，广告静默漏过。
            if o.get("default") not in (None, GROUP_AD_DEFAULT):
                rep.error(
                    "ad_group_default_not_block",
                    f"{GROUP_AD} 分流组的 default = {o.get('default')!r}，必须是 \"{GROUP_AD_DEFAULT}\"："
                    f"广告规则命中 {GROUP_AD} 组后若默认出站不是 block，广告会静默直连放行",
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
                f"+ 一条 ERROR（... using outbound/selector[{GROUP_AD}]: operation not permitted）。"
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
    #     （即最终落到 final 的那部分）。任何走 route(🤖 AI 组)/route(🚫 AD 组)/route(direct) 的连接
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
                "命中智能组/去广告组/direct 的域名仍会被原样交给代理服务端解析（服务端可用 IPv6 出口）。"
                "resolve 必须紧跟 hijack-dns，排在所有 route/reject 之前（详见 docs/LESSONS.md L18）",
            )


GROUP_TYPES = ("selector", "urltest", "block", "dns")
# 分流组 tag。**这就是配置里真实出现的字符串，含 emoji 与一个空格**——
# 改动它等于改动所有 profile / 模板 / 规则 / DNS detour / route.final，
# 且旧配置（含本地未提交的那几份）会与新配置的 cache 与规则命名对不上。
GROUP_PROXY = "🚀 Proxy"
GROUP_AI = "🤖 AI"
GROUP_AD = "🚫 AD"
# 分流组（骨架 tag 固定），任何一个配置文件都不得出现同名 tag 的重复语义
GROUP_TAGS = (GROUP_PROXY, GROUP_AI, GROUP_AD)
# 组的 outbounds 里只允许出现真实节点，不允许嵌套组（urltest 套 urltest 会串联两次测速）
NO_NESTING_GROUPS = GROUP_TAGS
# 固定组的类型不允许被改（m02132：智能组与代理组一样是 urltest，不再是指向代理组的 selector）
GROUP_TYPES_REQUIRED = {GROUP_PROXY: "urltest", GROUP_AI: "urltest", GROUP_AD: "selector"}
# 去广告组只允许一个出口（m07194）：block。direct 曾被放在这里作为「放行」档，
# 但它会让 AD 组变成一个用户看不出差别的开关，且任何误选都会让广告静默直连。
GROUP_AD_OUTBOUNDS = ("block",)
GROUP_AD_DEFAULT = "block"
# 每个组 tag 必须由一个「emoji + 一个 ASCII 空格 + 名字」构成：这是显示层面的约定（门禁 group_tag_incomplete）
GROUP_TAG_RE = re.compile(r"^[^\x00-]+ [A-Za-z0-9]+$")


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


def _probe_candidates(path: str):
    """把矩阵里的一个 path 模式变成若干「探针配置」。

    为什么要探针：矩阵的 `path` 是门禁的唯一抓手（`audit_matrix` 全靠 find_paths 去找字段）。
    上游一旦重命名或删除字段，find_paths 就永远返回空 —— `kind=deprecated` 的条目**静默失声**
    （变成死门禁，L34 同形），`kind=new expect=absent` 的反而**假绿**，因为本来就该找不到。
    此前没有任何门禁验证「矩阵的 path 在锁定的内核上仍然可达」。

    做法：不读真实配置，而是**按 path 注入**一个最小探针，交给 `sing-box check` 判：
      · 内核说 unknown field "<leaf>"                    → 它不认识这个字段；
      · 内核说 ... is deprecated in sing-box A and will be removed in B → 认识且已废弃；
      · 内核毫无意见                                      → 认识。
    把这三类信号与矩阵自报的 `deprecated_in` / `removed_in` / `since` 交叉比对，
    就能在没有服务端日志、没有上游 changelog 的情况下发现「门禁与内核脱节」。

    返回 [(说明, 探针配置)]；模式太复杂无法注入时返回 []（由调用方报 WARN，不静默放过）。
    """

    def build(segs):
        """自底向上构造：返回「该段及其之后」对应的值；无法构造返回 None。"""
        if not segs:
            return 0  # 叶子一律给 0，让内核只看「认不认识这个名字」
        seg = segs[0]
        rest = segs[1:]
        if seg in ("*", "**"):
            return None  # 通配由调用方展开
        m = re.match(r"^([A-Za-z0-9_\-]*)(?:\[([^\]]*)\])?$", seg)
        if not m:
            return None
        key, flt = m.group(1), m.group(2)
        child = build(rest)
        if child is None:
            return None
        if flt is None:
            return {key: child} if key else None
        if flt == "":
            item = child
        else:
            m2 = re.match(r"^([A-Za-z0-9_]+)=(.+)$", flt)
            if not m2:
                return None
            item = dict(child) if isinstance(child, dict) else {"_v": child}
            item[m2.group(1)] = m2.group(2)
        return {key: [item]}

    segs = path.split(".")
    if "**" in segs:
        # ** 语义是「任何一层」，所以把尾段挂到几个典型宿主上，任一命中即算可达。
        i = segs.index("**")
        body = build(segs[i + 1:])
        if body is None or not isinstance(body, dict):
            return []
        hosts = (
            ("根", "root"),
            ("inbounds[type=tun]", "inbounds"),
            ("outbounds[type=direct]", "outbounds"),
            ("dns.rules[0]", "dnsrules"),
            ("route.rules[0]", "routerules"),
        )
        out = []
        for label, kind in hosts:
            if kind == "root":
                cfg = {}
                tgt = cfg
            elif kind == "inbounds":
                cfg = {"inbounds": [{"type": "tun"}]}
                tgt = cfg["inbounds"][0]
            elif kind == "outbounds":
                cfg = {"outbounds": [{"type": "direct"}]}
                tgt = cfg["outbounds"][0]
            elif kind == "dnsrules":
                cfg = {"dns": {"rules": [{}]}}
                tgt = cfg["dns"]["rules"][0]
            else:
                cfg = {"route": {"rules": [{}]}}
                tgt = cfg["route"]["rules"][0]
            tgt.update(body)
            out.append((label, cfg))
        return out

    probe = build(segs)
    if not isinstance(probe, dict):
        return []
    return [("根", probe)]


def _probe_verdict(binary: str, cfg, tmp: Path):
    """跑一次探针，返回 (字段是否被内核认识, 内核自报的废弃/移除版本, 原始输出)。

    `sing-box check` 的错误文本就是判据；上游改文案会在这里暴露（配 negtest 的用例）。
    """
    tmp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    try:
        p = subprocess.run(
            [binary, "check", "-c", str(tmp)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as ex:
        return None, {}, "探针无法执行：" + str(ex)
    out = re.sub(r"\x1b\[[0-9;]*m", "", (p.stdout or "") + (p.stderr or ""))
    dep = re.search(r"deprecated in sing-box (\d+\.\d+\.\d+)", out)
    rem = re.search(r"removed in sing-box (\d+\.\d+\.\d+)", out)
    return ("unknown field" not in out), {
        "deprecated_in": dep.group(1) if dep else None,
        "removed_in": rem.group(1) if rem else None,
    }, out


def audit_matrix_paths(rep: Report, matrix, target_version: str, binary):
    """矩阵 path 与锁定内核的「字段实际是否存在」交叉对账。

    这是「内核升级导致门禁失效」的**检测器**：矩阵与内核任何一边变了这里都会响。

    判据只取一个方向 —— **内核已经不认这个字段，而矩阵还在要求门禁去查它**：
    此时 `find_paths` 永远返回空，`kind=deprecated/removed` 的条目会静默失声
    （门禁还在、但永远不会响，L34 同形），而这**在仓库里没有任何其他信号**。

    刻意**不报**的两种情况：
      · 矩阵说「已移除」，内核仍照收 —— 这在本项目里是**常态**：sing-box 用 migration 保住旧字段，
        就是为了让人误用时不至于炸；正因如此才需要 `kind=deprecated` 门禁，两者不矛盾。
        早先误把这当 ERROR，一跑就 17 条假报警，已删。
      · 两边都不提版本号 —— 信息不足，不判。
    """
    if binary is None:
        rep.info("matrix_probe_skipped", "未指定 sing-box 可执行文件，跳过「矩阵 path 与内核」交叉对账")
        return
    checked = 0
    probed = 0
    unreachable = []
    unprobeable = []
    # 探针是**临时**文件，放系统临时目录而不是仓库里 —— CI checkout 里没有 `local/`
    # （它不入库），早先写 `LOCAL / ".matrix-probe.json"` 在 CI 上直接
    # FileNotFoundError 把整个门禁跑崩（正是 L30 那类「环境依赖写在常量里」）。
    tmp = Path(tempfile.gettempdir()) / "sb-matrix-probe.json"
    try:
        for e in matrix.get("entries") or []:
            path = e.get("path")
            if not path:
                continue
            paths = path if isinstance(path, list) else [path]
            for p in paths:
                if not p or p.strip("*") == "":
                    continue
                eid = str(e.get("id"))
                # 只对「当前版本上这个字段本该已经存在」的条目做可达性判定。
                declared = e.get("deprecated_in") or e.get("removed_in") or e.get("since")
                if not declared or not ver_ge(target_version, declared):
                    continue
                cands = _probe_candidates(p)
                if not cands:
                    unprobeable.append(eid + " 的 " + p)
                    continue
                m = re.search(r"([A-Za-z0-9_]+)(?:\[[^\]]*\])?$", p)
                leaf = m.group(1) if m else None
                known = None
                info = {}
                for _label, cfg in cands:
                    probed += 1
                    k, i2, out = _probe_verdict(binary, cfg, tmp)
                    if k is None:
                        rep.warn("matrix_path_probe_error", out)
                        known = None
                        break
                    # 内核可能报多个 unknown field。只有「报的恰好是这个叶子」才算字段不认；
                    # 报的是**别的**键（例如把 tls 塞进不接受 tls 的宿主）说明探针本身不合法，
                    # 换下一个宿主再试。此前只查「输出里是否出现 leaf 名」，会把这类误判成「认识」。
                    unknown = set(re.findall(r'unknown field "([^"]+)"', out))
                    if unknown and leaf not in unknown:
                        continue
                    if not unknown:
                        known = True
                        info = i2
                        break
                    known = False
                if known is None:
                    continue
                checked += 1
                if not known:
                    unreachable.append((eid, p, declared))
                    continue
                core_dep, core_rem = info.get("deprecated_in"), info.get("removed_in")
                declared_removed = e.get("removed_in")
                # 内核自报的版本号比矩阵更早时，矩阵多半漏了更早的废弃点（只提醒，不判罚）。
                if core_rem and declared_removed and not ver_ge(core_rem, declared_removed):
                    rep.warn(
                        "matrix_version_mismatch",
                        "条目 " + eid + " 的 removed_in：矩阵写 " + declared_removed
                        + "，内核自报 " + core_rem + "（以后者为准）",
                    )
                elif core_dep and declared and not ver_ge(core_dep, declared):
                    rep.warn(
                        "matrix_version_mismatch",
                        "条目 " + eid + " 的 deprecated_in：矩阵写 " + declared
                        + "，内核自报 " + core_dep + "（以后者为准）",
                    )
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    for eid, p, declared in unreachable:
        rep.error(
            "matrix_path_unreachable",
            "矩阵要求门禁去查 " + eid + " 的 " + p + "（自称从 " + declared
            + " 起存在/废弃），但 " + target_version + " 的内核已经不认这个字段了 —— "
            "find_paths 永远返回空，**这条门禁已经悄悄失效**。"
            "多半是上游改过路径或名字：请对照内核源码更新 path/replacement，或把它标记为彻底移除",
            where="docs/version-matrix.json",
        )
    for item in unprobeable:
        rep.warn(
            "matrix_path_unprobeable",
            "路径 " + item + " 无法构造探针（含通配或复杂的过滤器），"
            "它是否仍对得上当前内核**没人能验**；建议拆成可注入的简单路径",
            where="docs/version-matrix.json",
        )
    if not rep.errors and not rep.warns:
        rep.info(
            "matrix_path_ok",
            "矩阵 path 与内核 " + target_version + " 交叉对账通过（"
            + str(checked) + " 条作过探针，共 " + str(probed) + " 次注入）",
        )


def audit_template(rep: Report):
    """校 templates/groups.json（固定分流组骨架）。

    这份文件是每个 profile 的出站骨架，它自身写错了，生成的配置就会集体写错。
    重点：代理组必须是 urltest（m01246 起不再有单独的 Auto 组）；组 tag 必须带 emoji 前缀。
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
    required = (*GROUP_TAGS, "direct", "block", "direct-download")
    for tag in required:
        if tag not in by_tag:
            rep.error("template_group_missing", f"templates/groups.json 缺固定组 `{tag}`")
    if "Auto" in by_tag:
        rep.error(
            "template_legacy_auto",
            f"templates/groups.json 里仍有 `Auto` 组：{GROUP_PROXY} 本身就是 urltest，不再需要单独的 Auto",
        )
    proxy = by_tag.get(GROUP_PROXY)
    if proxy and proxy.get("type") != "urltest":
        rep.error(
            "template_proxy_not_urltest",
            f"{GROUP_PROXY} 必须是 urltest（当前 {proxy.get('type')}）——它是全局默认出口与兜底",
        )
    if proxy and not proxy.get("url"):
        rep.error("template_proxy_no_url", f"{GROUP_PROXY} (urltest) 必须有 url，否则节点测速无意义")
    ai = by_tag.get(GROUP_AI)
    if ai and ai.get("type") != "urltest":
        rep.error(
            "template_ai_not_urltest",
            f"{GROUP_AI} 必须是 urltest（当前 {ai.get('type')}）——它与 {GROUP_PROXY} 是两个独立的优选组",
        )
    if ai and not ai.get("url"):
        rep.error("template_ai_no_url", f"{GROUP_AI} (urltest) 必须有 url，否则节点测速无意义")
    ad = by_tag.get(GROUP_AD)
    if ad and set(ad.get("outbounds") or []) - set(GROUP_AD_OUTBOUNDS):
        rep.error(
            "template_ad_polluted",
            f"{GROUP_AD} 只允许 {GROUP_AD_OUTBOUNDS}（m07194：删掉 direct）",
        )
    # 模板里的组 tag 也必须逐字带 emoji：走到这里说明 tag 已经不可比对，
    # 报一句人看得懂的「你写的是旧名」，比只报「缺固定组」更省排查时间。
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("tag") in {"Proxy", "AI", "AD"}:
            rep.error(
                "template_group_tag_incomplete",
                f"templates/groups.json 里的组 tag {ob['tag']!r} 是旧名（裸 ASCII）："
                f"规范名必须逐字是 {GROUP_TAGS}",
            )

    if ad and ad.get("default") not in (None, GROUP_AD_DEFAULT):
        rep.error("template_ad_default_not_block", f"{GROUP_AD} 的 default 必须是 block")

    # 三个骨架组的 tag 必须「emoji + 空格 + 名字」——它是给用户看的显示名，
    # 写成裸 ASCII（Proxy/AI/AD）会直接暴露在 sing-box 客户端的策略组列表里。
    for tag in GROUP_TAGS:
        if not GROUP_TAG_RE.match(tag):
            rep.error(
                "template_group_tag_incomplete",
                f"分流组 tag {tag!r} 不是「emoji + 一个 ASCII 空格 + 名字」的形式",
            )


def audit_platform_caps(cfg, rep: Report, platforms):
    """按平台能力差异检查配置。

    ⚠️ 这里只能拦「配置里写了什么」的显式问题。**平台差异的完整清单在
    docs/PLATFORM-MATRIX.md**，那份表由 audit_matrix_platform() 与三份 profile 对账。
    """
    if {"android", "ios"} & platforms:
        for i, ib in enumerate(cfg.get("inbounds", [])):
            if ib.get("type") == "tun" and "strict_route" in ib:
                rep.error(
                    "platform_strict_route",
                    f"inbounds[{i}].strict_route 在 Android / Apple 客户端未实现，请删除",
                )
    # ⚠️ 不要在这里加「Android 不能引用 local DNS」之类的检查：
    # 本仓库的 DNS 服务器 tag 是 dns-bootstrap / dns-cn / dns-proxy，
    # 历史上那条按 `domain_resolver == "dns-local"` 匹配的门禁永远不可能触发（死检查），已删。
    # 真要拦，就按当前实际使用的 tag 写，并同步 docs/PLATFORM-MATRIX.md。
    if "android" in platforms:
        route = cfg.get("route") or {}
        if route.get("override_android_vpn") and not route.get("auto_detect_interface"):
            rep.warn(
                "android_override_vpn_no_adi",
                "route.override_android_vpn 需要 route.auto_detect_interface 才生效，当前未开",
            )
    if "ios" in platforms:
        # Apple 图形客户端的 "Include All Networks" 与 sing-tun 的 system/mixed 栈互斥
        # （sing-tun stack.go：两种栈在 options.IncludeAllNetworks 时返回 ErrIncludeAllNetworks）。
        # stack 在 1.15.0 废弃、1.17.0 移除；移除后不再需要这个取舍，故只是 WARN。
        for i, ib in enumerate(cfg.get("inbounds", [])):
            if ib.get("type") == "tun" and ib.get("stack") in ("system", "mixed"):
                rep.warn(
                    "apple_include_all_networks_stack",
                    f"inbounds[{i}].stack = '{ib['stack']}' 与 Apple 客户端的 "
                    f"\"Include All Networks\" 互斥（sing-tun 返回 ErrIncludeAllNetworks）；"
                    f"要在 iOS 上开那个开关就得删掉 stack（1.15.0 起废弃、1.17.0 移除）",
                )
    # http_client.engine = "apple" 是 Apple 独占（NSURLSession），换到别的平台内核直接起不来。
    for i, c in enumerate(cfg.get("http_clients", []) or []):
        if isinstance(c, dict) and c.get("engine") == "apple" and not (platforms <= {"ios"}):
            rep.error(
                "apple_engine_on_universal",
                f"http_clients[{i}].engine = 'apple' 只在 Apple 平台可用，"
                f"当前平台 {'/'.join(sorted(platforms))} 会解析失败——要用就做成 Apple 专用 profile",
            )
    # 组 tag 必须逐字带 emoji 前缀（铁律 20）。矩阵对账只能发现「三份互不一致」，
    # 三份一起被改成裸 ASCII 时矩阵也无能为力 —— 所以这里再兜一道。
    for i, o in enumerate(cfg.get("outbounds", []) or []):
        if isinstance(o, dict) and o.get("tag") in {"Proxy", "AI", "AD"}:
            rep.error(
                "group_tag_incomplete",
                f"outbounds[{i}] 的分流组 tag {o['tag']!r} 是旧名（裸 ASCII）："
                f"规范名必须逐字是 {GROUP_TAGS}",
            )


# ---------------------------------------------------- 平台差异矩阵对账

PLATFORM_MATRIX = ROOT / "docs" / "PLATFORM-MATRIX.md"
MATRIX_SEC4_HEAD = "## 4. 三平台配置差异速查（本仓库实际做法）"


def _matrix_sec4_lineno():
    """§4 表头的行号（用于把「差异没登记」直接定位到该加行的位置）。"""
    if not PLATFORM_MATRIX.exists():
        return 1
    text = PLATFORM_MATRIX.read_text(encoding="utf-8")
    i = text.find(MATRIX_SEC4_HEAD)
    return text.count(chr(10), 0, i) + 1 if i >= 0 else 1


MATRIX_SEC4_LINENO = _matrix_sec4_lineno()
PROFILE_ORDER = ("desktop", "android", "ios")
_PROFILE_DIR = "1.14"
class _Missing:
    """哨兵：路径不存在。带可读 repr，免得错误信息里印出 <object object at 0x...>。"""

    def __repr__(self):
        return "<不存在>"


_MISSING = _Missing()


def _flatten(node, path="", out=None):
    """把嵌套 JSON 展平成 {路径: 值}；空容器也留一个路径。"""
    if out is None:
        out = {}
    if isinstance(node, dict):
        if not node:
            out[path] = {}
        for k, v in node.items():
            _flatten(v, f"{path}.{k}" if path else k, out)
    elif isinstance(node, list):
        if not node:
            out[path] = []
        for i, v in enumerate(node):
            _flatten(v, f"{path}[{i}]", out)
    else:
        out[path] = node
    return out


def _resolve_path(cfg, path: str):
    """按 `a.b[0].c` 取子节点；不存在返回 _MISSING。"""
    node = cfg
    for m in re.finditer(r"([A-Za-z0-9_\-]+)|\[(\d+)\]", path):
        if node is _MISSING:
            return _MISSING
        if m.group(1) is not None:
            if not isinstance(node, dict) or m.group(1) not in node:
                return _MISSING
            node = node[m.group(1)]
        else:
            idx = int(m.group(2))
            if not isinstance(node, list) or idx >= len(node):
                return _MISSING
            node = node[idx]
    return node


def _sec4_rows():
    """从 docs/PLATFORM-MATRIX.md 的 §4 表抽出 [(路径, 是否条数, {平台: 单元格}, 行号)]。

    行号是给「门禁输出『改哪里』」用的（七条改造第 6 条）：报错时必须能直接跳到 §4 那一行，
    否则读的人得回文件里搜。
    """
    if not PLATFORM_MATRIX.exists():
        return None
    text = PLATFORM_MATRIX.read_text(encoding="utf-8")
    i = text.find(MATRIX_SEC4_HEAD)
    if i < 0:
        return None
    # 先算 §4 起始行号（1-based），表格行号 = 起始行 + 段内偏移。
    sec_start_lineno = text.count("\n", 0, i) + 1
    body = text[i:]
    end = body.find("\n## ", 1)
    if end > 0:
        body = body[:end]
    rows = []
    for offset, line in enumerate(body.splitlines()):
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4:
            continue
        if cells[0] in ("项", "JSON 路径"):
            continue
        m = re.match(r"^`([^`]+)`(\s*条数)?$", cells[0])
        if not m:
            continue
        rows.append((m.group(1), m.group(2) is not None,
                     dict(zip(PROFILE_ORDER, cells[1:])), sec_start_lineno + offset))
    return rows


def _load_profiles(rep: Report):
    cfgs = {}
    for k in PROFILE_ORDER:
        p = PROFILES / _PROFILE_DIR / f"{k}-lazy.json"
        if not p.exists():
            rep.error("matrix_platform_stale", f"找不到 profiles/{_PROFILE_DIR}/{k}-lazy.json")
            return None
        cfgs[k] = json.loads(p.read_text(encoding="utf-8"))
    return cfgs


def audit_matrix_platform(rep: Report):
    """把 docs/PLATFORM-MATRIX.md §4 的差异速查表与三份 profile 逐项对账。

    为什么需要：PLATFORM-MATRIX.md 是平台差异的唯一权威清单，此前**零门禁**——
    它在第 1 节把 route_*_address_set 一律标 ✅（错的）、在第 4 节漏了 experimental，
    机器全绿，只有人读才可能发现。这正对 L26/L27 的那条教训：台账里写下的断言
    必须有字段/门禁承载。

    两条门禁：
      · matrix_platform_stale —— §4 里某一行的值/存在性与实际配置不符；
      · profile_drift         —— 三份配置出现了 §4 没登记的差异。
    """
    rows = _sec4_rows()
    if rows is None:
        rep.error(
            "matrix_platform_stale",
            f"docs/PLATFORM-MATRIX.md 里找不到 `{MATRIX_SEC4_HEAD}` 或其后没有表格——"
            f"该表是平台差异的唯一清单，删了它就没有对账依据",
        )
        return
    if not rows:
        rep.error("matrix_platform_stale", "docs/PLATFORM-MATRIX.md §4 表里没有可解析的数据行")
        return
    cfgs = _load_profiles(rep)
    if cfgs is None:
        return

    declared = set()
    for path, is_count, cells, lineno in rows:
        declared.add(path)
        # 门禁输出「改哪里」：§4 的每一行都带原文件行号（七条改造第 6 条）。
        loc = f"docs/PLATFORM-MATRIX.md:{lineno}"

        def _err(code, msg, _loc=loc):
            rep.error(code, msg, where=_loc)

        for k in PROFILE_ORDER:
            raw = cells[k]
            actual = _resolve_path(cfgs[k], path)
            if is_count:
                m = re.match(r"^`(\d+)`$", raw)
                if not m:
                    _err(
                        "matrix_platform_stale",
                        f"§4 的 `{path}` 条数 / {k} 单元格格式不认识：{raw!r}（应为 `数字`）",
                    )
                    continue
                if actual is _MISSING:
                    _err("matrix_platform_stale", f"§4 说 {k} 有 `{path}`，实际不存在")
                elif not isinstance(actual, (list, dict)):
                    _err("matrix_platform_stale", f"§4 说 {k} 的 `{path}` 是条数，实际不是容器")
                elif len(actual) != int(m.group(1)):
                    _err(
                        "matrix_platform_stale",
                        f"§4 说 {k} 的 `{path}` 是 {m.group(1)} 条，实际 {len(actual)} 条",
                    )
                continue
            if raw.strip("*").strip() == "删除":
                if actual is not _MISSING:
                    _err(
                        "matrix_platform_stale",
                        f"§4 说 {k} 的 `{path}` 应删除，实际存在：{actual!r}",
                    )
                continue
            m = re.match(r"^`(.*)`$", raw)
            if not m:
                _err(
                    "matrix_platform_stale",
                    f"§4 的 `{path}` / {k} 单元格格式不认识：{raw!r}"
                    f"（应为 `JSON 字面量` 或 删除；普通说明文字请写在表外）",
                )
                continue
            try:
                expect = json.loads(m.group(1))
            except json.JSONDecodeError:
                # 回退成纯文本比较：表格里写 `sb-template-1.14` 比写 `"sb-template-1.14"` 可读得多，
                # 而写错（如 ture / ture）一样会因不相等而报错，不会静默放过。
                expect = m.group(1)
            if actual is _MISSING:
                _err(
                    "matrix_platform_stale",
                    f"§4 说 {k} 的 `{path}` 是 `{m.group(1)}`，实际该路径不存在",
                )
            elif actual != expect:
                _err(
                    "matrix_platform_stale",
                    f"§4 说 {k} 的 `{path}` 是 `{m.group(1)}`，实际是 {actual!r}",
                )
    if not rep.errors:
        rep.info(
            "matrix_platform_ok",
            f"docs/PLATFORM-MATRIX.md §4 的 {len(rows)} 行与三份 profile 逐项一致",
        )

    # profile_drift：三份配置里凡是出现差异的路径，必须已在 §4 登记
    flats = {k: _flatten(cfgs[k]) for k in PROFILE_ORDER}
    all_paths = sorted(set().union(*(set(f) for f in flats.values())))
    for path in all_paths:
        vals = [flats[k].get(path, _MISSING) for k in PROFILE_ORDER]
        if all(v == vals[0] for v in vals):
            continue
        if any(
            path == d or path.startswith(d + ".") or path.startswith(d + "[")
            or d.startswith(path + ".") or d.startswith(path + "[")
            for d in declared
        ):
            continue
        rep.error(
            "profile_drift",
            f"三份 profile 的 `{path}` 不一致（{vals[0]!r} / {vals[1]!r} / {vals[2]!r}），"
            f"但 docs/PLATFORM-MATRIX.md §4 表里没有登记这一项——"
            f"平台差异必须写进矩阵，否则没人知道它是有意为之还是漏改",
            # 要改的位置是 §4 的**表**（要在那里加一行），不是某个 profile。
            where=f"docs/PLATFORM-MATRIX.md:{MATRIX_SEC4_LINENO}",
        )


def audit_matrix_coverage(rep: Report):
    """templates/groups.json（骨架）与三份 profile（实例）双向对账。

    为什么需要：模板是「该有哪些组」的唯一声明，但此前没有任何检查把它与 profile 挂钩——
    模板加了组、profile 没加（或类型不一致），机器全绿。反过来 profile 里冒出模板
    没登记的组，也没人管。
    """
    tpl_path = ROOT / "templates" / "groups.json"
    if not tpl_path.exists():
        return
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    tpl_groups = {}
    for ob in tpl.get("outbounds") or []:
        if isinstance(ob, dict) and ob.get("type") in ("selector", "urltest"):
            tpl_groups[ob.get("tag")] = ob.get("type")
    cfgs = _load_profiles(rep)
    if cfgs is None:
        return
    for k in PROFILE_ORDER:
        prof_groups = {}
        for ob in cfgs[k].get("outbounds") or []:
            if isinstance(ob, dict) and ob.get("type") in ("selector", "urltest"):
                prof_groups[ob.get("tag")] = ob.get("type")
        # 门禁输出「改哪里」：要改的是**配置**（profile），所以定位到出事的那份 profile。
        cfg_loc = f"profiles/{_PROFILE_DIR}/{k}-lazy.json"
        for tag, typ in tpl_groups.items():
            if tag not in prof_groups:
                rep.error(
                    "template_profile_group_missing",
                    f"{k}-lazy.json 缺模板里的分流组 `{tag}`——"
                    f"templates/groups.json 是本仓库对「该有哪些组」的唯一声明",
                    where=cfg_loc,
                )
            elif prof_groups[tag] != typ:
                rep.error(
                    "template_profile_group_type",
                    f"{k}-lazy.json 的 `{tag}` 是 {prof_groups[tag]}，"
                    f"模板要求 {typ}（组类型是分流行为的开关，不是风格问题）",
                    where=cfg_loc,
                )
        for tag in prof_groups:
            if tag not in tpl_groups:
                rep.error(
                    "profile_group_not_in_template",
                    f"{k}-lazy.json 多了模板没登记的组 `{tag}`——"
                    f"要么把它加进 templates/groups.json，要么删掉",
                    where=cfg_loc,
                )
    if not rep.errors:
        rep.info("matrix_coverage_ok", f"三份 profile 的分流组与模板一致（{len(tpl_groups)} 个组）")


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
# 脚注定义体的开头（`**1**:`）。它一旦出现，本段剩下的行全是脚注散文，不再有功能条目 ——
# 只靠正则逐行过滤会漏：脚注正文里有 `**not used by the open-source server**, and there…`
# 这种以 `*` 开头的续行（L43）。
_CHANGELOG_FOOTNOTE_RE = re.compile(r"^\*{0,2}\d+\*{0,2}\s*:")
# 预发布段（alpha / beta / rc）的版本号形态
_PRERELEASE_RE = re.compile(r"-(?:alpha|beta|rc)\b", re.I)


def _changelog_features(version: str, include_prerelease: bool = True):
    """从 docs/upstream-changelog.md 抽出「>= version」的新功能条目。

    一个函数两种口径，由 `include_prerelease` 选：

    * `include_prerelease=True`（默认，给 `tools/upgrade-check.py` 的升级流程用）——
      **故意包含 alpha / beta / rc 段**：这是提前发现「即将到来的新功能」的唯一途径。
      升级流程跑在计划阶段，属于前瞻，不是发布承诺。
    * `include_prerelease=False`（给 `audit.py` 的门禁用）—— 只认正式版段。依据是本仓库
      只面向正式版（AGENTS.md 铁律 1）。两个理由：
        ① 拿预发布段的条目当门禁，等于按「还没发布的东西」报警；
        ② 预发布段与正式段有大量重复文本，版本号归一化 + 去重后，`1.14.0-beta.5` 独有的条目
           会被算到 `1.14.0` 名下 —— 2014-10 实测：不筛正式段时 1.14.0 名下 102 条，
           其中 53 条（OpenVPN、Cloudflare Origin CA、APK 包、macOS backport …）**根本不在**
           1.14.0 正式版发布说明里（L43）。

    版本号归一化：`1.15.0-alpha.7` → `1.15.0`。

    栏掉纯修补段（`Fixes and improvements`）与脚注定义体，返回去重后的 [(版本, 条目原文), ...]。
    """
    if not CHANGELOG.exists():
        return []
    text = CHANGELOG.read_text(encoding="utf-8")
    seen = set()
    rows = []  # (ver, raw 段标题, feat)
    for m in re.finditer(r"^####\s+([0-9][0-9.\-a-zA-Z]*)\s*$", text, re.M):
        raw = m.group(1)
        base = re.match(r"(\d+\.\d+\.\d+)", raw)
        if not base:
            continue
        ver = base.group(1)
        if not ver_ge(ver, version):
            continue
        end = text.find("\n####", m.end())
        body = text[m.end(): end if end != -1 else len(text)]
        for line in body.splitlines():
            s = line.strip()
            if _CHANGELOG_FOOTNOTE_RE.match(s):
                break  # 脚注区开始了，后面没有功能条目
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
            rows.append((ver, raw, feat))
    if not include_prerelease:
        # 必须按「原始段标题」筛，而不是按归一化后的 ver —— 归一化已经丢掉了
        # `-alpha/-beta/-rc` 信息，那时再筛就晚了。
        rows = [r for r in rows if not _PRERELEASE_RE.search(r[1])]
    return [(v, f) for v, _raw, f in rows]


def coverage_window(matrix):
    """算出「新功能覆盖窗口」的起点版本 —— 它写在矩阵里，是**声明**，不是推导。

    为什么不能直接用锁定版（`singbox_version.txt`）当窗口起点：
    上游每个正式版都会引入新功能，而锁定版**总在往前走**（1.14.3 → 1.15.0 → …）。
    用锁定版当起点，就等于毎次升版都把上一个版本的整段拉进比对窗口：
    升到 1.15.0 那一刻，`1.14.0` 的 49 条会突然变成 49 个 ERROR，
    而人只能事后补一堆只为了关掉 ERROR 的空壳条目（L43）。

    为什么也不能用 `min(since)` 当窗口起点（曾考虑过、已放弃）：
    为了登记 1.14.0 的 `dns.optimistic`（`since: 1.14.0`），`min(since)` 会自动降到 1.14.0，
    同样把 1.14.0 整段拉进来 —— 登记一个历史条目就炸一次，自毁。
    「盘点到了哪一版」是**人工决定**，只能显式声明（`policy.coverage_floor`），
    不能从数据里猜出来。

    语义：`coverage_floor = X` 意思是「X 及之后的正式版，上游每一条新功能都已在矩阵里做过采纳决策」；
    比 X 更早的版本已盘点完毕、不再逐条参与比对（它们的盘点结论在 `docs/evidence/` 下）。
    """
    explicit = (matrix.get("policy") or {}).get("coverage_floor")
    if explicit:
        return explicit, "policy.coverage_floor"
    return None, "（矩阵里没写 policy.coverage_floor，无法判定窗口起点）"


def audit_coverage_window(rep: Report, matrix, target_version: str):
    """覆盖窗口起点与「已盘点版本」的对照校验。

    两个概念很容易被搞反，但它们回答的是两个不同问题：

    * `policy.coverage_floor` —— 「新功能覆盖比对从哪一版之后开始」（半开区间 `(floor, 锁定版]`）。
      它就是「已逐条盘点到此」的那一版；这一版自己的条目已经归档，不重复比对。
    * `policy.inventories` —— 「哪几版已经盘点过」以及**用哪种口径盘的**（可追溯性）。

    关键不变量：`coverage_floor` 必须等于 `inventories` 里最大的那个 version。
    两边不一致就是一起真实事故 —— 声明的盘点结论与实际盘点记录对不上（L43）：

    * floor 比已盘点的高 ⇒ 声称盘过其实没盘，窗口静默变窄，门禁一片绿；
    * floor 比已盘点的低 ⇒ 已盘过的版本会被反复拉回窗口，逼出一堆套话条目。

    只把两者放在一起才能拦下真正的事故：升级到下一个正式版后忘了盘点，
    而 floor 还是老值 —— 此时 changelog 窗口里空无一条，门禁一片绿，人以为没事（L43）。
    所以还要单独查一条：**窗口内每一个「有正式版新功能」的版本都必须在 inventories 里**。
    """
    pol = matrix.get("policy") or {}
    floor, src = coverage_window(matrix)
    if not floor:
        rep.error(
            "coverage_window_missing",
            "矩阵里没写 policy.coverage_floor —— 没有窗口起点就没有「上游加了新功能而仓库不知道」"
            "的检测（L43）。请注意：不能用锁定版当窗口（升版会炸出一大堆历史条目），"
            "也不能用 min(since) 推导（登记一个历史条目就会把窗口拉低），只能显式声明。",
        )
        return
    invs = pol.get("inventories")
    if not isinstance(invs, list) or not invs:
        rep.error(
            "coverage_inventory_missing",
            "矩阵里没有 policy.inventories（已逐个盘点的版本清单）。只用 floor 拦不住「升级了但没盘点」："
            "升级到下一个正式版后 changelog 窗口空无一条（floor 之后的正式版还没发布），"
            "门禁全绿，人以为没事（L43）。",
        )
        return

    tracked = []
    for i, inv in enumerate(invs):
        if not isinstance(inv, dict):
            rep.error(
                "coverage_inventory_missing",
                f"policy.inventories[{i}] 不是对象（应为 {{version, scope, evidence}}）",
            )
            continue
        ver, scope, ev = inv.get("version"), inv.get("scope"), inv.get("evidence")
        if not ver or not scope:
            rep.error(
                "coverage_inventory_missing",
                f"policy.inventories[{i}] 缺 version 或 scope（scope∈per-entry|by-class）",
            )
            continue
        if scope not in ("per-entry", "by-class"):
            rep.error(
                "coverage_inventory_missing",
                f"policy.inventories[{i}].version={ver} 的 scope={scope!r} 不合法"
                f"（per-entry=逐条登记条目 / by-class=按类归档，结论落在 evidence 文档里）",
            )
            continue
        tracked.append(ver)
        if scope == "by-class":
            if not ev:
                rep.error(
                    "coverage_inventory_doc_missing",
                    f"policy.inventories 里 {ver} 是 by-class（没有逐条条目，结论只在文档里），"
                    f"必须写 evidence 指向盘点文档",
                )
            elif not (ROOT / ev).exists():
                rep.error(
                    "coverage_inventory_doc_missing",
                    f"policy.inventories 里 {ver} 的 evidence={ev!r} 文件不存在",
                )

    # ①② floor 与盘点记录必须互相对得上（见 docstring：两边不一致都是事故）
    if tracked:
        top = max(tracked, key=parse_version)
        if parse_version(floor) > parse_version(top):
            rep.warn(
                "coverage_floor_stale",
                f"policy.coverage_floor={floor} 高于 inventories 里已盘点的最高版 {top}（{src}）—— "
                f"floor 的语义是「已盘点到此」，它不能高于已有盘点记录的版本："
                f"否则就是声称盘过而未盘，窗口静默变窄（L43）",
            )
        elif parse_version(floor) < parse_version(top):
            rep.error(
                "coverage_inventory_missing",
                f"policy.coverage_floor={floor} 低于 inventories 里已盘点的最高版 {top} —— "
                f"已盘过的版本会被反复拉回比对窗口，逼出一堆只为关掉 ERROR 的套话条目（L43）",
            )

    # ③ 拦「升级了但没盘点」：窗口 (floor, 锁定版] 里每一版**有正式版新功能**的都得在 inventories 里。
    #     只看「有 feature 的版本」而不看每一个版本，是因为 1.14.1/1.14.2 这类纯修补版
    #     本来就没有可盘点的东西，要求为它们建一条记录是形式主义。
    have_feat = {v for v, _f in _changelog_features(floor, include_prerelease=False) if v != floor}
    missing = sorted(v for v in have_feat if not any(parse_version(v) == parse_version(t) for t in tracked))
    if missing:
        rep.error(
            "coverage_inventory_missing",
            f"覆盖窗口 ({floor}, {target_version}] 里这些正式版有新功能但没盘点记录："
            f"{'、'.join(missing)}。升级流程漏了盘点那一步 —— changelog 窗口比对此时可能恰好是空的，"
            f"门禁一片绿，人以为没事（L43）。要么补盘点记录，要么把 policy.coverage_floor 往前推。",
        )

    if rep.ok():
        rep.info(
            "coverage_window_ok",
            f"覆盖窗口 ({floor}, {target_version}]；起点 {floor}（{src}）；已盘点版本："
            + "，".join(
                f"{i.get('version')}({i.get('scope')})" for i in invs if isinstance(i, dict) and i.get("version")
            ),
        )


def audit_new_features(rep: Report, matrix, target_version: str):
    """新功能采纳台账校验（仓库级，每份配置都跑一次之外单独跑一次）。

    四道检查：
      1. 数据完整性：kind=new 必须有合法 adopt + 非空 reason；有 path 的还必须有 expect。
      2. 未卜先知：decide_by 已过期而 adopt 仍缺失/非法 → ERROR（不能靠「忘了」来默认不启用）。
      3. 覆盖底盘：上游 changelog 里 **>= 覆盖窗口起点** 的正式版新功能条目，必须被某条 kind=new
         的 keywords 覆盖；否则 ERROR —— 防止「上游加了新功能，仓库浑然不知」。
         窗口起点由 `coverage_window()` 给出（不是锁定版，见该函数注释与 L43）。
      4. follow_up：条目可以登记「迁移时还需重新决策的参数」（如换 sing-tun 栈后 mtu 该取多少）。
         这类待办的判据在上游正式版文档里、不在配置里，静态检查判定不了对错，
         所以每次跑都打一条 INFO 提醒，避免它只活在某段散文里（L26）。
    """
    news = [e for e in matrix.get("entries", []) if e.get("kind") == "new"]
    if not news:
        rep.error(
            "new_feature_without_adoption",
            "version-matrix.json 里没有任何 kind=\"new\" 条目 —— 新功能采纳机制等于不存在"
            "（上游加了什么功能，仓库不会知道）",
        )
        return

    # 覆盖窗口起点：先算出来，3b) 与第 5) 步都要用。
    floor, floor_src = coverage_window(matrix)

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
        # 3b) 落在「已盘点版本」里的条目（since <= 覆盖窗口起点）必须挂一份成文的盘点依据。
        #     为什么：能在窗口之外新增条目，就说明在那个版本上做了一次追加盘点；
        #     也可能本轮盘点就把该版本归档并登记了其中几条。两种情况的结论都必须落在文档里，
        #     否则「已盘点」就是一句无凭无据的话（L43）。
        #     连 `since == floor` 也算：起点那一版自己不再进入比对窗口，
        #     它的盘点是靠文档而不是靠逐条比对保证的。
        since, floor0 = e.get("since"), (floor or "")
        if since and floor0 and parse_version(since) <= parse_version(floor0):
            inv = e.get("inventory")
            if not inv:
                rep.error(
                    "historical_feature_without_inventory",
                    f"[{eid}] since={since} 不在覆盖窗口内（起点 {floor0} 那一版已盘点过），"
                    f"属于已归档版本的条目，"
                    f"必须写 inventory 指向盘点文档（如 docs/evidence/…-features-{since}-inventory.md）",
                )
            else:
                ip = ROOT / inv
                if not ip.exists():
                    rep.error(
                        "inventory_doc_missing",
                        f"[{eid}] inventory={inv!r} 指向的文件不存在",
                    )
                else:
                    body = ip.read_text(encoding="utf-8")
                    if eid not in body:
                        rep.error(
                            "inventory_doc_unlinked",
                            f"[{eid}] 盘点文档 {inv} 里没有提到这个条目 id —— 文档与矩阵没对上"
                            f"（盘点结论必须能反向查到条目）",
                        )
        # 4) decide_by 过期仍未决策 → 不能靠「忘了」蒙混过关
        db = e.get("decide_by")
        if db and not ver_ge(db, target_version):
            rep.error(
                "new_feature_decision_overdue",
                f"[{eid}] 决策截止版本 {db} 已到（当前锁定 {target_version}）仍未落地："
                f"{e.get('title', '')} —— 请补上 adopt/reason，或把 decide_by 往后挪并说明原因",
            )

        # 4b) follow_up：迁移时还需重新决策的参数。这类待办的判据不在配置里（在上游正式版文档里），
        #     静态检查无法判定对错，所以只能「提醒」而不能「校验」—— 但提醒必须每次都出现，
        #     否则「读不读到」就取决于人恰好有没有翻到那条 reason（L26）。
        follow = e.get("follow_up") or []
        if follow:
            items = "；".join(
                (
                    f.get("todo", "")
                    + (f"（触发：{f['when']}）" if isinstance(f, dict) and f.get("when") else "")
                )
                if isinstance(f, dict)
                else str(f)
                for f in follow
            )
            rep.info(
                "matrix_follow_up_reminder",
                f"[{eid}] 迁移时还有附加待办（判据不在配置里，无法校验，只能提醒）：{items}",
            )

        # 4c) follow_up 自身必须可被渲染 —— `tools/gen-docs.py` 会直接打印它的内容，
        #     写成裸 dict/list 就得到一行 Python repr 泄漏到给用户看的 `docs/VERSION-MATRIX.md`。
        #     先用 list 判定，再逐个元素查 dict 里有没有 todo（L43）。
        if follow and not isinstance(follow, list):
            rep.error(
                "follow_up_invalid",
                f"[{eid}] follow_up 必须是数组（元素 = 一句待办字符串，或 {{todo, when}} 对象），"
                f"现在是 {type(follow).__name__}",
            )
        else:
            for i, f in enumerate(follow):
                if isinstance(f, dict):
                    if not str(f.get("todo") or "").strip():
                        rep.error(
                            "follow_up_invalid",
                            f"[{eid}] follow_up[{i}] 是对象但没写 todo —— docs/VERSION-MATRIX.md 会印出一行空白",
                        )
                elif not isinstance(f, str) or not f.strip():
                    rep.error(
                        "follow_up_invalid",
                        f"[{eid}] follow_up[{i}]={f!r} 既不是字符串也不是含 todo 的对象",
                    )

        # 4d) 矩阵条目必需字段：`_schema` 里声明了这几个字段，但声明不产生任何约束 ——
        #     缺了 id 的条目会以 `[?]` 出现在报错里（无法定位），缺了 kind 的条目会被静默跳过。
        if not str(e.get("id") or "").strip():
            rep.error(
                "matrix_entry_missing_field",
                f"kind=new 的第 {news.index(e)} 条条目没有 id —— 所有检查都会退化成 `[?]`，定位不了",
            )
        for req in ("title", "reason"):
            if not str(e.get(req) or "").strip():
                rep.error("matrix_entry_missing_field", f"[{eid}] kind=new 缺必填字段 {req}")
        if e.get("kind") != "new":
            rep.error(
                "matrix_entry_missing_field",
                f"[{eid}] 出现在 kind=new 集合里但 kind={e.get('kind')!r}",
            )

    # 5) changelog 覆盖比对（窗口本身的合法性由 `audit_coverage_window` 单独校验）
    if not floor:
        return  # 没窗口就没得比，且已由 audit_coverage_window 报错
    # ⚠️ 窗口是**半开区间** (coverage_floor, target_version]：
    #    语义是「已盘点到此为止」，即 floor 这一版已经盘过了、不再重复比对。
    #    若写成 >= floor，登一条 since=1.14.0 的条目就会把 1.14.0 的 49 条重新拉进窗口，
    #    而那 49 条已归档在 docs/evidence/…-features-1.14.0-inventory.md 里（L43）。
    # 门禁只认正式版段；`tools/upgrade-check.py` 用同一个函数但保留预发布段（前瞻）。
    feats = [x for x in _changelog_features(floor, include_prerelease=False) if x[0] != floor]
    if not feats:
        rep.info(
            "coverage_window_empty",
            f"新功能覆盖窗口 ({floor}, {target_version}] 里没有正式版新功能条目（"
            f"1.14.1 / 1.14.2 / 1.14.3 都只有修补，1.15.0 尚未发布正式版）。"
            f"注意：这**不等于**本次没查 —— 它只是说明窗口本身是空的；"
            f"窗口里一旦出现条目就会被逐条比对（L43）。",
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
            f"上游 changelog 里 ({floor}, {target_version}]（覆盖窗口，起点 {floor_src}）的正式版新功能有 "
            f"{len(uncovered)} 条没被矩阵覆盖（keywords 比对）："
            + "；".join(f"{v} {f}" for v, f in uncovered[:6])
            + (" …" if len(uncovered) > 6 else ""),
        )
    else:
        rep.info(
            "new_feature_covered",
            f"上游 changelog 中 ({floor}, {target_version}]（{floor_src}）的正式版新功能共 {len(feats)} 条，"
            f"全部被 {len(news)} 条 kind=new 条目的 keywords 覆盖"
            f"（另有 {len([e for e in news if e.get('since') and parse_version(e['since']) <= parse_version(floor)])} "
            f"条属于已盘点过的版本，不参与比对）",
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
LESSON_HEAD_RE = re.compile(r"^##\s+L(\d+)\s+(.+)$", re.M)
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
    text = LESSONS.read_text(encoding="utf-8")
    heads = list(LESSON_HEAD_RE.finditer(text))
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[head.end() : end]
        if not re.search(r"^\*\*门禁\*\*：", body, re.M):
            rep.error(
                "lesson_missing_gate_line",
                f"docs/LESSONS.md 的 L{head.group(1)}（{head.group(2).strip()}）没有 `**门禁**：` 行——"
                f"台账声明了机读格式，缺这一行等于这条教训没有门禁归属，也没有就写「无」",
            )
        # 五要素的「标题存在性」—— 机器只能校“有没有这一段”，校不了“写得对不对”。
        # 这是 L27 的对策：文件头声称「每条都必须有五要素」，而 L7–L15 当时大面积缺失，
        # 因为头部的声明从来没人验。至少把可机校的那一半变成事实。
        missing = [
            name
            for name, pat in (
                ("根因", r"^\*\*根因"),
                ("为什么没被拦住", r"^\*\*为什么"),
                ("修法", r"^\*\*修法"),
            )
            if not re.search(pat, body, re.M)
        ]
        if missing:
            rep.error(
                "lesson_missing_element",
                f"docs/LESSONS.md 的 L{head.group(1)}（{head.group(2).strip()}）缺五要素中的："
                f"{'、'.join(missing)}——文件头声明每条都必须有 现象/根因/为什么没被拦住/修法/门禁，"
                f"标题缺哪一段就补哪一段（机器只能校段落是否存在）",
            )
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
    # geoip-cn 归属实测用到的两个大陆 DNS（LESSONS L28 / D13 的前置论证）
    "117.50.10.10",     # 下一代互联网国家工程中心公共 DNS
    "180.184.1.1",      # 字节跳动公共 DNS
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
# ⚠️ **必须带显式时区偏移**（如 `+08:00`）。写成不带偏移的 `"YYYY-MM-DD HH:MM:SS"`，
#    git 会按**各机器本地时区**解释 —— 本机 +0800、CI 是 UTC，同一份门禁会得到
#    相差 8 小时的两个窗口（本地扫 6 个提交、CI 扫 0 个），结论自然不一致。实测踩过，见 L30。
LEAK_SCAN_START_DATE = "2026-10-12T20:00:00+08:00"


def audit_template_text(rep: Report):
    """校 templates/groups.json 的 `_rules_of_thumb` 文字。

    这段文字**没有任何工具消费**（纯人手维护），因此是全文最容易过期的部分：
    铁律 14 已在 L18 更正为「resolve 紧跟 hijack-dns」，而这里的摘录长期仍写「末尾」，
    等于在“固定骨架”里留了一句反话。改成可机检的形式：
      · 必须有一条同时提到 `resolve` 与 `hijack-dns`（否则无人能看出位置约束）；
      · 不许出现「…末尾…」这种规定式说法。

    判定“过期”要看**语义方向**，不能只看关键词：现文写的是
    「…必须在 hijack-dns 之后…（放末尾等于没放）」，包含“末尾”二字却是在**否定**它，
    不能误判。故只在两种情形下报错：① 命中历史上的规定式短语；
    ② 提到 resolve 与末尾、却完全不提 hijack-dns（= 双不出现的旧口径）。
    """
    path = ROOT / "templates" / "groups.json"
    if not path.exists():
        return
    try:
        tpl = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    tips = tpl.get("_rules_of_thumb") or []
    stale_phrases = ("末尾还要有", "末尾必须有", "末尾追加", "末尾加", "放到末尾", "放在末尾")
    for tip in tips:
        hit = next((p for p in stale_phrases if p in tip), None)
        if hit is None and "resolve" in tip and "末尾" in tip and "hijack-dns" not in tip:
            hit = "resolve + 末尾（且未提 hijack-dns）"
        if hit:
            rep.error(
                "template_thumb_stale",
                f"templates/groups.json 的 _rules_of_thumb 仍写「{hit}」式的 resolve 位置——"
                "hijack-dns 之后的第一个 route/reject 一命中就 break match，末尾等于没放（docs/LESSONS.md L18）",
            )
    if not any("resolve" in tip and "hijack-dns" in tip for tip in tips):
        rep.error(
            "template_thumb_stale",
            "templates/groups.json 的 _rules_of_thumb 缺一条说明 resolve 位置的条目——"
            "这段文字无人消费，必须有机器看得懂的约束，否则下次又会被改回错的口径",
        )


def _tracked_files():
    """返回「仓库里应当被文本级门禁扫描的文件」清单。

    已跟踪 + 尚未 add 的新文件：只看 `git ls-files` 会漏掉“刚写好、还没 add”的新文档，
    造成本地绿、CI 红（L29）。故两个来源都要。
    调用方自己按后缀/前缀过滤（这里不预筛，保留全集才好排版）。
    """
    files, seen = [], set()
    for args in (["git", "ls-files"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(
                args, cwd=str(ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for f in out.splitlines():
            if f.strip() and f not in seen:
                seen.add(f)
                files.append(f)
    return files


def _is_negative_fixture(path: str) -> bool:
    """这个文件是不是「专门用旧名来验门禁」的负向样本。

    判定靠**文件名**而不是目录，因为仓库的负向脚本有两种合法位置：
      · `tools/negtest.py`  —— 常驻回归套件；
      · `local/neg_*.py`、`local/*_negtest*` —— 一次性排查脚本（`local/` 不进仓库）。
    用词根 `neg` + `test` 两处都覆盖，同时避开 `tools/audit.py` 的 framework 文件。
    """
    name = path.rsplit("/", 1)[-1].lower()
    return name.startswith("neg") or "_neg" in name or "negtest" in name


def audit_doc_group_names(rep: Report):
    """扫全仓散文，拦「旧组名残留」。

    为什么需要它：组改名（m07194）的真实成本 98% 在散文，不在配置——
    JSON 引用位由 profile_drift / dangling_ref 一族盯着，而 19 个文件里
    240 处 Markdown/注释里的组名**一处门禁都没有**。当时我手写了两版正则仍漏掉
    `templates/groups.json:46` 的裸 `Proxy`，只能靠人肉 grep 逐轮找漏（铁律 20 整改）。

    判定必须区分三种「看起来像旧名」的东西，误报比漏报更贵：
      ㊀ 真·旧名残留  → 报错，要求改成规范名。
      ㊁ 必须保留旧名的位置（下列豁免） → 放行：
         · 「旧名 / 原话 / 改名之前」等**历史叙述**上下文——改了就篡改事实；
         · 门禁自己的**反向检测字面量**（`legacy = {"Proxy","AI","AD"}`）——
           它本来就是靠旧名来发现漏改，改成规范名就变成永远不响的死检查；
         · `Proxy` 出现在 `NaiveProxy` / `OpenAI` 之类的**专有名词**里。
      ㊂ 「AI」= 人工智能/助手（`给 AI 读的入口`、`任何人或任何 AI`）
         → **根本不是组名**，绝不能改。

    依赖的是「组名已是 emoji 形态」这个不变式：规范名 `🚀 Proxy` 里仍含 `Proxy`，
    所以判「旧名」必须要求前面**没有 emoji 前缀**，不能只匹配裸词。
    """
    legacy = {"Proxy": GROUP_PROXY, "AI": GROUP_AI, "AD": GROUP_AD}
    # ㊁ 豁免：这些上下文里出现的旧名是**正确的**，改了反而错
    EXEMPT = (
        "旧名", "原名", "原话", "改名", "更名", "之前叫", "曾经",
        "detour not found", "not found:", "legacy", "保留名", "历史",
        # 「由 `Proxy` / `AI` / `AD` 改成 …」式叙述：描述改名本身，必须保留旧名。
        "由 `Proxy`", "由 `AI`", "由 `AD`", "tag 由", "的 tag 由",
        # 「自己造成的悬空引用」类复盘：说的是事故发生时的旧名。
        "仍指向", "已不存在", "不存在的 `", "早期", "当时",
        # 「旧策略组选择会失效」：说的是客户端里残留的旧选择。
        "旧策略组", "手动选过",
    )
    # 反引号包裹的**单个**裸组名（`` `AD` ``）是引用位还是叙述，靠上面 EXEMPT 区分。
    # 这条不变式保证不会被误用：“🚀 AD” 不是合法规范名（emoji 与名字必须匹配）。
    # ㊂ 「AI = 人工智能」判据：紧邻的搭配词（「给 AI 读的入口」「AI 类站点」「AI 助手」）
    AI_AS_TOOL = re.compile(
        r"(?:给|任何|或|让|由|是|本|个|读|入口|生成|助手|模型|来做写协流程拿到负责根据|类|的入口)"
    )
    pat = re.compile(r"(?<![A-Za-z0-9_])(Proxy|AI|AD)(?![A-Za-z0-9_])")
    # ④ 只有「配置引用位」才报错。
    #    理由：散文里用短称（「🚫 AD 组」「🚫 AD 里的 direct」）是可读的，强行全写成带 emoji
    #    只会变成噪音；而真正造成 L35 事故的是**配置引用位**——
    #    「jinx-ads → 🚫 AD」「outbound 🚫 AD」「selector[🚫 AD]」「`🚫 AD`」这些地方，
    #    下一个读者会照抄进配置，留旧名就等于埋悬空引用。
    CONFIG_REF = re.compile(
        r"(?:→|->|=>|outbound\s*$|outbounds|\btag\b|detour|selector\[|route\(|final\s*$|\bdefault\b)"
    )

    # 4  「历史台账」豁免：docs/LESSONS.md 与 docs/DECISIONS.md 是**追加型历史记录**，
    #   它们必须能写下旧名——「用户原话：给 Proxy 改名为🚀 Proxy」一旦把旧名改掉，
    #   记载就变成假的；复盘条目里「早期 AI 实现成 selector(outbounds=[Proxy])」同理。
    #   所以门禁只管**活文档**（下一个人会照着写新配置的那些）。
    #   代价：历史文件里新写的旧名不会被机器抓到——可接受，因为那里本来就允许旧名。
    HISTORICAL = {"docs/LESSONS.md", "docs/DECISIONS.md"}
    files = [
        f for f in _tracked_files()
        if f.endswith((".md", ".json", ".py", ".sh", ".yml", ".yaml"))
        and not f.startswith(("docs/upstream-", "archive/", "docs/evidence/"))
        and f not in HISTORICAL
        and f != "docs/schema.json"
    ]
    found = []
    for f in files:
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in pat.finditer(text):
            name = m.group(1)
            # 规范名是「emoji + 一个 ASCII 空格 + 名字」，所以向前看 2 个字符：
            # 只看 1 个字符会漏掉那个空格，把 `🚀 Proxy` 里的 `Proxy` 误判成旧名。
            if "🚀" in text[max(0, m.start() - 2): m.start()] \
                    or "🤖" in text[max(0, m.start() - 2): m.start()] \
                    or "🚫" in text[max(0, m.start() - 2): m.start()]:
                continue
            ctx = text[max(0, m.start() - 60): m.end() + 60]
            context = text[max(0, m.start() - 60): m.end()].replace("\n", " ")
            after = text[m.end(): m.end() + 12]
            # 专有名词：NaiveProxy / OpenAI / ADGuard 等
            if re.search(r"(?:Naive|Open|Ad)Proxy|##\s*AD|\.ad\b", ctx):
                continue
            # 「AI = 人工智能」：仅当没有组名语境的搭配
            if name == "AI" and AI_AS_TOOL.search(context[-10:]) and not re.match(
                r"\s*(?:分流)?组", after
            ):
                continue
            # ㊁ 历史叙述上下文豁免
            if any(k in ctx for k in EXEMPT):
                continue
            # ④ 只报配置引用位；散文短称不报（见 CONFIG_REF 注释）
            #    ⚠️ 必须拿 `before` 去匹配，不能把名字拼上去再匹配：
            #    `outbound\s*$` / `final\s*$` 这类锚定行尾的模式一旦拼上名字就永远不匹配。
            #    （第一版正是这么写的，落点位置被改回旧名时静默放过 —— 反向自测才知道。）
            before = text[max(0, m.start() - 30): m.start()]
            is_config_ref = bool(CONFIG_REF.search(before))
            # 「`🚫 AD`」这种反引号包裹的单组名（无 emoji）也算引用位
            if before.endswith("`") and after.startswith("`"):
                is_config_ref = True
            # 反向检测字面量（`{"Proxy", "AI", "AD"}`）自带旧名——那正是它发现漏改的依据，
            # 改成规范名就变成永远不响的死检查。
            #   豁免按**「谁需要旧名」**判定，而不是按文件名硬编码：
            #   ① 本文件（audit.py）自己持有 legacy 映射与反向字面量；
            #   ② 任何专门造坏样本的文件（`tools/negtest.py`、`local/` 下的脚本）——
            #      它们的**本职就是写出错误写法**，用规范名反而验不了门禁。
            #      （negtest.py 上线后立刻被本门禁拦下，就是这个豁免缺失导致的；
            #        若按文件名硬编码 `tools/negtest.py`，下一个负向脚本又会重踩。）
            if f == "tools/audit.py" and re.search(r'\{\s*"Proxy"\s*,\s*"AI"\s*,\s*"AD"\s*\}', ctx):
                continue
            if _is_negative_fixture(f):
                continue
            if not is_config_ref:
                continue
            found.append((f, text[: m.start()].count("\n") + 1, name, context.strip()[-70:]))

    if not found:
        rep.info(
            "doc_group_name_clean",
            "全仓散文没有旧组名残留（🚀 Proxy / 🤖 AI / 🚫 AD 是唯一规范写法）",
        )
        return
    for f, line, name, ctx in found[:40]:
        rep.error(
            "doc_group_name_stale",
            f'{f}:{line} 出现旧组名 {name!r}（规范名是 {legacy[name]!r}）…{ctx}…'
            "——组 tag 是 route.final / route.rules[].outbound / dns.servers[].detour 的引用目标，"
            "散文里留旧名会让下一个读它的人照着改出悬空引用（铁律 20）",
            where=f"{f}:{line}",
        )
    if len(found) > 40:
        rep.error(
            "doc_group_name_stale",
            f"另有 {len(found) - 40} 处旧组名（共 {len(found)} 处），已截断显示",
        )


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

    # LEAK_SCAN_START_DATE 必须带显式时区偏移（对应 L30 那次真实事故）
    # 不带偏移时 git 按各机器本地时区解释：本机 +0800 扫到 6 个提交、CI(UTC) 扫到 0 个，
    # 同一份门禁给出相反的结论。这类“环境相关”的常量必须把自己钉死。
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$", LEAK_SCAN_START_DATE):
        rep.error(
            "tool_selftest_failed",
            f"LEAK_SCAN_START_DATE 必须写成带显式时区偏移的 ISO 形式（如 2026-10-12T20:00:00+08:00），"
            f"当前是 {LEAK_SCAN_START_DATE!r}。不带偏移会被各机器按本地时区解释，"
            f"本地与 CI 得到相差数小时的窗口，详见 docs/LESSONS.md L30",
        )


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

    范围：`git ls-files` 的全部文件（含 docs/）+ **尚未 add 的新文件** + commit message。
    第二项是必须的：`git ls-files` 只看已跟踪文件，所以“刚写好、还没 `git add`”的新文档
    完全在盲区里 —— 本地跑 audit 是绿的，推送后 CI 第一次扫到它就红。这个坑真实发生过（L29）。
    commit message 也算“写进仓库的文本” —— 它同样公开、同样推不回来。
    但 commit message 只扫 LEAK_SCAN_START_DATE 之后的：历史里已知有泄漏，
    而“把要拦的 SHA 写进仓库”会重新泄漏一次（见该常量的说明）。
    `local/` 不跟踪、按规定就允许放真实节点，故跳过。
    豁免：- RFC 私有 / 回环 / 文档专用 / 组播 等范围
          - PUBLIC_IP_WHITELIST 里人工审阅过的公网 IP
    """
    # 已跟踪 + 未跟踪但未被 ignore 的：后者覆盖“刚写好、还没 git add”的新文件。
    # 只看 ls-files 会漏掉它们 —— 本地绿、CI 红，正是 L29 的成因。
    files = []
    seen = set()
    for args in (["git", "ls-files"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(
                args, cwd=str(ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            ).stdout
        except (OSError, subprocess.SubprocessError) as ex:
            rep.info("skip_check_template", f"无法取得 git 文件列表（{' '.join(args)}），跳过防泄漏扫查：{ex}")
            return
        for f in out.splitlines():
            if f.strip() and f not in seen:
                seen.add(f)
                files.append(f)
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
    # 本机私有登记（local/ 在 .gitignore 里，所以绝对路径不会进仓库；见 L25）。
    # 与 tools/check-all.sh 的解析顺序保持一致：两边行为不同会让人以为「一边能跑一边不能」。
    local_bin = LOCAL / ".singbox-bin"
    if local_bin.is_file():
        first = local_bin.read_text(encoding="utf-8", errors="replace").splitlines()
        if first and first[0].strip() and Path(first[0].strip()).exists():
            return first[0].strip()
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
        for lv, code, msg, where in lessons_rep.items:
            print(f"[{lv[0]}] docs/LESSONS.md: {msg}" + (f"   ← {where}" if where else ""))
    if not lessons_rep.ok():
        failed = True

    # 新功能采纳台账是仓库级校验（不依赖具体配置），单独跑一次
    newfeat_rep = Report("docs/version-matrix.json")
    audit_new_features(newfeat_rep, matrix, version)
    if newfeat_rep.items and not args.json:
        for lv, code, msg, where in newfeat_rep.items:
            print(f"[{lv[0]}] docs/version-matrix.json: {msg}" + (f"   ← {where}" if where else ""))
    if not newfeat_rep.ok():
        failed = True

    # 决策记录 ↔ 矩阵双向校验（同上，与具体配置无关）
    decisions_rep = Report("docs/DECISIONS.md")
    audit_decisions(decisions_rep, matrix, version)
    if decisions_rep.items and not args.json:
        for lv, code, msg, where in decisions_rep.items:
            print(f"[{lv[0]}] docs/DECISIONS.md: {msg}")
    if not decisions_rep.ok():
        failed = True

    # 新功能覆盖窗口：floor 与「已盘点版本」必须对得上
    covwin_rep = Report("docs/version-matrix.json（覆盖窗口）")
    audit_coverage_window(covwin_rep, matrix, version)
    if covwin_rep.items and not args.json:
        for lv, code, msg, where in covwin_rep.items:
            print(f"[{lv[0]}] 覆盖窗口: {msg}" + (f"   ← {where}" if where else ""))
    if not covwin_rep.ok():
        failed = True

    # 防泄漏扫查（同上，与具体配置无关）：被跟踪文件里不许有未审阅的公网 IP
    redact_rep = Report("仓库防泄漏扫查（git ls-files）")
    audit_redaction(redact_rep)
    if redact_rep.items and not args.json:
        for lv, code, msg, where in redact_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not redact_rep.ok():
        failed = True

    # 工具自检（同上，与具体配置无关）：工具也是代码，语法错与不变量失效同样要拦。
    # 只管 ERROR 不管 WARN：本机没有 sing-box 时 --run 会降级为 WARN，那是预期行为。
    tools_rep = Report("tools/*.py 自检")
    audit_tools(tools_rep)
    if tools_rep.items and not args.json:
        for lv, code, msg, where in tools_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not tools_rep.ok():
        failed = True

    # 模板文字（同上）：`_rules_of_thumb` 是全文唯一无人消费的部分，最易过期。
    tpl_rep = Report("templates/groups.json 文字")
    audit_template_text(tpl_rep)
    if tpl_rep.items and not args.json:
        for lv, code, msg, where in tpl_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not tpl_rep.ok():
        failed = True

    # 散文里的旧组名残留（仓库级）：见 audit_doc_group_names 的 docstring。
    # 组改名的真实成本 98% 在散文（240 处 / 19 个文件），此前零门禁。
    doc_rep = Report("全仓散文的组名")
    audit_doc_group_names(doc_rep)
    if doc_rep.items and not args.json:
        for lv, code, msg, where in doc_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not doc_rep.ok():
        failed = True

    # 平台差异矩阵对账（仓库级）：PLATFORM-MATRIX.md §4 ⟺ 三份 profile 的实际值。
    plat_rep = Report("docs/PLATFORM-MATRIX.md §4")
    audit_matrix_platform(plat_rep)
    if plat_rep.items and not args.json:
        for lv, code, msg, where in plat_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not plat_rep.ok():
        failed = True

    # 模板 ⟺ profile 的组一致性（仓库级）：模板声明该有哪些组，profile 必须照做。
    cov_rep = Report("templates/groups.json ⟺ profiles")
    audit_matrix_coverage(cov_rep)
    if cov_rep.items and not args.json:
        for lv, code, msg, where in cov_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not cov_rep.ok():
        failed = True

    # 矩阵 path 与内核「字段实际是否存在」的交叉对账（仓库级、与具体配置无关）。
    # 这是「内核升级导致门禁失效」的检测器：矩阵与内核任何一边变了，这里都会响。
    probe_rep = Report("docs/version-matrix.json path ⟺ 内核")
    audit_matrix_paths(probe_rep, matrix, version, None if args.no_check else find_singbox(args.singbox))
    if probe_rep.items and not args.json:
        for lv, code, msg, where in probe_rep.items:
            print(f"[{lv[0]}] {msg}" + (f"   ← {where}" if where else ""))
    if not probe_rep.ok():
        failed = True

    if args.files:
        # 显式传了文件就只查这些；仓库自检（无参数）时连带把 templates/groups.json
        # 送进同一套检查流程，避免出现“模板自己违规却没人管”。
        targets = [Path(f) for f in args.files]
    else:
        # ⚠️ 扫描范围必须等于「真实会被使用的配置」的集合，而不是「仓库里被跟踪的配置」。
        # L35 的根因就是这里：local/ 下四份真机运行配置没有被扫，
        # 于是组改名漏改 dns.servers[].detour 时，所有门禁全绿、真机才炸。
        # local/ 在 .gitignore 里、允许放真实节点，故只跳过它不适用的两项：
        #   ① 防泄漏扫查（audit_redaction 自己按 startswith("local/") 跳过）
        #   ② 占位域名检查（audit_repo_rules 自己按 rel.parts[0]=="profiles" 隔离）
        # 引用完整性、平台能力、组一致性、DNS 广告层顺序等**一律照查**。
        targets = sorted(PROFILES.rglob("*.json")) + [ROOT / "templates" / "groups.json"]
        if LOCAL.is_dir():
            targets += sorted(LOCAL.glob("*.json"))

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

        skipped = audit_matrix(cfg, rep, matrix, version, platforms, is_template=is_template)
        audit_platform_caps(cfg, rep, platforms)
        audit_repo_rules(cfg, rep)
        audit_loopback_guard(cfg, rep)
        if is_template:
            audit_template(rep)
        if skipped:
            rep.info(
                "template_new_present_skipped",
                f"这是骨架模板，已跳过 {len(skipped)} 条 kind=new 的 expect=present 断言"
                f"（骨架只有出站与策略组，不含 dns / inbounds / route 全量字段）："
                + "，".join(skipped),
            )
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
        (covwin_rep, {"coverage-window"}),
        (decisions_rep, {"decisions"}),
        (redact_rep, {"redaction"}),
        (tools_rep, {"tools"}),
        (tpl_rep, {"template-text"}),
        (plat_rep, {"platform-matrix"}),
        (cov_rep, {"template-coverage"}),
        (probe_rep, {"matrix-paths"}),
        (doc_rep, {"doc-group-names"}),
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
                            {"level": lv, "code": c, "message": m,
                             **({"where": w} if w else {})}
                            for lv, c, m, w in r.items
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
            for lv, c, m, w in r.items:
                mark = {"ERROR": "[E]", "WARN": "[W]", "INFO": "[i]"}[lv]
                print(f"  {mark} {m}" + (f"   ← {w}" if w else ""))
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
