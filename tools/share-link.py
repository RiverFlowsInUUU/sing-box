#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""share-link.py —— 分享链接 → sing-box outbound（把铁律 2/3/5 做成代码）

用法：
    python tools/share-link.py 'vless://...'                 # 解一条，打印 outbound JSON
    python tools/share-link.py 'vmess://...' 'ss://...'      # 解多条
    cat links.txt | python tools/share-link.py -             # 从 stdin 批量读（每行一条）

设计动机（见 docs/DRIVER.md 「为什么要有这个脚本」）：
    「分享链接 → outbound」的映射有大量**易错但可机器判定**的细节 ——
    reality 漏写 reality 块、VMess 的 aid 缺省、SS 2022 密码 base64 长度、
    `security=none` 的 vless 不该写 tls、`net=tcp` 不该写 transport、`flow` 只认一个值。
    过去这些靠 AI 现场读 11KB 的 docs/PROTOCOL-MAPPING.md 再手写，
    每一步都是一次赌；现在只要链接格式对，出来的 outbound 就是对的。

    这个脚本**不改任何配置文件**，只做「链接 → 对象」这一件事。
    插进哪份骨架、加进哪个组，是 mknode.py 的事。

输出：
    默认打印一个 JSON 数组（多条时）或对象（单条时），可直接贴进 outbounds[]。
    --pretty  缩进 4 空格（贴近 profiles/ 的排版）
"""

import argparse
import base64
import binascii
import json
import re
import sys
from urllib.parse import parse_qs, unquote, urlparse

# ── 与 audit.py 保持同一套常量（两处行为不同会让人以为「一边能跑一边不能」）──
VALID_SS_METHODS = {
    "none",
    "aes-128-gcm", "aes-192-gcm", "aes-256-gcm",
    "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305",
    "aes-128-ctr", "aes-192-ctr", "aes-256-ctr",
    "aes-128-cfb", "aes-192-cfb", "aes-256-cfb",
    "rc4-md5", "chacha20-ietf", "xchacha20",
}
# 2022 系列的密钥长度（字节）——密码写错长度会 FATAL: decode key: illegal base64
SS2022_KEY_BYTES = {
    "2022-blake3-aes-128-gcm": 16,
    "2022-blake3-aes-256-gcm": 32,
    "2022-blake3-chacha20-poly1305": 32,
}
VMESS_SECURITY = {
    "auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305", "aes-128-cfb",
}
VALID_FLOW = {"xtls-rprx-vision"}


class LinkError(Exception):
    """链接本身有问题（格式不支持 / 解码失败）——报出来，不要猜。"""


# ── 通用小工具 ──────────────────────────────────────────────────────

def _b64(data: str) -> str:
    """宽容的 base64 解码：URL-safe、无 padding、两种变体都试。"""
    s = data.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as ex:
        raise LinkError(f"base64 解不开（已试过补 padding 与 URL-safe 变体）：{ex}")


def _q(query: str) -> dict:
    """query → {key: 第一个值}，键名统一小写（链接里的键名大小写不统一）。"""
    out = {}
    for k, v in parse_qs(query, keep_blank_values=True).items():
        out[k.lower()] = v[0]
    return out


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _tag_of(frag: str, fallback: str) -> str:
    t = unquote(frag or "").strip()
    return t or fallback


def _port(p, raw: str) -> int:
    if p is None:
        raise LinkError(f"链接里没有端口（port={raw!r}）")
    try:
        n = int(p)
    except ValueError:
        raise LinkError(f"端口不是整数：{p!r}")
    if not (0 < n < 65536):
        raise LinkError(f"端口超出范围：{n}")
    return n


def _tls_block(q: dict, host: str, default_alpn=None, force=False):
    """按 query 生成 tls 块。force=True 给 trojan/anytls/hysteria2/tuic 这种必须有 TLS 的协议。"""
    security = (q.get("security") or "").strip().lower()
    if security in ("none", "0", "false") and not force:
        return None
    sni = q.get("sni") or q.get("peer") or q.get("host") or host
    tls = {"enabled": True, "server_name": sni, "insecure": _truthy(q.get("insecure") or q.get("allowinsecure"))}

    fp = (q.get("fp") or "").strip()

    if security == "reality":
        pbk = (q.get("pbk") or "").strip()
        if not pbk:
            raise LinkError("security=reality 但链接里没有 pbk（public_key）——reality 必须有公钥，不能猜")
        # ⚠️ reality **必须**配 uTLS：不写 fp 也要补默认。
        # 实测（1.14.3 真内核）缺 utls 会 `FATAL: initialize outbound[N]: uTLS is required by reality client`。
        # 光看链接里没 fp 就省掉 utls，是一条"链接合法、配置非法"的死路。
        tls["utls"] = {"enabled": True, "fingerprint": fp or "chrome"}
        reality = {"enabled": True, "public_key": pbk}
        sid = (q.get("sid") or "").strip()
        if sid:
            reality["short_id"] = sid
        tls["reality"] = reality
    elif fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}

    alpn = q.get("alpn")
    if alpn:
        tls["alpn"] = [x.strip() for x in alpn.split(",") if x.strip()]
    elif default_alpn:
        tls["alpn"] = list(default_alpn)

    if not fp and security != "reality" and "alpn" in tls and tls["alpn"] == default_alpn:
        pass  # 保留默认 alpn，其余裁掉空字段
    return tls


def _transport(q: dict):
    """按 type/net 生成 transport 块；net=tcp（或空）返回 None。"""
    net = (q.get("type") or q.get("net") or "tcp").strip().lower()
    if net in ("", "tcp", "raw"):
        return None
    path = q.get("path") or "/"
    host = q.get("host") or ""
    if net == "ws":
        tr = {"type": "ws", "path": path}
        if host:
            tr["headers"] = {"Host": host}   # 键名区分大小写，Host 首字母大写
        return tr
    if net == "grpc":
        tr = {"type": "grpc"}
        sn = q.get("servicename") or q.get("service_name") or ""
        if sn:
            tr["service_name"] = sn
        return tr
    if net in ("http", "h2"):
        tr = {"type": "http", "path": path}
        if host:
            tr["host"] = [host]
        return tr
    if net == "httpupgrade":
        tr = {"type": "httpupgrade", "path": path}
        if host:
            tr["host"] = host
        return tr
    if net == "quic":
        return {"type": "quic"}
    raise LinkError(f"不认识的 transport type={net!r}（支持 ws/grpc/http/h2/httpupgrade/quic）")


# ── 逐协议 ──────────────────────────────────────────────────────────

def parse_vless(url: str, frag: str) -> dict:
    u = urlparse(url)
    q = _q(u.query)
    if not u.username:
        raise LinkError("vless:// 里没有 uuid")
    ob = {
        "type": "vless",
        "tag": _tag_of(frag, "vless-node"),
        "server": u.hostname or "",
        "server_port": _port(u.port, url),
        "uuid": unquote(u.username),
    }
    flow = (q.get("flow") or "").strip()
    if flow:
        if flow not in VALID_FLOW:
            # 不悄悄丢弃：链接写了个 sing-box 不认的 flow，用户需要知道
            raise LinkError(
                f"flow={flow!r} 不是合法值（sing-box 只接受空或 {sorted(VALID_FLOW)}）。"
                "如果你确定服务端要 xhttp 之类，那它不属于 flow 字段，请人工确认"
            )
        ob["flow"] = flow
    tls = _tls_block(q, u.hostname or "")
    if tls:
        ob["tls"] = tls
    tr = _transport(q)
    if tr:
        ob["transport"] = tr
    return ob


def parse_vmess(url: str, frag: str) -> dict:
    payload = url[len("vmess://"):].split("#", 1)[0]
    obj = json.loads(_b64(payload))
    if not isinstance(obj, dict):
        raise LinkError("vmess:// 解出来不是 JSON 对象")
    add, port, uid = obj.get("add"), obj.get("port"), obj.get("id")
    if not add or not port or not uid:
        raise LinkError(f"vmess 缺必需字段（add/port/id）：{ {k: obj.get(k) for k in ('add','port','id')} }")
    scy = (obj.get("scy") or "").strip().lower()
    if scy and scy not in VMESS_SECURITY:
        raise LinkError(f"vmess security={scy!r} 不在合法取值里：{sorted(VMESS_SECURITY)}")
    ob = {
        "type": "vmess",
        "tag": _tag_of(frag, obj.get("ps") or "vmess-node"),
        "server": add,
        "server_port": _port(port, str(port)),
        "uuid": uid,
        "security": scy or "auto",
        "alter_id": int(obj.get("aid") or 0),
    }
    if (obj.get("tls") or "").lower() == "tls":
        tls = {"enabled": True, "server_name": obj.get("sni") or obj.get("host") or add}
        if (obj.get("fp") or "").strip():
            tls["utls"] = {"enabled": True, "fingerprint": obj["fp"].strip()}
        if obj.get("alpn"):
            tls["alpn"] = [x.strip() for x in str(obj["alpn"]).split(",") if x.strip()]
        ob["tls"] = tls
    tr = _transport({
        "type": obj.get("net") or "tcp",
        "path": obj.get("path") or "/",
        "host": obj.get("host") or "",
        "servicename": obj.get("path") if (obj.get("net") or "").lower() == "grpc" else "",
    })
    if tr:
        ob["transport"] = tr
    return ob


def parse_trojan(url: str, frag: str) -> dict:
    u = urlparse(url)
    q = _q(u.query)
    if not u.username:
        raise LinkError("trojan:// 里没有 password")
    pw = unquote(u.username)
    if u.password:
        pw = f"{pw}:{unquote(u.password)}"
    return {
        "type": "trojan",
        "tag": _tag_of(frag, "trojan-node"),
        "server": u.hostname or "",
        "server_port": _port(u.port, url),
        "password": pw,
        # trojan 必须带 TLS —— 链接写 security=none 也照样写（sing-box 要求）
        "tls": _tls_block(q, u.hostname or "", force=True),
        **({"transport": _transport(q)} if _transport(q) else {}),
    }


def parse_hysteria2(url: str, frag: str) -> dict:
    u = urlparse(url)
    q = _q(u.query)
    pw = q.get("auth") or unquote(u.username) or (unquote(u.password) if u.password else "")
    if not pw:
        raise LinkError("hysteria2:// 里没有 password/auth")
    ob = {
        "type": "hysteria2",
        "tag": _tag_of(frag, "hy2-node"),
        "server": u.hostname or "",
        "password": pw,
        "up_mbps": 0,
        "down_mbps": 0,
        "tls": _tls_block(q, u.hostname or "", default_alpn=["h3"], force=True),
    }
    mport = (q.get("mport") or "").strip()
    if mport:
        # mport 与 server_port 互斥：端口跳跃写法里 server_port 不该出现
        ob.pop("server_port", None)
        ob["server_ports"] = [mport.replace("-", ":")]
    else:
        ob["server_port"] = _port(u.port, url)
    ob = {"type": ob["type"], "tag": ob["tag"], "server": ob["server"],
          **{k: v for k, v in ob.items() if k in ("server_port", "server_ports")},
          "password": ob["password"], "up_mbps": 0, "down_mbps": 0, "tls": ob["tls"]}
    if (q.get("obfs") or "").strip() == "salamander" and q.get("obfs-password"):
        ob["obfs"] = {"type": "salamander", "password": q["obfs-password"]}
    if q.get("bbr_profile"):
        ob["bbr_profile"] = q["bbr_profile"]
    return ob


def parse_ss(url: str, frag: str) -> dict:
    body = url[len("ss://"):].split("#", 1)[0]
    query = ""
    if "?" in body:
        body, query = body.split("?", 1)
    q = _q(query)

    if "@" in body:
        # SIP002: ss://base64(method:password)@host:port  或  ss://method:password@host:port
        userinfo, hostport = body.rsplit("@", 1)
        if ":" in userinfo and not userinfo.startswith("$"):
            method, _, password = userinfo.partition(":")
            method, password = unquote(method), unquote(password)
        else:
            method, _, password = _b64(userinfo).partition(":")
    else:
        # 旧式: ss://base64(method:password@host:port)
        decoded = _b64(body)
        userinfo, _, hostport = decoded.rpartition("@")
        method, _, password = userinfo.partition(":")
    if not hostport or ":" not in hostport:
        raise LinkError(f"ss:// 里解析不出 host:port（hostport={hostport!r}）")
    host, _, port = hostport.rpartition(":")

    method = method.strip().lower()
    if method not in VALID_SS_METHODS:
        raise LinkError(f"method={method!r} 不在 1.14 正式版合法取值里（见 PROTOCOL-MAPPING §2.5）")

    if method in SS2022_KEY_BYTES:
        expect = SS2022_KEY_BYTES[method]
        try:
            raw = base64.b64decode(password + "=" * (-len(password) % 4))
        except binascii.Error as ex:
            raise LinkError(f"{method} 的密码必须是合法 base64（会 FATAL: decode key）：{ex}")
        if len(raw) != expect:
            raise LinkError(
                f"{method} 需要 {expect} 字节密钥，但解出来是 {len(raw)} 字节"
                f"（会 FATAL: decode key: illegal base64 data）"
            )

    ob = {
        "type": "shadowsocks",
        "tag": _tag_of(frag, "ss-node"),
        "server": unquote(host),
        "server_port": _port(port, port),
        "method": method,
        "password": password,
    }
    if q.get("plugin"):
        ob["plugin"] = q["plugin"]
        if q.get("plugin-opts"):
            ob["plugin_opts"] = q["plugin-opts"]
    return ob


def parse_anytls(url: str, frag: str) -> dict:
    u = urlparse(url)
    q = _q(u.query)
    pw = unquote(u.username) or (unquote(u.password) if u.password else "")
    if not pw:
        raise LinkError("anytls:// 里没有 password")
    return {
        "type": "anytls",
        "tag": _tag_of(frag, "anytls-node"),
        "server": u.hostname or "",
        "server_port": _port(u.port, url),
        "password": pw,
        "tls": _tls_block(q, u.hostname or "", force=True),
    }


def parse_tuic(url: str, frag: str) -> dict:
    u = urlparse(url)
    q = _q(u.query)
    if not u.username or not u.password:
        raise LinkError("tuic:// 需要 uuid:password 形式")
    ob = {
        "type": "tuic",
        "tag": _tag_of(frag, "tuic-node"),
        "server": u.hostname or "",
        "server_port": _port(u.port, url),
        "uuid": unquote(u.username),
        "password": unquote(u.password),
        "congestion_control": q.get("congestion_control") or "bbr",
        "udp_relay_mode": q.get("udp_relay_mode") or "native",
        "tls": _tls_block(q, u.hostname or "", default_alpn=["h3"], force=True),
    }
    if "tls" in ob and ob["tls"] is None:
        ob["tls"] = {"enabled": True, "server_name": u.hostname or "", "alpn": ["h3"]}
    return ob


PARSERS = [
    ("vmess://", parse_vmess),
    ("vless://", parse_vless),
    ("trojan://", parse_trojan),
    ("hysteria2://", parse_hysteria2),
    ("hy2://", parse_hysteria2),
    ("ss://", parse_ss),
    ("anytls://", parse_anytls),
    ("tuic://", parse_tuic),
]


def parse_link(link: str) -> dict:
    link = link.strip()
    if not link:
        raise LinkError("空链接")
    frag = ""
    for prefix, fn in PARSERS:
        if link.lower().startswith(prefix):
            if prefix == "ss://":
                # ss 的 #tag 在 query 之后，交给 parse_ss 自己切
                pass
            elif "#" in link:
                head, _, frag = link.partition("#")
                link = head
            return fn(link, frag)
    raise LinkError(
        "不认识的前缀。支持：vmess / vless / trojan / hysteria2(hy2) / ss / anytls / tuic。"
        "（socks:// 与 http:// 代理请按 PROTOCOL-MAPPING §1 手工写，字段少且不易错）"
    )


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="分享链接 → sing-box outbound（只解码，不写文件）",
        epilog="输出可直接贴进 outbounds[]；插进骨架请用 tools/mknode.py",
    )
    ap.add_argument("links", nargs="*", help="分享链接；给 - 表示从 stdin 逐行读")
    ap.add_argument("--pretty", action="store_true", help="缩进 4 空格")
    ap.add_argument("--ndjson", action="store_true", help="每行一个对象，便于管道")
    args = ap.parse_args()

    raw = []
    if not args.links or args.links == ["-"]:
        raw = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
    else:
        for a in args.links:
            raw.extend([ln for ln in a.splitlines() if ln.strip()])

    if not raw:
        ap.error("没有给链接。用法：python tools/share-link.py 'vless://...'")

    out, bad = [], 0
    for i, link in enumerate(raw, 1):
        try:
            out.append(parse_link(link))
        except LinkError as ex:
            bad += 1
            print(f"[E] 第 {i} 条：{ex}", file=sys.stderr)
        except Exception as ex:  # JSON 解析失败之类，也不要吞
            bad += 1
            print(f"[E] 第 {i} 条：{type(ex).__name__}: {ex}", file=sys.stderr)

    if not out:
        return 1

    indent = 4 if args.pretty else None
    if args.ndjson:
        for o in out:
            print(json.dumps(o, ensure_ascii=False, indent=indent))
    elif len(out) == 1:
        print(json.dumps(out[0], ensure_ascii=False, indent=indent))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=indent))

    if bad:
        print(f"\n[batch] {len(out)} 成 / {bad} 败", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
