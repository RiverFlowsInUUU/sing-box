# DECISIONS.md — 决策记录（谁、什么时候、为什么）

> **这份文件记录「我们选了 A 而不是 B」以及理由。**
> 与之分工：
> - `docs/VERSION-MATRIX.md` / `version-matrix.json` = **机器的答案**（`adopt` 值，门禁据此验配置）
> - `docs/LESSONS.md` = **踩过的坑**（事故 → 根因 → 门禁）
> - **本文件 = 人的理由**。矩阵只存一行 `reason`，写不下背景、备选方案、代价权衡；
>   升级后回头看「当初为什么不用 MASQUE」时，答案在这里。
>
> 矩阵里每条 `kind: "new"` 都必须在本文件有对应的 **D<n>** 条目。
> `tools/audit.py` 的 `audit_decisions()` 会做双向校验：矩阵条目 ↔ 本文件条目。

---

## 记录格式

```
## D<n> <标题>
- **日期**：YYYY-MM-DD
- **触发**：哪个上游版本 / 哪次用户提问
- **决策**：启用 / 不启用 / 必须跟随（对应矩阵里的 adopt）
- **矩阵 ID**：`new_xxx`（**基础设施类决策不属于任何新功能，写「（基础设施类，不进矩阵）」**）
- **为什么**：（3-5 行，必须能说服半年后的自己）
- **备选方案**：（考虑过但没选的，以及为什么没选；没有就写「无」）
- **前提 / 风险**：（这个决策依赖什么假设，什么情况下该重新评估）
```

> 本文件不只记“上游新功能”。**任何“选了 A 没选 B”的决策都该记在这里**（门禁设计、
> 目录约定、流程取舍……）—— 判据是“半年后有人问「当初为什么不那样做」时，答案在哪里”。
> 只有新功能那类需要反向在矩阵里建 `kind: "new"` 条目；基础设施类写「（基础设施类，不进矩阵）」即可，
> `audit_decisions()` 只校验 `new_` 开头的 ID，不会误拦。

---

## D1 sing-tun 自带 TCP/IP 栈 —— 必须跟随

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0（changelog: *Significantly improve TUN performance with a new TCP/IP stack*）
- **决策**：**必须跟随**（`adopt: "must"`）
- **矩阵 ID**：`new_tun_sing_tun_stack`
- **为什么**：这不是「要不要开」的问题。1.15 起 sing-tun 使用自己的 TCP/IP 栈，官方称峰值性能、
  能耗、内存三项均显著改善；**启用方式就是删掉 `tun.stack` 字段**（官方 migration 示例里
  `address` 与 `mtu` 都不动）。1.15/1.16 上写不写 `stack` 都能跑，**1.17.0 起保留即 FATAL**。
  既然迟早要删、删了只有好处，就没有「不启用」这个选项。
- **备选方案**：无。留着 `stack` 等于主动选择 1.17 启动失败。
- **前提 / 风险**：⚠️ 唯一风险点是 **`mtu`**。本仓库 tun 写的是 `mtu: 9000`，
  而官方对比表用的是 1500 / 4064 / 65535；换栈后 `mtu` 取值是否仍合适，**须在 1.15 正式版文档
  确认后再定**。已登记到矩阵条目的 `reason` 里。

---

## D2 Android `auto_redirect` 全功能支持 —— 不启用

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.1（*Implement fully functional auto_redirect for Android*）
- **决策**：**不启用**（`adopt: "no"`）
- **矩阵 ID**：`new_tun_auto_redirect_android`
- **为什么**：1.15 起 Android 上 `auto_redirect` 通过图形客户端的 **root 服务或 root shell**
  才全功能可用。本仓库的三份配置走的是 VpnService / 系统 TUN，**不需要 root、也不假设用户有 root**。
  引入它会把「装上就能用」变成「先 root」。
- **备选方案**：无。
- **前提 / 风险**：本仓库若将来要支持 root 用户绕过 VpnService 的转发开销，可以重新评估。
  届时须在真机上验证（本机受铁律 11 限制，无法验证）。

---

## D3 `on_demand` endpoint 选项 —— 不启用

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.1（*Add on_demand endpoint option*）
- **决策**：**不启用**（`adopt: "no"`）
- **矩阵 ID**：`new_endpoint_on_demand`
- **为什么**：该选项作用于 **endpoint**（WireGuard / Tailscale / OpenVPN Client / OpenConnect）。
  本仓库**一个 endpoint 都不用** —— 节点全是 outbound（vless / vmess / trojan / hysteria2 / ss / anytls / tuic）。
  没有 endpoint，这个字段无处可写。
- **备选方案**：无。
- **前提 / 风险**：若将来给仓库加 WireGuard 类节点（那会变成 endpoint），此决策需重新评估。

---

## D4 cache file 写缓冲 —— 不启用（但默认已生效）

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.1（*Add cache file write buffering*）
- **决策**：**不写字段**（`adopt: "no"`，`path: experimental.cache_file.buffer_size`）
- **矩阵 ID**：`new_cache_file_write_buffering`
- **为什么**：写缓冲的**好处已经在内核内部默认生效**（默认 1MB）。这个新功能给的是一个
  **调参开关**（`buffer_size` / `flush_interval`），不是「开/关某能力」。本仓库的 cache 只有
  DNS 记录与规则集元数据，量极小，调缓冲参数没有可测量的收益，反而多两个字段要维护。
- **备选方案**：显式写 `buffer_size` —— 放弃，理由如上（无收益）。
- **前提 / 风险**：无。若将来 cache 写入成为瓶颈（如启用大量 RDRC 记录），可重新评估。

---

## D5 Tailcat 出入站、MASQUE endpoint、NaiveProxy 版本 —— 不启用

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.5 / alpha.7 / alpha.9
- **决策**：**不启用**（`adopt: "no"`）
- **矩阵 ID**：`new_tailcat_inbound_outbound`、`new_masque_endpoints`、`new_naiveproxy_version_bump`
- **为什么**：三条理由同源 —— **本仓库手上没有对应的服务端**。
  - **Tailcat**（Tailscale 数据面）：需要 Tailscale 网络与控制面配套，本仓库面向单机上网代理。
  - **MASQUE**（HTTP CONNECT-IP）：新增协议，用户的节点是 vless/vmess/trojan/hysteria2/ss/anytls/tuic，无 MASQUE。
  - **NaiveProxy 版本更新**：这是**内核内部组件版本号**的升级，不是可配置项。用户**无法**通过配置
    「启用」或「不启用」它 —— 它随内核版本自动生效。列进矩阵的目的是**记录我们知道这件事**，
    避免它被当成「漏掉的新功能」反复报警。
- **备选方案**：无。
- **前提 / 风险**：若用户将来提供 MASQUE / Tailscale 服务端，前两条需重新评估。

---

## D6 TLS 整证书 SHA-256 固定 —— 不启用

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.7（*Add full certificate pinning for TLS*）
- **决策**：**不启用**（`adopt: "no"`）
- **矩阵 ID**：`new_tls_certificate_sha256_pinning`
- **为什么**：这是「在既有公钥固定之外，新增整证书哈希固定」。**本仓库的节点由用户随时更换、
  证书会轮换**（Let's Encrypt 90 天自动续期）。钉死证书哈希的直接后果是：节点续期证书后
  **连接直接失败**，且报错是 TLS 层的、不易与「节点挂了」区分。收益（防中间人）在这个使用场景
  （自己搭的、已知的服务器）近乎为零，代价（换证书即断线）却是确定的。
- **备选方案**：只在用户明确要求「钉死某个固定节点证书」时，作为**单节点临时配置**启用。
  不进 `profiles/` 模板。
- **前提 / 风险**：无。

---

## D7 `dns_server_address` / `dns_search_domain` 规则项 —— 不启用

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.8
- **决策**：**不启用**（`adopt: "no"`）
- **矩阵 ID**：`new_dns_server_address_rule_item`
- **为什么**：这两个规则项用来匹配「系统 / DHCP / VPN 下发给本机的 DNS 服务器地址与搜索域」，
  典型用途是企业内网 / 分域环境做条件分流。本仓库的 DNS 已经按**域名**分流
  （`geosite-cn` → 国内 DNS、其余 → 代理 DNS），不走「按系统 DNS 地址」这条路。
- **备选方案**：无。
- **前提 / 风险**：若将来要适配「公司内网 DNS + 公网分流」场景，可重新评估。

---

## D8 HTTP 出站 `version` 选项 —— 不启用（默认行为已生效）

- **日期**：2026-10-12
- **触发**：sing-box 1.15.0-alpha.7（*Add HTTP/2, HTTP/3 and UDP support for HTTP proxy*）
- **决策**：**不写字段**（`adopt: "no"`，`path: outbounds[type=http].version`）
- **矩阵 ID**：`new_http_outbound_version`
- **为什么**：1.15 重写 HTTP 代理：**默认改用 HTTP/2 并自动回退 HTTP/1.1**（带 `path` 或 `Host`
  头时仍用 HTTP/1.1）。也就是说**好处默认就有**，而 `version` 是「强制指定某一版」的锁。
  显式写 `version` 反而会**锁死协商结果**，失去自动回退能力。本仓库目前也不用 HTTP 出站。
- **备选方案**：显式写 `version: "h2"` —— 放弃，会失去回退。
- **前提 / 风险**：若将来遇到「服务端只支持 h3」的极端场景，可单点指定。

---

## D9 仓库防泄漏门禁：把“真实节点不进仓”从铁律变成机器能拦的事实（基础设施决策）

- **日期**：2026-10-12
- **触发**：`ec5d300` 泄漏事故（L18 的证据文档把节点域名与它的 A/AAAA 记录一起推到了公开仓库）
- **决策**：**新建 `audit_redaction()` 门禁** —— 按 `git ls-files` 扫**全部被跟踪文件**，
  发现未审阅的公网 IP 即报 ERROR。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：铁律 7 写的是「仓库里不放真实节点」，但当时唯一的防泄漏门禁 `placeholder_server`
  **只管 `profiles/` 目录里的 JSON 字段** —— 而这次泄漏发生在 `docs/` 的散文里。
  所有门禁都是“按字段”审的，**散文没人管**。道理很硬：**门禁的作用域必须与铁律的作用域一致**，
  否则一个缺口就能让整条铁律形同虚设。另外，事后才发现 force-push 只重置分支指针，
  旧对象仍可按 SHA 直取 —— 依赖“事后补救”远比“事前拦住”昂贵。
- **备选方案**：
  - 只靠铁律 7 的人工自觉 —— 已失败一次。
  - 只扫 `docs/evidence/`（事故发生的目录）—— 治标：事故可以发生在任何文件。
  - 用 hook / CI 强制脱敏 —— 仓库已有 CI，但 hook 本地不可见且容易被绕过；
    门禁整合到已存在的 `audit.py`，与其它 8 类检查同进同出、同一退出码，最省心。
- **前提 / 风险**：
  - 依赖 `git ls-files`（非 git 工作区会跳过并给 INFO，不报错）。
  - 白名单需人工维护（`PUBLIC_IP_WHITELIST`）；新增公用地址（如新的公共 DNS）时要补一行，
    否则会误报 —— **宁可误报也不愿漏报**。
  - IPv6 只扫 `2000::/3`（全球单播）：真实节点地址只会落在这里；
    上游文档里的保留段示例（`8000::/1`）不扫，避免误报。

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-12 | 建档；记录 D1–D8（对应 1.15.0 的 10 条新功能） |
| 2026-10-12 | 新增 D9（防泄漏门禁，基础设施决策，事故：`ec5d300`） |
