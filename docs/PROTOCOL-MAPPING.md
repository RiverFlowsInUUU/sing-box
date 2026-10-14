# PROTOCOL-MAPPING.md — 分享链接 → sing-box outbound 映射表

> 目标：任何 AI 拿到用户给的节点链接，都能**不猜字段**地写出 sing-box 正式版可用的 outbound。
> 所有字段名均以 `sing-box schema`（本机导出的 `docs/schema.json`）为准，未出现在 schema 的字段一律不写。

## 0. 通用骨架

任何节点出站都是这六件的组合：

```jsonc
{
  "type":  "<协议名，见下>",
  "tag":   "<唯一名称，中文/emoji 都可，但要与分流组引用一致>",
  "server": "<域名或 IP>",
  "server_port": <整数>,
  "<凭据字段>": "<uuid / password / method…>",
  "tls": { },          // 仅在该协议需要 TLS 时出现
  "transport": { },    // 仅 vless/vmess/trojan 的 ws/grpc/http/httpupgrade
  "multiplex": { }     // 可选，一般不要写
}
```

**不要写** `domain_resolver`（除非用户明确要求指定 DNS 解析服务器）。
**不要写** `"udp": true` —— 1.11.0 起该字段已不存在，UDP 由规则与 `network` 控制。
**不要写** `"tfo"` —— 已更名为 `tcp_fast_open`。

### 通用可选字段（Dial Fields，所有节点都能用）

`connect_timeout`（duration，如 `"10s"`）、`tcp_fast_open`、`tcp_multi_path`、`detour`、
`bind_interface`、`routing_mark`、`network_strategy`、`network_type`。

---

## 1. 分享链接的分发识别

| 前缀 | 协议 | 编码方式 |
|------|------|----------|
| `vmess://` | VMess | 后面整段 **base64**，解出来是 JSON |
| `vless://` | VLESS | URI 形式：`vless://<uuid>@<host>:<port>?<query>#<tag>` |
| `trojan://` | Trojan | `trojan://<password>@<host>:<port>?<query>#<tag>` |
| `hysteria2://` / `hy2://` | Hysteria2 | `hysteria2://<password>@<host>:<port>?<query>#<tag>`（`auth` 参数也当 password） |
| `ss://` | Shadowsocks | 两种：`ss://base64(method:password)@host:port#tag` 或 `ss://base64(method:password@host:port)#tag` |
| `anytls://` | AnyTLS | `anytls://<password>@<host>:<port>?<query>#<tag>` |
| `tuic://` | TUIC | `tuic://<uuid>:<password>@<host>:<port>?<query>#<tag>` |
| `socks://` / `socks5://` | SOCKS | `socks5://<user>:<pass>@host:port#tag` |
| `http(s)://` | HTTP 代理 | 同上 |

**解码注意**：base64 可能是 URL-safe（`-_`）或无 padding。解码时先补 `=` 到 4 的倍数，
再把 `-_` 换成 `+/`；两种都试一遍。解出的 `#tag` 要 **URL decode**。

---

## 2. 逐协议映射

### 2.1 VLESS（`vless://`）

链接 query 常见键：`type`(network)、`security`、`sni`、`fp`、`pbk`、`sid`、`flow`、`path`、`host`、`serviceName`、`alpn`、`encryption`。

```jsonc
{
  "type": "vless",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": 443,
  "uuid": "<uuid>",
  "flow": "xtls-rprx-vision",          // 仅当链接 flow=xtls-rprx-vision
  "tls": {
    "enabled": true,
    "server_name": "<sni 或 host>",
    "insecure": false,
    "utls": { "enabled": true, "fingerprint": "chrome" },   // fp=chrome
    "reality": {                                            // security=reality
      "enabled": true,
      "public_key": "<pbk>",
      "short_id": "<sid>"
    },
    "alpn": ["h2", "http/1.1"]
  },
  "transport": { }                     // 见 §2.6，仅 type != tcp 时写
}
```
- `security=none` → **不写 `tls` 块**。
- `security=tls` → 写 `tls.enabled: true`，**不写 `reality`**。
- `security=reality` → `tls.enabled: true` + `reality` 块（`public_key` 必填）。
- `encryption` 参数：**忽略**（sing-box 无此字段）。
- `flow=xhttp` 之类非法值不要写进 `flow`；`flow` 只接受空或 `xtls-rprx-vision`。
- 缺 `sni` 时 `server_name` 用链接里的 host。

### 2.2 VMess（`vmess://`）

base64 解出的 JSON 字段名是 v2rayN 的：`v` `ps` `add` `port` `id` `aid` `scy` `net` `type` `host` `path` `tls` `sni` `alpn` `fp`。

```jsonc
{
  "type": "vmess",
  "tag": "<ps 或 tag>",
  "server": "<add>",
  "server_port": <port>,
  "uuid": "<id>",
  "security": "auto",                  // 来自 scy；取值 auto|none|zero|aes-128-gcm|chacha20-poly1305|aes-128-cfb
  "alter_id": 0,                       // 来自 aid，整数
  "tls": { "enabled": true, "server_name": "<sni 或 host>" },   // 仅 tls=tls
  "transport": { }                     // 见 §2.6，仅 net != tcp
}
```
- `scy`=空或 `auto` → 写 `"auto"`。
- `aid` 缺省 → 写 `0`。
- `tls` 为 `""` 或缺失 → 不写 `tls` 块。

### 2.3 Trojan（`trojan://`）

```jsonc
{
  "type": "trojan",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": 443,
  "password": "<password>",
  "tls": { "enabled": true, "server_name": "<sni 或 host>" },
  "transport": { }                     // 见 §2.6
}
```
- Trojan **必须带 TLS**；链接里 `security=none` 也照样写 `tls.enabled: true`（sing-box 要求）。

### 2.4 Hysteria2（`hysteria2://` / `hy2://`）

query 常见键：`sni`、`insecure`、`obfs`、`obfs-password`、`pinSHA256`、`alpn`、`mport`（端口跳跃）。

```jsonc
{
  "type": "hysteria2",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": <port>,
  "password": "<password>",
  "up_mbps": 0,                        // 0 = 启用 BBR 而不是 Hysteria CC
  "down_mbps": 0,
  "obfs": { "type": "salamander", "password": "<obfs-password>" },   // 仅 obfs=salamander
  "tls": {
    "enabled": true,
    "server_name": "<sni 或 host>",
    "insecure": false,                 // insecure=1 时为 true
    "alpn": ["h3"]
  }
}
```
- `mport=20000-30000`（或 `1000:2000`）→ 用 `"server_ports": ["20000:30000"]` **替代** `server_port`（二者互斥）。
- `obfs=none` 或缺失 → 不写 `obfs`。
- 官方客户端把 `user:pass` 合并当密码；sing-box 不做别名，**直接把整串写进 `password`**。
- 可选 `"bbr_profile": "standard"`（1.14.0+，取值 `standard|conservative|aggressive`），非必需。

### 2.5 Shadowsocks（`ss://`）

```jsonc
{
  "type": "shadowsocks",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": <port>,
  "method": "<method>",
  "password": "<password>"
}
```
- `method` 合法值（1.14 正式版，enum 全量）：
  `none` `aes-128-gcm` `aes-192-gcm` `aes-256-gcm` `chacha20-ietf-poly1305` `xchacha20-ietf-poly1305`
  `2022-blake3-aes-128-gcm` `2022-blake3-aes-256-gcm` `2022-blake3-chacha20-poly1305`
  `aes-128-ctr` `aes-192-ctr` `aes-256-ctr` `aes-128-cfb` `aes-192-cfb` `aes-256-cfb`
  `rc4-md5` `chacha20-ietf` `xchacha20`
- **2022 系列**的 password 必须是合法 base64 且长度匹配（128 位=16 字节 → 24 字符含 `==`）。
  写错会 FATAL：`initialize outbound[...]: decode key: illegal base64 data`。
- SIP002 的 `plugin` 参数 → 写 `"plugin"` + `"plugin_opts"`（如 `v2ray-plugin` / `obfs-local`）。

### 2.6 AnyTLS（`anytls://`）

```jsonc
{
  "type": "anytls",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": <port>,
  "password": "<password>",
  "tls": { "enabled": true, "server_name": "<sni 或 host>", "insecure": false }
}
```
- AnyTLS 自 **1.12.0** 起提供，必须带 TLS。

### 2.7 TUIC（`tuic://`）

```jsonc
{
  "type": "tuic",
  "tag": "<tag>",
  "server": "<host>",
  "server_port": <port>,
  "uuid": "<uuid>",
  "password": "<password>",
  "congestion_control": "bbr",         // cubic | new_reno | bbr
  "udp_relay_mode": "native",          // native | quic
  "tls": { "enabled": true, "server_name": "<sni>", "alpn": ["h3"] }
}
```

### 2.8 传输层（vless / vmess / trojan 的 `transport`）

由链接的 `type`(net) 决定，**`net=tcp` 时不写 `transport` 块**：

| 链接 `type` | `transport` |
|---|---|
| `ws` | `{"type":"ws","path":"<path>","headers":{"Host":"<host>"}}` |
| `grpc` | `{"type":"grpc","service_name":"<serviceName>"}` |
| `http` / `h2` | `{"type":"http","host":["<host>"],"path":"<path>"}` |
| `httpupgrade` | `{"type":"httpupgrade","host":"<host>","path":"<path>"}` |
| `quic` | `{"type":"quic"}` |

`headers` 里的键名区分大小写，`Host` 首字母大写。
`tls` 的 `server_name` 与 `transport.host` 要一致（除非链接明确不同）。

---

## 3. 插入分流组（用户指定落点）

三个组位置固定，**代理组与智能组都是 urltest**（不再有单独的 `Auto` 组）：

```jsonc
{ "type": "urltest", "tag": "🚀 Proxy", "outbounds": ["Node-01", "..."],
  "url": "http://www.gstatic.com/generate_204", "interval": "3m", "tolerance": 100 }
{ "type": "urltest", "tag": "🤖 AI",    "outbounds": ["Node-01", "Node-04"],
  "url": "http://www.gstatic.com/generate_204", "interval": "3m", "tolerance": 100 }
{ "type": "selector", "tag": "🚫 AD",   "outbounds": ["block"], "default": "block" }
```

- 用户说"放代理组" → 把新节点 tag 加进 `🚀 Proxy.outbounds`。它是 urltest，加进去就等于加进自动测速。
- 用户说"放智能组" → 加进 `🤖 AI.outbounds`。它也是 urltest，只放用户想给 AI 用的节点（例如全部台湾节点）；
  **不要把代理组放进智能组的 `outbounds`** —— urltest 里嵌 urltest 会串联两次测速，两个组结果几乎一样，智能组就失去意义。
- **去广告组只放 `block`，永远不把代理节点放进去。**
- tag 一旦被规则集/规则引用就不能随便改名：`🚀 Proxy` `🤖 AI` `🚫 AD` `direct` `block` 是保留名。
- `route.final` 固定指向 `🚀 Proxy`，即全局兜底走 urltest 优选。
- `route.auto_detect_interface` **必须是 `true`**，否则流量回灌 tun（见 `EXPERIENCES.md` 的「三层问题模型」）。

## 4. 常见解码坑

| 现象 | 原因 | 处理 |
|---|---|---|
| base64 解不开 | URL-safe 变体 / 缺 padding | 补 `=`，把 `-_` 换 `+/`，两种都试 |
| `unknown field "udp"` | 老写法 | 删掉，UDP 不是节点字段 |
| `unknown field "tfo"` | 老写法 | 改 `tcp_fast_open` |
| `decode key: illegal base64` | SS 2022 密码长度/base64 不对 | 核对方法对应密钥长度 |
| `invalid public_key` | reality `pbk` 抄错 | 原样复制，别加空格 |
| 有 TLS 但握手失败 | `security=reality` 漏写 `reality` 块 | 补 `reality.enabled/public_key` |
| **配置合法、`check` 过、启动无 FATAL，但节点始终连不上** | 服务端是**自签证书**（如自建 Zoraxy / 反代），而 `tls.insecure` 是默认的 `false` —— `share-link.py` 只从链接 query 的 `insecure`/`allowinsecure` 取值，**手工写的 `http://` 代理没有任何地方承载这个信息** | 在节点的 `tls` 里显式写 `"insecure": true`。判断依据：`openssl s_client -connect <host>:443` 看 `issuer` 是否等于 `subject`（自签）；或直接看 sing-box 日志有无 `x509: certificate signed by unknown authority` |
| `http_client is conflict with deprecated download_detour` | 两者同时存在 | 删 `download_detour`，只用 `http_client` |
| 手机上能启动、但节点全无延迟 / 只有上传没下载 / 内存爆 1GB | 缺 `route.auto_detect_interface: true`，出站回灌 tun | 在 `route` 里加 `"auto_detect_interface": true` |

## 5. 自检清单（写完 outbound 后逐条过）

1. `type` 在 schema 的 Outbound oneOf 里（`vless` `vmess` `trojan` `hysteria2` `shadowsocks` `anytls` `tuic` `socks` `http` `ssh` `shadowtls` `hysteria` `tor` `direct` `block` `selector` `urltest` `naive` `cloudflared` `bridge` `openvpn` `openconnect` …）
2. 所有字段名都能在 `docs/schema.json` 的对应 `$defs` 里找到
3. `server` / `server_port` / 凭据三项齐全
4. TLS 需求满足（trojan/anytls/hysteria2/tuic 必须有；vless 看 `security`）
   - **自签证书**的服务端必须显式 `"insecure": true`；写了 `insecure: false` 而服务端自签 ⇒ 语法全绿但**永远连不上**（上面坑表第 6 行）
5. 没有 `udp` / `tfo` / `domain_strategy` 这类老字段
6. tag 无重复、已加入目标分流组的 `outbounds`（代理组是 urltest，加进去即自动测速）
7. 跑 `python tools/audit.py <profile> --platform <p> --check` 全绿
