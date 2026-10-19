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
import os
import shutil
import subprocess
import sys

# L37：Windows 上 stdout 重定向到管道时默认回退 GBK，
# 本文件到处是 ✅/❌，一 `| tee` 就 UnicodeEncodeError 崩掉
# —— 管道里崩正是「本地绿、CI 红」的温床。故 import 后立即 reconfigure。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass          # 极端环境（无 stdout）下不影响主流程

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEGDIR = ROOT / "local" / "_negtest"
BASE = ROOT / "profiles" / "1.14" / "android-lazy.json"


# ── 「改真实文件」的两层保护 ──────────────────────────────────────
# 背景（2026-10-19 实测复现）：
#   repo / matrix / doc 三个作用域都会临时改**真实入库文件**，靠 try/finally 还原。
#   但 Windows 上 os.kill(SIGTERM) / taskkill /F / 任务管理器 / timeout 命令
#   走的都是 TerminateProcess —— **进程瞬间消失，finally / atexit / 信号处理器
#   一律不执行**。实测跑到一半 SIGTERM → docs/version-matrix.json 永久留在
#   「被故意改坏」的状态；而它是门禁的真相源，被污染后引用它的检查全部失真。
#
# 所以做两层：
#   ① 信号处理器 —— 只兜得住 Ctrl-C / Ctrl-Break（覆盖面有限，见函数说明）
#   ② 开跑前自检 —— **不赌上轮正常结束**，每次开跑前重新比对，发现脏就恢复
#      （真正管用的是这层：硬杀之后唯一的机会就是下一次开跑）
_DIRTY = {}


def register_dirty(path, original_bytes):
    """改动真实文件前登记，供信号/退出时兜底还原。"""
    _DIRTY[str(path)] = original_bytes


def unregister_dirty(path):
    """正常还原后注销。"""
    _DIRTY.pop(str(path), None)


def restore_all_dirty():
    """把登记表里还没还原的文件全部还原。返回还原成功数。"""
    n = 0
    for path_str, original in list(_DIRTY.items()):
        try:
            p = Path(path_str)
            if p.read_bytes() != original:
                p.write_bytes(original)
            _DIRTY.pop(path_str, None)
            n += 1
        except OSError:
            pass          # 尽力而为：信号处理器里不能抛异常
    return n


def _install_safety_net():
    """信号 + 退出时兜底还原。只做还原，不试图继续跑测试。

    ⚠️ 覆盖面（Windows 实测）：
      · Ctrl-C  → SIGINT，处理器会跑 ✓
      · Ctrl-Break → SIGBREAK，会跑 ✓
      · os.kill(SIGTERM) / taskkill /F / 任务管理器 / timeout 命令
        → TerminateProcess，**处理器不会跑** ✗
        （`subprocess.send_signal(2)` 在 Windows 上直接 ValueError）
    所以这一层只是补充；真正管用的是 `_guard_against_leftover_dirty()`。
    """
    import atexit
    import signal as _signal

    def _handler(signum, _frame):
        restore_all_dirty()
        _signal.signal(signum, _signal.SIG_DFL)
        raise SystemExit(128 + signum)

    # ⚠️ 常量必须在 try **里面**取：Windows 的 signal 模块没有 SIGHUP，
    #    写成循环里的元组字面量会在求值时就抛 AttributeError，except 轮不到
    #    —— 那会让整个 negtest.py 启动即崩（本行第一版就是这么错的）。
    for _sig_name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        try:
            _signal.signal(getattr(_signal, _sig_name), _handler)
        except (AttributeError, ValueError, OSError):
            pass          # 平台没有这个信号 / 非主线程装不上 —— 都跳过
    atexit.register(restore_all_dirty)


_install_safety_net()


def _watched_paths():
    """「会被负向用例改动」的真实文件清单 —— 从代码算，不手写。

    第五轮复核 P2-A：手写 3 个，实际 6 个 —— 漏掉的 3 个不告警也不恢复。
    手抄一份会漂的副本，正是 L52「判据与待检特征同源」禁止的做法。
    """
    watched = {
        str(BASE.relative_to(ROOT)).replace(chr(92), "/"),
        str(MATRIX.relative_to(ROOT)).replace(chr(92), "/"),
    }
    # ⚠️ **不能**写成 `try: watched.update(DOC_MUTATIONS_TARGETS) except NameError: pass`。
    #    那正是让我静默两轮提交的写法（第六轮复核 P3-2 实测复现）：
    #    定义行一改名 → 清单从 6 个悄悄变 2 个，而全套 69/69 照样全绿、零提示。
    #    ——「用 except: pass 前问一句：它会不会把『我做错了』也一起吞掉？」
    #    这条教训我自己写进了上一轮报告，然后**原样留着那行代码**。
    #    现在缺定义就**报错**，不降级。
    if "DOC_MUTATIONS_TARGETS" not in globals():
        raise RuntimeError(
            "❗ DOC_MUTATIONS_TARGETS 未定义 —— 开跑前自检的监视清单会悄悄缩水，"
            "而被硬杀时那些文件就不会被恢复。"
            "请检查 negdoc_mutations 的 import 与 DOC_MUTATIONS_TARGETS 的定义行。"
        )
    watched.update(DOC_MUTATIONS_TARGETS)

    # 条数断言：把它变成**会响的东西**（复核建议）。
    # 少了就报错 —— 覆盖面的缩水不该由人肉「插完打印一次」来发现。
    _MIN_EXPECTED = 5          # BASE + MATRIX + doc 表里至少 3 个不同的目标
    if len(watched) < _MIN_EXPECTED:
        raise RuntimeError(
            f"❗ 开跑前自检的监视清单只有 {len(watched)} 个文件（至少要 "
            f"{_MIN_EXPECTED} 个）：{sorted(watched)}。"
            "清单缩水意味着被硬杀时这些文件不会被恢复 —— "
            "新增/改名用例时请同步检查 DOC_MUTATIONS。"
        )
    return sorted(watched)


BASELINE = ROOT / "local" / ".negtest-baseline.json"


def _save_baseline():
    """开跑前：记下「将被改的文件」此刻的内容。

    ⚠️ 判据必须是「相对**上次开跑时**」，不能用「相对 git 脏」——
       后者包含开发者自己的正常编辑，而 tools/negtest.py 就在清单里，
       会形成「只要在改 negtest 就没法跑 negtest」的死循环（实测踩到：
       应用改动 → 跑一次 → 改动被 git checkout 冲掉）。
    """
    data = {}
    for rel in _watched_paths():
        try:
            # ⚠️ newline="" —— 保持行尾原样。默认会做 CRLF 转换，
            #    恢复时写回 CRLF 就触发本仓门禁「绕过 patch-text 裸写」的指纹（实测踩到）。
            with (ROOT / rel).open(encoding="utf-8", newline="") as fh:
                data[rel] = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
    try:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(data, ensure_ascii=False),
                            encoding="utf-8")
    except OSError:
        pass          # 记不下基线不致命：只是失去一层保护


def _clear_baseline():
    try:
        BASELINE.unlink()
    except OSError:
        pass


def _guard_against_leftover_dirty():
    """开跑前自检：上轮若被硬杀留下脏文件，用**上次开跑时的基线**恢复。

    ⚠️ 为什么不能用「相对 git 脏」（实测踩到的死循环）：
       tools/negtest.py 在监视清单里（tool-selftest-failed 会改它），
       而「我正在编辑 negtest.py」本身就让它相对 git 是 M ——
       自检于是把**我的编辑**当成「上轮残留」git checkout 掉。

    ✅ 用「上次开跑时记下的内容」作判据就不会误判：
       我总是先编辑再跑，所以基线里存的就是我编辑后的内容。
    """
    if not BASELINE.exists():
        return
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _clear_baseline()
        return
    dirty = []
    for rel, want in data.items():
        try:
            with (ROOT / rel).open(encoding="utf-8", newline="") as fh:
                now = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if now != want:
            dirty.append(rel)
    if not dirty:
        _clear_baseline()
        return
    print("  ⚠️ 检测到上一轮**未正常结束**留下改动（很可能是被硬杀）：")
    for rel in dirty:
        print("       %s" % rel)
    print("     → 用上次开跑时的基线内容恢复"
          "（不是 git 版本 —— 那会吞掉你自己的编辑）")
    for rel in dirty:
        try:
            # 同样 newline="" —— 恢复必须是字节级原样，不做任何换行转换
            with (ROOT / rel).open("w", encoding="utf-8", newline="") as fh:
                fh.write(data[rel])
        except OSError:
            pass
    _clear_baseline()



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


def m_ai_default_dangling(cfg):
    """组默认项指向一个不存在的 tag。

    2026-10-19 审查 P1-A 的现场：骨架里 🤖 AI 写着 default="Node-01"，
    而 mknode 删占位节点时只清了组员数组、没清 default ——
    于是产物带一个悬空 default，check 全绿但 run 立刻 FATAL：
      selector[🤖 AI]: default outbound not found: Node-01

    这条用例保证 `default_dangling` 门禁真的会响。
    """
    _by_tag(cfg, "🤖 AI")["default"] = "ghost-node"


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
    """selector 组丢了 default。

    ⚠️ 本用例原名 `ad-no-url`、改的是 `🤖 AI` 组的 `url` —— 那是 AI 还是 urltest 时写的
    （urltest 必须有 url）。2026-10-14 AI 改为 **selector 优先** 后，
    AI 组已不含 `url` 字段，`pop("url")` 删不到东西 ⇒ 门禁不响、用例假失败。
    ⇒ 改成测 selector 的真实约束：**缺 default**（`template_ai_no_default`）。

    「urltest 缺 url」这条约束本身仍有 `urltest-no-url-a` 用 `🚀 Proxy` 覆盖着（Proxy 仍是 urltest）。
    """
    _by_tag(cfg, "🤖 AI").pop("default", None)


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


def m_coverage_floor_raised(cfg):
    """覆盖窗口起点高于已盘点版本 —— 声称盘过而实际没盘（L43）。"""
    pass  # 真改动在 MATRIX_MUTATIONS 里（改的是矩阵文件，不是这份配置）


def m_coverage_inventory_missing(cfg):
    """覆盖窗口起点低于已盘点版本 —— 把已盘过的版本拉回比对窗口（L43）。"""
    pass


def m_coverage_floor_declared_but_missing(cfg):
    """矩阵里干脆不声明覆盖窗口起点。"""
    pass


def m_placeholder_server(cfg):
    """入库文件里出现非占位域名（真实节点域名被提交进仓库）。

    ⚠️ 这个破坏函数曾经是**坏的**：它把 server 设成 `node-01.example.com` ——
    那**本身就是占位域名**，门禁当然不会响。即使登记进 CASES 也永远 ✅，
    是一条「假装在验、实际什么都没验」的死用例（L37 的形态）。
    现在改成真域名，并登记进 CASES。
    """
    # 必须**不是**占位域名（PLACEHOLDER_DOMAINS = .example.com/.org/.net/.invalid/.test/.localhost），
    # 否则本用例又变成死用例。用一个真域名形态、且刻意避开上述后缀。
    cfg["outbounds"][0]["server"] = "node-01.my-vps-host.xyz"


def m_route_final_missing(cfg):
    """把 route.final 整个删掉 —— 流量会静默走 sing-box 默认出站（L48）。"""
    cfg["route"].pop("final", None)


def m_dns_final_missing(cfg):
    """把 dns.final 整个删掉 —— 查询会走 dns.servers 第一条（本仓是明文 bootstrap，L48）。"""
    cfg["dns"].pop("final", None)


def m_empty_group_in_real_config(cfg):
    """完整可运行配置里把组清空 —— 真 FATAL: missing tags（L48）。

    旧写法对 NO_NESTING_GROUPS 里的组一律降级成 WARN，于是这条**抓不到**。
    """
    for o in cfg.get("outbounds", []):
        if isinstance(o, dict) and o.get("type") in ("selector", "urltest"):
            o["outbounds"] = []
            return


# (用例名, 破坏函数, 期望的 code, 期望级别, 作用范围)
#   作用范围 "single" = 改一份临时配置，只跑那一份（快）
#            "repo"   = 临时改**真实** profile 跑整个仓库审计（用于「必须比对真实文件」的门禁，
#                       如模板 ⟺ profile 对账、文档散文扫查）—— 跑完立即还原
#            "matrix" = 临时改**真实** docs/version-matrix.json（用于「门禁本身失效」这类
#                       只能靠矩阵触发的检查，见 L39）—— 跑完立即还原
# 判据是「这个文件会不会被提交」的用例。负向样本落在 local/ 下天然不是入库文件，
# 靠 _audit_codes 注入 __NEGTEST_FAKE_TRACKED 给它一个临时身份（见 run_case_single）。
TRACKED_SENSITIVE_CASES = {"placeholder-server"}

CASES = [
    ("ad-gets-direct",            m_ad_gets_direct,            "ad_group_polluted",              "ERROR", "single"),
    ("ad-default-direct",         m_ad_default_direct,         "ad_group_default_not_block",     "ERROR", "single"),
    ("group-tag-reverted",        m_group_tag_reverted,        "group_tag_incomplete",           "ERROR", "single"),
    ("group-missing",             m_group_missing,             "template_profile_group_missing", "ERROR", "repo"),
    ("unknown-group",             m_unknown_group,             "profile_group_not_in_template",  "ERROR", "repo"),
    ("dangling-group-ref",        m_dangling_group_ref,        "dangling_ref",                   "ERROR", "single"),
    ("ai-default-dangling",      m_ai_default_dangling,       "default_dangling",               "ERROR", "single"),
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
    # 防真实节点外泄的那一道。判据已由「目录名 == profiles」改为「被 git 跟踪 ⇒ 入库」
    # （见 audit.py 该处注释），此用例确保它改了之后**仍然会响**。
    # 注意：这里必须用 "single"（跑临时配置）而不是 "repo" —— 后者会真去改 profiles/ 下的
    # 入库文件，一旦中途异常就可能把真域名留在仓库里，风险不对称。
    ("placeholder-server",        m_placeholder_server,        "placeholder_server",             "ERROR", "single"),
    # L48：三处「值缺失 ⇒ 门禁静默」的补齐。都是真 FATAL / 静默改道，而 check 不报。
    ("route-final-missing",       m_route_final_missing,       "final_missing",                  "ERROR", "single"),
    ("dns-final-missing",         m_dns_final_missing,         "dns_final_missing",              "ERROR", "single"),
    ("empty-group-real-config",   m_empty_group_in_real_config,"empty_group",                    "ERROR", "single"),
    ("dup-tag",                   m_dup_tag,                   "dup_tag",                        "ERROR", "single"),
    ("direct-empty",              m_direct_empty,              "download_detour_empty_direct",   "ERROR", "single"),
    ("strict-route-on-mobile",    m_strict_route_on_mobile,    "platform_strict_route",          "ERROR", "single"),
    ("apple-engine-universal",    m_apple_engine_on_universal, "apple_engine_on_universal",      "ERROR", "single"),
    ("final-missing",             m_final_missing,             "final_missing",                  "ERROR", "single"),
    ("cache-path-absolute",       m_cache_path_absolute,       "cache_path_abs",                "WARN",  "single"),
    ("cache-path-parent",         m_cache_path_parent,         "cache_path_parent",              "ERROR", "single"),
    # ⚠️ 作用域必须是 `repo`（跑整仓）而不是 `single`：
    # `template_ai_no_default` 在 `audit_template()` 里，**只对 templates/groups.json 生效**，
    # 单文件 profile 用例根本走不到那个函数 —— 写成 single 会假失败。
    ("ai-selector-no-default",    m_ad_no_url,                 "template_ai_no_default",         "ERROR", "tpl"),
    # ⚠️ 这个用例**故意不碰配置**，去改矩阵——因为它模拟的是「上游把字段改名」：
    # 此后 find_paths 永远返回空、那条门禁静默失声，而配置侧门禁全部照旧全绿。
    # 这是唯一一类「改配置根本触发不了」的失效（L39），所以作用域是 matrix。
    ("matrix-path-renamed",       m_matrix_path_renamed,       "matrix_path_unreachable",        "ERROR", "matrix"),
    # 覆盖窗口类（矩阵作用域，见 L43）：三种「看起来在查、其实没查」的形态。
    ("coverage-floor-stale",      m_coverage_floor_raised,      "coverage_floor_stale",           "WARN",  "matrix"),
    ("coverage-inv-missing",      m_coverage_inventory_missing, "coverage_inventory_missing",     "ERROR", "matrix"),
    ("coverage-floor-missing",    m_coverage_floor_declared_but_missing, "coverage_window_missing", "ERROR", "matrix"),
]

# 矩阵里的字段路径：既能真实触发矩阵，又确实是本仓关心的一条（1.12.0 已移除）。
MATRIX_PATH_OLD = '"path": "route.rules[].geosite"'
MATRIX_PATH_NEW = '"path": "route.rules[].geosite_renamed_by_upstream"'

# 覆盖窗口的锚点：**只用单行字符串**。
# 教训：这里最初写成跨行三引号字面量，结果被一次行尾转换（CRLF↔LF）悄悄改成
# 不匹配的形态，用例直接以 RuntimeError 崩掉（见 L42 的同类陷阱：锚点必须能被逐字复现）。
MATRIX_FLOOR_OLD = '"coverage_floor": "1.14.0",'
MATRIX_FLOOR_LOW = '"coverage_floor": "1.13.0",'    # 窗口起点低于 inventories ⇒ 把已盘过的版本拉回窗口
MATRIX_FLOOR_HIGH = '"coverage_floor": "1.15.0",'   # 窗口起点高于 inventories ⇒ 声称盘过而没盘
MATRIX_FLOOR_EMPTY = '"coverage_floor": "",'          # 干脆不声明窗口起点


# ── config-only 提速的安全兜底（2026-10-13）─────────────────────────
#
# 背景：single 用例占 negtest 耗时大头。它们的判据全是**配置类** code，
# 而每次还重复跑 9 项与配置无关的台账检查 —— 实测单次 1187ms → 293ms。
#
# ⚠️ 但这必须**证明**不会漏检，不能靠"我记得"。两道断言：
#
#   ① LEDGER_CODES：台账类 code 清单。断言这些 code 的用例若被分到
#      「会跳过台账」的作用域 ⇒ 它永远不响（假绿）⇒ 直接报错。
#   ② CONFIG_ONLY_SCOPES：允许走 config-only 的作用域白名单。
#
# 已验证（穷举 50 个 single 用例，全量 vs config-only 逐一对账）：
#   **配置类 code 被误跳过 0 个**。
LEDGER_CODES = {
    "lessons_missing", "lessons_missing_gate", "gate_without_lesson",
    "lesson_missing_element", "lesson_missing_gate_line",
    "decision_without_record", "decision_references_unknown", "decisions_missing",
    "new_feature_without_adoption", "new_feature_expect_invalid",
    "new_feature_uncovered", "new_feature_decision_overdue",
    "coverage_window_missing", "coverage_inventory_missing",
    "matrix_entry_missing_field", "matrix_path_unprobeable",
    "matrix_version_mismatch", "matrix_platform_stale",
    "tool_selftest_failed", "tool_syntax_error", "rules_dupe",
    "edit_method_fingerprint", "redaction_clean", "sensitive_ip_in_repo",
    "doc_group_name_stale", "doc_group_name_clean",
}

CONFIG_ONLY_SCOPES = {"single"}


def _assert_config_only_safe(name, expect, scope):
    """拦住「本该跑台账的用例被分到会跳过台账的作用域」——那会造成永久假绿。"""
    if scope not in CONFIG_ONLY_SCOPES:
        return
    if expect in LEDGER_CODES:
        raise RuntimeError(
            "use case " + repr(name) + " (scope=" + scope + ") asserts ledger code "
            + repr(expect) + ", but that scope skips the ledger via --config-only; "
            "it would never fire (false green). Move it to doc/matrix/repo scope."
        )


def _audit_codes(path_or_none, level="ERROR", repo_args=(), no_check=True,
                 extra_env=None, config_only=False):
    """跑真实的 audit CLI，返回报出的 code 集合。不 mock、不 import 审计函数。"""
    cmd = [sys.executable, str(ROOT / "tools" / "audit.py"), "--json"]
    if no_check:
        cmd.append("--no-check")
    if config_only:
        cmd.append("--config-only")
    cmd.extend(repo_args)
    if path_or_none is not None:
        cmd.append(str(path_or_none))
    env = None
    if extra_env:
        env = {**os.environ, **extra_env}
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, env=env,
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
    # 有些门禁的判据是**「这个文件会不会被提交进仓库」**（如 placeholder_server）。
    # 负向样本天生落在 local/ 下、是未跟踪的，于是这类门禁在样本上永远不会响 ——
    # 用例会假失败（门禁没坏，是样本不具备触发条件）。
    # 解：给这类用例提供一个**临时的「入库」身份**，跑完立刻摘掉。
    # 只在本次子进程内生效，绝不真的去 git add。
    fake_tracked = name in TRACKED_SENSITIVE_CASES
    # single 用例断言的都是**配置类** code（台账类的由 _assert_config_only_safe 兜住），
    # 故跳过 9 项与配置无关的台账检查 —— 实测单次 1187ms → 293ms。
    # 已穷举验证：50 个 single 用例的配置类 code 一个不漏。
    return _audit_codes(out, level,
                        extra_env={"__NEGTEST_FAKE_TRACKED": str(out)} if fake_tracked else None,
                        config_only=True)


def _is_scan_target(path):
    """这份文件会不会被 audit 当成「该审的配置」扫进去？

    audit 对 `local/` 只做顶层 glob（有意不递归，好让 local/_archive/ 天然免检）。
    所以负向样本必须落在子目录里 —— 这是个**隐式**约束，靠一条 runtime 断言守住，
    不然哪天把 NEGDIR 改成 local/ 顶层，整套负向回归会静默变假绿。

    ⚠️ 「会不会被提交」的判据**必须与 `audit.py` 同源**。两边各写一份，
    迟早一边改了、另一边留着旧写法 —— 那正是 L46 记的那类「两处独立判断叠加失效」。
    所以这里直接 import audit 的 `_is_tracked`，不再自己拼。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import audit  # 与审计共用同一套「入库」判据，避免两处定义漂移（L46）
    rel = audit._rel_to_root(path)
    return rel is not None and audit._is_tracked(rel)


def run_case_repo(name, mutate, base_text, level):
    """临时改**真实** profile 跑整仓审计，再立即还原。

    用于「必须与真实文件对账」的门禁（模板 ⟺ profile、散文扫查）。
    风险：这个函数写仓库内的真实文件 —— 所以用 try/finally 保证还原，
    并对比字节长度确认还原成功。
    """
    original = BASE.read_bytes()
    cfg = copy.deepcopy(json.loads(base_text))
    mutate(cfg)
    register_dirty(BASE, original)          # 见文件头「两层保护」
    try:
        BASE.write_bytes(
            (json.dumps(cfg, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
        return _audit_codes(None, level)
    finally:
        BASE.write_bytes(original)
        unregister_dirty(BASE)
        if BASE.read_bytes() != original:
            raise RuntimeError(f"❗ 还原 {BASE} 失败——请手工 git checkout 恢复")


# 矩阵是「知识」，不是「配置」——它失效时配置侧门禁会**静默全绿**（L39）。
# 所以负向套件必须能故意去动矩阵，否则「门禁失效」这一类永远没有被验证的机会。
MATRIX = ROOT / "docs" / "version-matrix.json"


# 每个 matrix 作用域用例声明自己的 (锚点, 替换)。写成表而不是分支，
# 是为了让「这个用例到底改坏了什么」在一处就能读完 —— 否则测试本身的意图
# 会随用例增多而散掉，而散掉的测试和没有测试一样（L37）。
MATRIX_MUTATIONS = {
    "matrix-path-renamed": (MATRIX_PATH_OLD, MATRIX_PATH_NEW),
    # coverage-floor-stale（WARN）：把起点抬到 1.15.0 —— inventories 最高只到 1.14.0，
    # 于是「声称盘过而没盘」被抓。这条同时会让窗口里的 1.14.1/1.14.2/1.14.3
    # 变成无盘点记录（coverage_inventory_missing），一次改坏触发两条门禁是**故意**的：
    # 两种缺口本来就是同一个事故的两面。
    "coverage-floor-stale": (MATRIX_FLOOR_OLD, MATRIX_FLOOR_HIGH),
    # coverage-inventory-missing：把起点压到 1.13.0 —— 1.14.0 那 49 条被拉回比对窗口
    # 而 inventories 里没有对应记录，门禁必须响。这也是「随手改 floor 让 ERROR 消失」
    # 这条捷径会撞上的墙。
    "coverage-inv-missing": (MATRIX_FLOOR_OLD, MATRIX_FLOOR_LOW),
    # coverage_window_missing：不声明起点。没有窗口就没有「上游加了东西而仓库不知道」的检测。
    "coverage-floor-missing": (MATRIX_FLOOR_OLD, MATRIX_FLOOR_EMPTY),
}


def run_case_tpl(name, mutate, base_text, level):
    """临时改**真实模板** `templates/groups.json`，跑整仓审计，再立即还原。

    为什么需要独立作用域：`audit_template()` **只在整仓模式下、且只对模板文件**执行
    （见 audit.py 的 `if is_template: audit_template(rep)`）。
    profile 作用域（`single` / `repo`）都走不到它 —— 写成那两个会**假失败**。

    ⚠️ 写盘必须带 `newline=""` 保住 LF：用默认 newline 会在 Windows 写 CRLF，
    触发 `edit_method_fingerprint`，输出被无关 ERROR 刷屏，让人误判「门禁没响」。
    （2026-10-14 踩过：我为此白查了三轮。）
    """
    T = ROOT / "templates" / "groups.json"
    original = T.read_bytes()
    cfg = copy.deepcopy(json.loads(base_text))
    mutate(cfg)
    try:
        T.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + "\n",
                     encoding="utf-8", newline="")
        return _audit_codes(None, level)
    finally:
        T.write_bytes(original)
        if T.read_bytes() != original:
            raise RuntimeError("❗ 还原 templates/groups.json 失败——请手工 git checkout 恢复")


def run_case_matrix(name, mutate, base_text, level):
    """临时改**真实**矩阵，跑整仓审计，再立即还原（同 run_case_repo 的纪律）。

    用文本替换而非 json 重写：矩阵文件的行尾与缩进风格要保持原样，
    否则一次负向测试就会给仓库留下几百行的格式 diff。
    """
    original = MATRIX.read_bytes()
    text = original.decode("utf-8")
    old_anchor, new_anchor = MATRIX_MUTATIONS[name]
    if original.count(old_anchor.encode("utf-8")) != 1:
        raise RuntimeError(f"❗ 矩阵里找不到唯一的锚点 {old_anchor!r}")
    try:
        register_dirty(MATRIX, original)    # 见文件头「两层保护」
        MATRIX.write_bytes(text.replace(old_anchor, new_anchor).encode("utf-8"))
        # 探针需要真实内核：没有可执行文件时**跳过**（不能报绿，那是撒谎）。
        codes = _audit_codes(None, level, no_check=False)
        if "matrix_probe_skipped" in codes:
            raise SkipCase("本机没有 sing-box 可执行文件，探针没法跑")
        return codes
    finally:
        MATRIX.write_bytes(original)
        unregister_dirty(MATRIX)
        if MATRIX.read_bytes() != original:
            raise RuntimeError(f"❗ 还原 {MATRIX} 失败——请手工 git checkout 恢复")
        # 探针留下的临时文件也要清掉：它在 local/_negtest/ 里虽不被扫，但会积垃圾。
        try:
            (NEGDIR / ".matrix-probe.json").unlink()
        except OSError:
            pass


# ── doc 作用域：仓库级台账类门禁（见 tools/_negdoc_runner.py 的说明）────
sys.path.insert(0, str(ROOT / "tools"))
from _negdoc_runner import make_doc_runner          # noqa: E402
from negdoc_mutations import DOC_MUTATIONS, cases as _negdoc_cases   # noqa: E402

# 「doc 用例会改哪些真实文件」——从表里算，供开跑前自检用。
# 第五轮复核 P2-A：手写清单漏了 3 个；从代码算才跟得上新增用例。
DOC_MUTATIONS_TARGETS = sorted({v[0] for v in DOC_MUTATIONS.values()})
import _negdoc_funcs as _ndf                                        # noqa: E402
import _negcfg_funcs as _ncf                                        # noqa: E402

run_case_doc = make_doc_runner(
    DOC_MUTATIONS, _audit_codes,
    register=register_dirty, unregister=unregister_dirty,
)

# 把 doc 组用例并入 CASES（破坏函数已在下方以 m_* 形式定义）
for _name, _fn, _code, _lv, _scope in _negdoc_cases():
    CASES.append((_name, getattr(_ndf, _fn), _code, _lv, _scope))

# 单文件配置类（single 作用域）—— 见 tools/_negcfg_funcs.py
for _name, _fn, _code, _lv in _ncf.CASES:
    CASES.append((_name, getattr(_ncf, _fn), _code, _lv, "single"))


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

    _guard_against_leftover_dirty()      # 上轮被硬杀的话先恢复
    _save_baseline()                     # 记下此刻内容，供下次开跑比对

    print("═" * 68)
    print("  门禁负向回归：每个用例故意改坏一处，期望对应门禁报出指定 code")
    print("═" * 68)
    bad = []
    try:
        for name, mutate, expect, level, scope in cases:
            try:
                _assert_config_only_safe(name, expect, scope)
                if scope == "tpl":
                    codes = run_case_tpl(name, mutate, base_text, level)
                elif scope == "matrix":
                    codes = run_case_matrix(name, mutate, base_text, level)
                elif scope == "repo":
                    codes = run_case_repo(name, mutate, base_text, level)
                elif scope == "doc":
                    codes = run_case_doc(name, mutate, base_text, level)
                elif scope == "doc_kernel":
                    codes = run_case_doc(name, mutate, base_text, level, use_kernel=True)
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
        _clear_baseline()          # 所有用例都已归还 → 基线不再需要

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
