#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""negtest.py —— 门禁的负向回归：故意改坏配置，确认对应的门禁真的会响。

为什么需要它（这是七条改造的第 7 条）：
    在这之前，每次新增或修改门禁，我都是**临时现写样本、跑完就删**。
    结果是：① 下次要验证同一件事得从零再写一遍；② 没人知道某个门禁是不是
    「永远不响的死检查」（L34 就是这样埋了很久：它按一个早就不再使用的字面量匹配）；
    ③ 改门禁时没有回归网，容易把一个能响的检查改成不响的，而 audit 自己照样全绿。

    一个门禁只有**同时**满足两件事才算数：
      · 干净时安静（false positive 为零）—— 由 `tools/audit.py` 全绿保证；
      · 被破坏时会响（true positive）—— 由本脚本保证。
    缺了后一半，门禁就只是装饰。

用法：
    python tools/negtest.py            # 跑全部用例
    python tools/negtest.py -k dns     # 只跑名字含 dns 的用例
    python tools/negtest.py -v         # 打印每个用例的门禁实际报了什么

机制：每个用例拿到「真实 profile 的 dict」，做一处最小破坏，写到 `local/_negtest/`
（该目录在 .gitignore 覆盖范围内，且跑完即删），然后调**真实的 CLI**
（`python tools/audit.py --no-check --json <file>`）解析它报出的 code。
不 mock、不 import 审计函数 —— 走的就是 CI 走的那条路。
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEGDIR = ROOT / "local" / "_negtest"
BASE = ROOT / "profiles" / "1.14" / "android-lazy.json"

# Windows 上 stdout 重定向到管道/文件时，Python 默认用 GBK，本文件到处是 emoji
# （✅/❌），一 `| tee` 就 UnicodeEncodeError 崩掉 —— 而「管道里崩」恰恰是
# 「本地绿、CI 红」这一类问题的温床（同 L30 的思路：输出编码也是环境依赖）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):      # 老 Python / 已被包装的流
        pass


# ──────────────────────────────────────────────────────────────────────
# 用例：每个函数接受 profile 的 dict（深拷贝后的），就地破坏它。
# 第一条必须能触发第二条的 code（在 CASES 里登记）。
# ──────────────────────────────────────────────────────────────────────
def _by_tag(cfg, tag):
    return next(o for o in cfg["outbounds"] if o.get("tag") == tag)


def m_matrix_path_renamed(cfg):
    """占位：真实动作在 run_case_matrix() 里做（它改的是矩阵文件，不是这份配置）。

    保留这个函数是为了让 CASES 的形状统一（名字仍在输出里出现）。
    """


def m_ad_gets_direct(cfg):
    """🚫 AD 里放回 direct —— 广告组变成可放行。"""
    _by_tag(cfg, "🚫 AD")["outbounds"] = ["block", "direct"]


def m_ad_default_direct(cfg):
    """🚫 AD 的 default 改成 direct（组里没有 direct 时选中即回退 → 静默放行）。"""
    _by_tag(cfg, "🚫 AD")["default"] = "direct"


def m_group_tag_reverted(cfg):
    """组 tag 退回裸 ASCII 旧名 —— 与所有引用处不一致。"""
    _by_tag(cfg, "🚀 Proxy")["tag"] = "Proxy"
    cfg["route"]["rules"][8]["outbound"] = "Proxy"


def m_group_missing(cfg):
    """删掉一个模板声明的固定组。"""
    cfg["outbounds"] = [o for o in cfg["outbounds"] if o.get("tag") != "🤖 AI"]
    cfg["route"]["rules"] = [r for r in cfg["route"]["rules"] if r.get("outbound") != "🤖 AI"]


def m_unknown_group(cfg):
    """多出一个模板里没登记的组。"""
    cfg["outbounds"].append({"type": "selector", "tag": "🆕 Extra", "outbounds": ["direct"]})


def m_dangling_outbound(cfg):
    """route.rules 指向一个不存在的出站 tag（check 不报，运行时才炸）。"""
    cfg["route"]["rules"][8]["outbound"] = "nonexistent-group"


def m_dangling_group_ref(cfg):
    """组自身引用一个不存在的出站（dangling_ref 管的是这一类）。"""
    _by_tag(cfg, "🤖 AI")["outbounds"] = ["Node-01", "ghost-node"]


def m_dns_detour_stale_name(cfg):
    """dns.servers 的 detour 写成旧组名 —— 既是悬空引用，也是散文外的旧名残留。"""
    for s in cfg["dns"]["servers"]:
        if s.get("detour"):
            s["detour"] = "Proxy"


def m_cache_path_parent(cfg):
    """cache_file.path 含 '..'（父目录不存在会 FATAL，见 ENOENT 事故）。"""
    cfg["experimental"]["cache_file"]["path"] = "../cache/cache.db"


def m_ad_no_url(cfg):
    """urltest 组丢了 url。"""
    _by_tag(cfg, "🤖 AI").pop("url", None)


def m_dns_ad_without_whitelist(cfg):
    """dns.rules 引了广告拦截集，却没有 jinx-direct 白名单配套。"""
    cfg["dns"]["rules"] = [r for r in cfg["dns"]["rules"] if r.get("rule_set") != ["jinx-direct"]]


def m_dns_ad_action_route(cfg):
    """DNS 层拦截写成 action=route —— 等于没拦（route 是「换个服务器解析」）。"""
    for r in cfg["dns"]["rules"]:
        if r.get("rule_set") == ["jinx-ads", "awanue-ads"]:
            r["action"] = "route"
            r["server"] = "dns-cn"
            r.pop("rcode", None)


def m_dns_ad_before_whitelist(cfg):
    """白名单排到拦截之后 —— 被覆盖的白名单域名会被误拦。"""
    rules = cfg["dns"]["rules"]
    wi = next(i for i, r in enumerate(rules) if r.get("rule_set") == ["jinx-direct"])
    bi = next(i for i, r in enumerate(rules) if r.get("rule_set") == ["jinx-ads", "awanue-ads"])
    rules[wi], rules[bi] = rules[bi], rules[wi]


def m_resolve_wrong_strategy(cfg):
    """resolve 没写 ipv4_only。"""
    for r in cfg["route"]["rules"]:
        if r.get("action") == "resolve":
            r["strategy"] = "prefer_ipv4"


def m_resolve_moved_to_end(cfg):
    """resolve 挪到末尾 —— 命中 route/reject 就 break match，等于没放（L18）。"""
    rules = cfg["route"]["rules"]
    ri = next(i for i, r in enumerate(rules) if r.get("action") == "resolve")
    rules.append(rules.pop(ri))


def m_no_auto_detect_interface(cfg):
    """tun + auto_route 却没写 auto_detect_interface（Android 上表现为能启动没网）。"""
    cfg["route"].pop("auto_detect_interface", None)


def m_dns_detour_dangling(cfg):
    """dns.servers 的 detour 指向不存在的出站（L35 事故原形）。"""
    for s in cfg["dns"]["servers"]:
        if s.get("detour"):
            s["detour"] = "Proxy"      # 旧名，已不存在


def m_ruleset_missing(cfg):
    """route.rules 引用一个没在 route.rule_set 里声明的规则集。"""
    cfg["route"]["rules"][10]["rule_set"] = ["geosite-nonexistent"]


def m_dup_tag(cfg):
    """两个出站用同一个 tag。"""
    _by_tag(cfg, "direct").setdefault("_x", 0)
    cfg["outbounds"].append({"type": "direct", "tag": "direct"})


def m_direct_empty(cfg):
    """direct-download 丢掉 domain_resolver —— 变回「空 direct」，规则集下载 FATAL。"""
    _by_tag(cfg, "direct-download").pop("domain_resolver", None)


def m_strict_route_on_mobile(cfg):
    """Android/iOS 写了 strict_route（官方未实现）。"""
    cfg["inbounds"][0]["strict_route"] = True


def m_apple_engine_on_universal(cfg):
    """非 Apple 平台用了 engine: apple（NSURLSession）。"""
    for c in cfg.get("http_clients", []):
        c["engine"] = "apple"


def m_final_missing(cfg):
    """route.final 指向不存在的出站。"""
    cfg["route"]["final"] = "does-not-exist"


def m_cache_path_absolute(cfg):
    """cache_file.path 写成绝对路径。"""
    cfg["experimental"]["cache_file"]["path"] = "C:/tmp/cache.db"


def m_placeholder_server(cfg):
    """profiles/ 里出现非占位域名（真实节点域名被提交进仓库）。"""
    _by_tag(cfg, "🧪 Placeholder") if False else None
    cfg["outbounds"][0]["server"] = "node-01.example.com"


# (用例名, 破坏函数, 期望的 code, 期望级别, 作用范围)
#   作用范围 "single" = 改一份临时配置，只跑那一份（快）
#            "repo"   = 临时改**真实** profile 跑整个仓库审计（用于「必须比对真实文件」的门禁，
#                       如模板 ⟺ profile 对账、文档散文扫查）—— 跑完立即还原
#            "matrix" = 临时改**真实** docs/version-matrix.json（用于「门禁本身失效」这类
#                       只能靠矩阵触发的检查，见 L39）—— 跑完立即还原
CASES = [
    ("ad-gets-direct",            m_ad_gets_direct,            "ad_group_polluted",              "ERROR", "single"),
    ("ad-default-direct",         m_ad_default_direct,         "ad_group_default_not_block",     "ERROR", "single"),
    ("group-tag-reverted",        m_group_tag_reverted,        "group_tag_incomplete",           "ERROR", "single"),
    ("group-missing",             m_group_missing,             "template_profile_group_missing", "ERROR", "repo"),
    ("unknown-group",             m_unknown_group,             "profile_group_not_in_template",  "ERROR", "repo"),
    ("dangling-group-ref",        m_dangling_group_ref,        "dangling_ref",                   "ERROR", "single"),
    ("dangling-rule-outbound",    m_dangling_outbound,         "rule_outbound_missing",          "ERROR", "single"),
    ("dns-ad-without-whitelist",  m_dns_ad_without_whitelist,  "dns_ad_without_whitelist",       "ERROR", "single"),
    ("dns-ad-action-route",       m_dns_ad_action_route,       "dns_ad_target",                  "ERROR", "single"),
    ("dns-ad-before-whitelist",   m_dns_ad_before_whitelist,   "dns_ad_order",                   "ERROR", "single"),
    ("resolve-wrong-strategy",    m_resolve_wrong_strategy,    "resolve_not_ipv4_only",          "ERROR", "single"),
    ("resolve-moved-to-end",      m_resolve_moved_to_end,      "resolve_not_first",              "ERROR", "single"),
    ("no-auto-detect-interface",  m_no_auto_detect_interface,  "tun_without_auto_detect_interface", "ERROR", "single"),
    ("dns-detour-dangling",       m_dns_detour_dangling,       "dns_server_detour_missing",      "ERROR", "single"),
    ("detour-stale-group-name",   m_dns_detour_stale_name,     "doc_group_name_stale",           "ERROR", "repo"),
    ("ruleset-missing",           m_ruleset_missing,           "rule_ruleset_missing",           "ERROR", "single"),
    ("dup-tag",                   m_dup_tag,                   "dup_tag",                        "ERROR", "single"),
    ("direct-empty",              m_direct_empty,              "download_detour_empty_direct",   "ERROR", "single"),
    ("strict-route-on-mobile",    m_strict_route_on_mobile,    "platform_strict_route",          "ERROR", "single"),
    ("apple-engine-universal",    m_apple_engine_on_universal, "apple_engine_on_universal",      "ERROR", "single"),
    ("final-missing",             m_final_missing,             "final_missing",                  "ERROR", "single"),
    ("cache-path-absolute",       m_cache_path_absolute,       "cache_path_abs",                "WARN",  "single"),
    ("cache-path-parent",         m_cache_path_parent,         "cache_path_parent",              "ERROR", "single"),
    ("ad-no-url",                 m_ad_no_url,                 "urltest_no_url",                 "ERROR", "single"),
    # ⚠️ 这个用例**故意不碰配置**，去改矩阵——因为它模拟的是「上游把字段改名」：
    # 此后 find_paths 永远返回空、那条门禁静默失声，而配置侧门禁全部照旧全绿。
    # 这是唯一一类「改配置根本触发不了」的失效（L39），所以作用域是 matrix。
    ("matrix-path-renamed",       m_matrix_path_renamed,       "matrix_path_unreachable",        "ERROR", "matrix"),
]

# 矩阵里的字段路径：既能真实触发矩阵，又确实是本仓关心的一条（1.12.0 已移除）。
MATRIX_PATH_OLD = '"path": "route.rules[].geosite"'
MATRIX_PATH_NEW = '"path": "route.rules[].geosite_renamed_by_upstream"'


def _audit_codes(path_or_none, level="ERROR", repo_args=(), no_check=True):
    """跑真实的 audit CLI，返回报出的 code 集合。不 mock、不 import 审计函数。"""
    cmd = [sys.executable, str(ROOT / "tools" / "audit.py"), "--json"]
    if no_check:
        cmd.append("--no-check")
    cmd.extend(repo_args)
    if path_or_none is not None:
        cmd.append(str(path_or_none))
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"audit.py 的输出不是 JSON（rc={proc.returncode}）：{proc.stdout[:200]!r}"
        ) from None
    return {
        it.get("code") for rep in data for it in rep.get("items", [])
        if it.get("level") == level
    }


class SkipCase(Exception):
    """环境不满足（例如本机没有 sing-box 可执行文件），跳过而不是判失败。

    区分「门禁失效了」与「这次没法验」很重要：前者必须红，后者报绿就是撒谎。
    """


def run_case_single(name, mutate, base_text, level):
    cfg = copy.deepcopy(json.loads(base_text))
    mutate(cfg)
    NEGDIR.mkdir(parents=True, exist_ok=True)
    # 文件名里带 android：audit 的 infer_platform() 靠文件名判平台
    out = NEGDIR / f"neg-android-{name}.json"
    out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # audit 对 local/*.json 是**顶层 glob、不递归** —— 所以临时负向配置必须放子目录里。
    # 否则它会被整仓审计顺手审一遍，用例断言的「某 code 出现了」可能是别的文件贡献的：
    # 一个永远不响的门禁照样会「通过」（这正是本脚本要防的那类假绿）。
    if _is_scan_target(out):
        raise RuntimeError(
            f"❗ 临时配置 {out} 会被整仓审计当普通配置扫进去，负向用例会失真"
        )
    return _audit_codes(out, level)


def _is_scan_target(path):
    """这份文件会不会被 audit 当成「该审的配置」扫进去？

    audit 对 `local/` 只做顶层 glob（有意不递归，好让 local/_archive/ 天然免检）。
    所以负向样本必须落在子目录里 —— 这是个**隐式**约束，靠一条 runtime 断言守住，
    不然哪天把 NEGDIR 改成 local/ 顶层，整套负向回归会静默变假绿。
    """
    try:
        rel = Path(path).resolve().relative_to(Path(ROOT).resolve())
    except ValueError:
        return False
    return rel.parent.as_posix() == "local" or rel.parts[0] == "profiles"


def run_case_repo(name, mutate, base_text, level):
    """临时改**真实** profile 跑整仓审计，再立即还原。

    用于「必须与真实文件对账」的门禁（模板 ⟺ profile、散文扫查）。
    风险：这个函数写仓库内的真实文件 —— 所以用 try/finally 保证还原，
    并对比字节长度确认还原成功。
    """
    original = BASE.read_bytes()
    cfg = copy.deepcopy(json.loads(base_text))
    mutate(cfg)
    try:
        BASE.write_bytes(
            (json.dumps(cfg, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
        return _audit_codes(None, level)
    finally:
        BASE.write_bytes(original)
        if BASE.read_bytes() != original:
            raise RuntimeError(f"❗ 还原 {BASE} 失败——请手工 git checkout 恢复")


# 矩阵是「知识」，不是「配置」——它失效时配置侧门禁会**静默全绿**（L39）。
# 所以负向套件必须能故意去动矩阵，否则「门禁失效」这一类永远没有被验证的机会。
MATRIX = ROOT / "docs" / "version-matrix.json"


def run_case_matrix(name, mutate, base_text, level):
    """临时改**真实**矩阵，跑整仓审计，再立即还原（同 run_case_repo 的纪律）。

    用文本替换而非 json 重写：矩阵文件的行尾与缩进风格要保持原样，
    否则一次负向测试就会给仓库留下几百行的格式 diff。
    """
    original = MATRIX.read_bytes()
    text = original.decode("utf-8")
    if original.count(MATRIX_PATH_OLD.encode("utf-8")) != 1:
        raise RuntimeError(f"❗ 矩阵里找不到唯一的锚点 {MATRIX_PATH_OLD}")
    try:
        MATRIX.write_bytes(text.replace(MATRIX_PATH_OLD, MATRIX_PATH_NEW).encode("utf-8"))
        # 探针需要真实内核：没有可执行文件时**跳过**（不能报绿，那是撒谎）。
        codes = _audit_codes(None, level, no_check=False)
        if "matrix_probe_skipped" in codes:
            raise SkipCase("本机没有 sing-box 可执行文件，探针没法跑")
        return codes
    finally:
        MATRIX.write_bytes(original)
        if MATRIX.read_bytes() != original:
            raise RuntimeError(f"❗ 还原 {MATRIX} 失败——请手工 git checkout 恢复")
        # 探针留下的临时文件也要清掉：它在 local/_negtest/ 里虽不被扫，但会积垃圾。
        try:
            (NEGDIR / ".matrix-probe.json").unlink()
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description="门禁负向回归（故意改坏配置，确认门禁会响）")
    ap.add_argument("-k", metavar="SUBSTR", help="只跑名字含该子串的用例")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每个用例实际报出的 code")
    args = ap.parse_args()

    if not BASE.exists():
        print(f"❌ 找不到基准配置 {BASE}", file=sys.stderr)
        return 2
    base_text = BASE.read_text(encoding="utf-8")

    cases = [c for c in CASES if not args.k or args.k in c[0]]
    if not cases:
        print(f"❌ 没有匹配 {args.k!r} 的用例", file=sys.stderr)
        return 2

    print("═" * 68)
    print("  门禁负向回归：每个用例故意改坏一处，期望对应门禁报出指定 code")
    print("═" * 68)
    bad = []
    try:
        for name, mutate, expect, level, scope in cases:
            try:
                if scope == "matrix":
                    codes = run_case_matrix(name, mutate, base_text, level)
                elif scope == "repo":
                    codes = run_case_repo(name, mutate, base_text, level)
                else:
                    codes = run_case_single(name, mutate, base_text, level)
                ok, why = expect in codes, "命中"
                if not ok:
                    why = f"**没有**报出 {expect!r}"
            except SkipCase as ex:
                print(f"  ⏭ {name:<26} [{level:<5}] → {expect}   跳过：{ex}")
                continue
            except Exception as ex:                      # noqa: BLE001
                ok, why, codes = False, f"跑崩了：{ex}", set()
            mark = "✅" if ok else "❌"
            print(f"  {mark} {name:<26} [{level:<5}] → {expect}")
            if args.verbose or not ok:
                print(f"       {why}")
                if codes:
                    print(f"       实际 {level}: {', '.join(sorted(c for c in codes if c))}")
            if not ok:
                bad.append((name, expect))
    finally:
        shutil.rmtree(NEGDIR, ignore_errors=True)

    print("═" * 68)
    if bad:
        print(f"  ❌ {len(bad)}/{len(cases)} 个用例失败——门禁可能已成死检查：")
        for name, expect in bad:
            print(f"       {name}（期望 {expect}）")
        print("═" * 68)
        return 1
    print(f"  ✅ {len(cases)}/{len(cases)} 个用例全部命中——门禁是活的")
    print("═" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
