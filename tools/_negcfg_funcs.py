# -*- coding: utf-8 -*-
"""_negcfg_funcs.py —— 单文件配置类（`single` 作用域）门禁的破坏函数

2026-10-13 补齐覆盖率时新增。此前 115 个门禁里只有 29 个有用例覆盖，
其中「单文件配置类」这一大批（安全 / 引用完整性 / 模板组结构 / 路由DNS / 平台字段）
**一个用例都没有** —— 门禁写了，但没人证明它会响。

## 每个函数的破坏力都实测过

不是照着 code 名猜一个「看起来会坏」的改法：每个函数都先用
`audit.py <样本> --json` 跑一遍，确认**确实报出**目标 code 才登记。
（教训：我自己先猜错了两次 —— `ruleset_format` 的靶心是「删 format **且** url 不以
`.srs/.json` 结尾」的组合，单删 format 不会响；`resolve_not_first` 的靶心是
「resolve 排到第一个 route/reject **之后**」，插到 hijack-dns 之前反倒不算。）

## 为什么单独成文件

`negtest.py` 已经很长，而且这个文件用 `Write` 落盘、不经过 shell / JSON 的转义层 ——
上一批同类内容在传递时被转义层改坏过三次，每次都要回滚重来。
"""


# ── 取节点的辅助 ────────────────────────────────────────────────────
def _grp(cfg, tag):
    """按 tag 取一个策略组出站。"""
    for o in cfg.get("outbounds", []):
        if isinstance(o, dict) and o.get("tag") == tag:
            return o
    raise KeyError(tag)


def _first_rs(cfg, i=0):
    """取第 i 个 rule_set。本仓 [0] 是远程 binary 集，
    覆盖 http_client / format / url 这几类判据都靠它。"""
    return cfg["route"]["rule_set"][i]


# ── A 安全 / 防泄漏 ─────────────────────────────────────────────────
def m_cache_path_parent(cfg):
    """cache_file.path 含 '..' —— sing-box 不建父目录，启动即 FATAL。"""
    cfg["experimental"]["cache_file"]["path"] = "../cache/cache.db"


def m_cache_path_abs(cfg):
    """cache_file.path 是绝对路径 —— 三平台工作目录不同，迁移必炸（WARN 级）。"""
    cfg["experimental"]["cache_file"]["path"] = "C:/abs/path/cache.db"


# ── B 引用完整性 ────────────────────────────────────────────────────
def m_ruleset_download_detour(cfg):
    """rule_set 用了已废弃的 download_detour（与 http_client 冲突，启动 FATAL）。"""
    _first_rs(cfg)["download_detour"] = "direct-download"


def m_dup_tag(cfg):
    """两个出站用了同一个 tag。"""
    cfg["outbounds"][2]["tag"] = "Node-01"


def m_route_final_wrong(cfg):
    """route.final 指向不存在的出站。这是「值错了」，
    与 route-final-missing（「值没了」）是同一门禁的两条路径，都要覆盖。"""
    cfg["route"]["final"] = "NoSuchGroup"


def m_dns_final_wrong(cfg):
    """dns.final 指向不存在的 server。同上，与 dns-final-missing 配对。"""
    cfg["dns"]["final"] = "no-such-dns"


# ── C 模板 / 组结构 ─────────────────────────────────────────────────
def m_group_wrong_type(cfg):
    """🚀 Proxy 必须是 urltest，被改成 selector。"""
    _grp(cfg, "🚀 Proxy")["type"] = "selector"


def m_group_nesting(cfg):
    """组里嵌套另一个组 —— 两个 urltest 串联会互相拖累测速。"""
    _grp(cfg, "🚀 Proxy")["outbounds"] = ["🤖 AI"]


def m_urltest_no_url(cfg):
    """urltest 缺 url。"""
    _grp(cfg, "🚀 Proxy").pop("url", None)


def m_ad_default_direct(cfg):
    """去广告组 default 改成 direct —— 广告静默放行。"""
    _grp(cfg, "🚫 AD")["default"] = "direct"


def m_ad_polluted(cfg):
    """去广告组里放了非 block 的出口。"""
    _grp(cfg, "🚫 AD")["outbounds"] = ["block", "direct"]


# ── D 路由 / DNS / 规则集 ───────────────────────────────────────────
def m_ruleset_raw_url(cfg):
    """规则集走了 raw.githubusercontent.com（国内常打不开）。"""
    _first_rs(cfg)["url"] = "https://raw.githubusercontent.com/a/b/c.json"


def m_ruleset_no_http_client(cfg):
    """规则集没写 http_client。"""
    _first_rs(cfg).pop("http_client", None)


def m_ruleset_bad_url(cfg):
    """规则集 URL 不是统一 CDN 前缀。"""
    _first_rs(cfg)["url"] = "https://example.invalid/a.json"


def m_ruleset_format_missing(cfg):
    """url 不以 .srs/.json 结尾且没写 format。

    ⚠️ 必须**同时**满足两个条件才会响：只删 format（url 仍以 .srs 结尾）不触发。
    """
    _first_rs(cfg).pop("format", None)
    _first_rs(cfg)["url"] = "https://testingcf.jsdelivr.net/gh/x/y"


def m_rule_outbound_missing(cfg):
    """route.rules 引用了不存在的出站。"""
    for r in cfg["route"]["rules"]:
        if r.get("action") == "route":
            r["outbound"] = "NoSuchGroup"
            return


def m_rule_ruleset_missing(cfg):
    """route.rules 引用了未定义的规则集。"""
    cfg["route"]["rules"][5]["rule_set"] = ["no-such-set"]


def m_dns_rule_server_missing(cfg):
    """dns.rules 引用了不存在的 dns server。"""
    cfg["dns"]["rules"][1]["server"] = "no-such-dns"


def m_dns_rule_ruleset_missing(cfg):
    """dns.rules 引用了未定义的规则集。"""
    for r in cfg["dns"]["rules"]:
        if r.get("rule_set"):
            r["rule_set"] = ["no-such-set"]
            return


def m_dns_detour_wrong(cfg):
    """dns.servers[].detour 指向不存在的出站。"""
    for s in cfg["dns"]["servers"]:
        if s.get("detour"):
            s["detour"] = "NoSuchGroup"
            return


# ── E 平台 / 配置字段 ───────────────────────────────────────────────
def m_platform_strict_route(cfg):
    """移动端不支持 strict_route。"""
    cfg["inbounds"][0]["strict_route"] = True


def m_resolve_moved_to_end(cfg):
    """resolve 排到第一个 route/reject 之后 —— 等于没放。

    ⚠️ 靶心是「**之后**」。把它插到 hijack-dns 之前**不算**错（那正是正确位置），
    所以必须移到末尾。
    """
    rules = cfg["route"]["rules"]
    for i, r in enumerate(rules):
        if r.get("action") == "resolve":
            rules.append(rules.pop(i))
            return


def m_resolve_wrong_strategy(cfg):
    """resolve 的 strategy 不是 ipv4_only。"""
    for r in cfg["route"]["rules"]:
        if r.get("action") == "resolve":
            r["strategy"] = "prefer_ipv4"
            return


def m_resolve_missing(cfg):
    """整个删掉 resolve 规则。"""

    cfg["route"]["rules"] = [r for r in cfg["route"]["rules"]
                             if r.get("action") != "resolve"]


def m_no_auto_detect_interface(cfg):
    """auto_detect_interface 关掉 —— 出站回灌 tun，能启动但没网。"""
    cfg["route"]["auto_detect_interface"] = False


# ── 用例表 ──────────────────────────────────────────────────────────
# (用例名, 破坏函数名, 期望的 code, 期望级别)
# 作用域固定 `single`（跑临时配置，快且不碰真文件），由 negtest.py 组装。
CASES = [
    # A 安全 / 防泄漏
    ("cache-path-parent-a", "m_cache_path_parent", "cache_path_parent", "ERROR"),
    ("cache-path-abs-a", "m_cache_path_abs", "cache_path_abs", "WARN"),
    # B 引用完整性
    ("ruleset-download-detour-a", "m_ruleset_download_detour", "ruleset_download_detour", "ERROR"),
    ("dup-tag-a", "m_dup_tag", "dup_tag", "ERROR"),
    ("route-final-wrong", "m_route_final_wrong", "final_missing", "ERROR"),
    ("dns-final-wrong", "m_dns_final_wrong", "dns_final_missing", "ERROR"),
    # C 模板 / 组结构
    ("group-wrong-type-a", "m_group_wrong_type", "group_wrong_type", "ERROR"),
    ("group-nesting-a", "m_group_nesting", "group_nesting", "ERROR"),
    ("urltest-no-url-a", "m_urltest_no_url", "urltest_no_url", "ERROR"),
    ("ad-default-direct-a", "m_ad_default_direct", "ad_group_default_not_block", "ERROR"),
    ("ad-polluted-a", "m_ad_polluted", "ad_group_polluted", "ERROR"),
    # D 路由 / DNS / 规则集
    ("ruleset-raw-url-a", "m_ruleset_raw_url", "ruleset_url_raw", "ERROR"),
    ("ruleset-no-http-client", "m_ruleset_no_http_client", "ruleset_http_client", "ERROR"),
    ("ruleset-bad-url", "m_ruleset_bad_url", "ruleset_url", "WARN"),
    ("ruleset-format-missing", "m_ruleset_format_missing", "ruleset_format", "WARN"),
    ("rule-outbound-missing-a", "m_rule_outbound_missing", "rule_outbound_missing", "ERROR"),
    ("rule-ruleset-missing-a", "m_rule_ruleset_missing", "rule_ruleset_missing", "ERROR"),
    ("dns-rule-server-missing-a", "m_dns_rule_server_missing", "dns_rule_server_missing", "ERROR"),
    ("dns-rule-ruleset-missing-a", "m_dns_rule_ruleset_missing", "dns_rule_ruleset_missing", "ERROR"),
    ("dns-detour-wrong", "m_dns_detour_wrong", "dns_server_detour_missing", "ERROR"),
    # E 平台 / 配置字段
    ("platform-strict-route-a", "m_platform_strict_route", "platform_strict_route", "ERROR"),
    ("resolve-moved-to-end-a", "m_resolve_moved_to_end", "resolve_not_first", "ERROR"),
    ("resolve-wrong-strategy-a", "m_resolve_wrong_strategy", "resolve_not_ipv4_only", "ERROR"),
    # ⚠️ resolve_missing_ipv4_only 是 **WARN** 级，不是 ERROR
    ("resolve-missing-a", "m_resolve_missing", "resolve_missing_ipv4_only", "WARN"),
    ("no-auto-detect-interface-a", "m_no_auto_detect_interface",
     "tun_without_auto_detect_interface", "ERROR"),
]
