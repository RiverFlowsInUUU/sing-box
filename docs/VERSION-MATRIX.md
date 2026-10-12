# VERSION-MATRIX.md — 字段生命周期总表

> **本文件由 `tools/gen-docs.py` 从 `docs/version-matrix.json` 生成，请勿手改。**
> 要改内容请改 JSON，然后运行 `python tools/gen-docs.py`。

`tools/audit.py` 读的就是那份 JSON；本文件只是给人看的快照。

## 怎么用这张表

- **废弃中**：当前正式版仍能用，但官方已宣布将来移除 → 新写的配置不要再用。
- **已移除**：用即 `FATAL`，配置起不来 → 必须按「替代写法」改。
- **平台限制**：字段本身合法，但目标客户端没实现 → `sing-box check` 不会报错，要靠人看。
- **语义变更**：字段名没变但默认行为变了 → 不报错，容易悄悄出错。
- **新功能采纳**：上游新增的能力 → **没有默认答案**；本仓库必须逐条写下「启用 / 不启用 / 必须跟随」与理由，留空即门禁 ERROR。

## 一、按移除版本排序（越靠前越紧急）

> 本表只含「存量字段的命运」（废弃/移除/平台/语义）；**新功能的采纳决策见第二节**。

| 移除版本 | 废弃版本 | 类别 | 字段 | 替代写法 |
|---|---|---|---|---|
| 1.6.0 | 1.5.0 | 已移除 | `outbounds[].type = shadowsocksr` | 无（sing-box 已不支持 SSR） |
| 1.11.0 | 1.10.0 | 已移除 | `**.rule_set_ipcidr_match_source` | rule_set_ip_cidr_match_source |
| 1.12.0 | 1.8.0 | 已移除 | `experimental.clash_api.cache_file` | experimental.cache_file |
| 1.12.0 | 1.8.0 | 已移除 | `route.rules[].geoip` | rule_set 引用 geoip 规则集 |
| 1.12.0 | 1.8.0 | 已移除 | `route.rules[].geosite` | rule_set 引用 geosite 规则集 |
| 1.12.0 | 1.10.0 | 已移除 | `inbounds[type=tun].inet4_address` | address（数组） |
| 1.12.0 | 1.10.0 | 已移除 | `inbounds[type=tun].inet6_address` | address（数组） |
| 1.13.0 | 1.11.0 | 已移除 | `outbounds[type=direct].override_address` | route.rules[].action = route-options + override_address |
| 1.13.0 | 1.11.0 | 已移除 | `outbounds[type=direct].override_port` | route.rules[].action = route-options + override_port |
| 1.13.0 | 1.12.0 | 已移除 | `**.tls.ech.**` | 无（改用标准库 ECH） |
| 1.13.0 | 1.11.0 | 已移除 | `inbounds[].domain_strategy` | route.rules[].action = resolve + strategy |
| 1.13.0 | 1.11.0 | 已移除 | `inbounds[].sniff` | route.rules[].action = sniff |
| 1.13.0 | 1.11.0 | 仅存档 | `legacy_special_outbounds` | rule action |
| 1.13.0 | 1.11.0 | 已移除 | `inbounds[type=tun].gso` | 直接删除 |
| 1.13.0 | 1.11.0 | 已移除 | `outbounds[].type = wireguard` | endpoints[].type = wireguard |
| 1.14.0 | 1.12.0 | 已移除 | `dns.servers[].address` | dns.servers[].type + dns.servers[].server |
| 1.16.0 | 1.14.0 | 废弃中 | `dns.rules[].strategy` | 把 strategy 移到 DNS server 定义里 |
| 1.16.0 | 1.14.0 | 废弃中 | `dns.rules[].ip_cidr` | match_response + 在 DNS server 上写地址过滤 |
| 1.16.0 | 1.14.0 | 废弃中 | `dns.rules[].ip_is_private` | match_response 版 ip_is_private |
| 1.16.0 | 1.12.0 | 废弃中 | `dns.rules[].outbound` | 在 DNS server 上加 dial fields（如 detour / domain_resolver） |
| 1.16.0 | 1.14.0 | 废弃中 | `route.rule_set[].download_detour` | route.rule_set[].http_client |
| 1.16.0 | 1.14.0 | 语义变更 | `remote_rule_set_without_http_client` | 显式配置顶层 http_clients + route.default_http_client |
| 1.16.0 | 1.14.0 | 废弃中 | `dns.independent_cache` | 直接删除（DNS 缓存行为已统一） |
| 1.16.0 | 1.14.0 | 废弃中 | `dns.rules[].rule_set_ip_cidr_accept_empty` | response matching（match_response） |
| 1.16.0 | 1.14.0 | 废弃中 | `experimental.cache_file.store_rdrc` | experimental.cache_file.store_dns |
| 1.16.0 | 1.14.0 | 废弃中 | `**.tls.acme` | certificate provider（configuration/certificate/ + tls.certificate_provider） |
| 1.17.0 | 1.15.0 | 废弃中 | `inbounds[type=tun].stack` | 直接删除 stack，使用 sing-tun 自带 TCP/IP 栈 |
| — | 1.11.0 | 语义变更 | `empty_direct_as_download_detour` | 给下载用的 direct 出站加 domain_resolver（或 bind_interface / inet4_bind_address / routing_mark 等），或改走 Proxy；只写 {"type":"direct","tag":"direct"} 的空 direct 不能作为规则集下载 detour |
| — | — | 平台限制 | `**.process_path` | 移动端不可用 |
| — | — | 平台限制 | `**.process_name` | 在移动端改用 package_name / include_package / exclude_package |
| — | — | 平台限制 | `inbounds[type=tun].strict_route` | 删除该字段（移动端未实现） |
| — | — | 平台限制 | `**.user_id` | Android 用 package_name；Apple 仅 macOS 独立版/iOS 越狱版可用 |

## 二、新功能采纳决策（kind=new）

> 上游新增的能力**不带默认答案**。本仓库的铁律是：每个新功能都必须显式写下
> 「启用 / 不启用 / 必须跟随」与理由，否则 `tools/audit.py` 直接 ERROR。
> 升级前先看 `python tools/upgrade-check.py` 报告的第 5 节，它会列出还没做决策的新功能。

| 决策 | 自版本 | 决策截止 | 条目 | 说明 |
|---|---|---|---|---|
| 不启用 | 1.15.0 | — | `new_cache_file_write_buffering` | cache_file 写缓冲（buffer_size / flush_interval） |
| 不启用 | 1.15.0 | — | `new_dns_server_address_rule_item` | route/dns 规则项 dns_server_address 与 dns_search_domain |
| 不启用 | 1.15.0 | — | `new_endpoint_on_demand` | endpoint 的 on_demand 选项（WireGuard / Tailscale / OpenVPN / OpenConnect） |
| 不启用 | 1.15.0 | — | `new_http_outbound_version` | HTTP 出入站支持 HTTP/2、HTTP/3 与 UDP（version / disable_version_fallback） |
| 不启用 | 1.15.0 | — | `new_masque_endpoints` | MASQUE 客户端/服务端 endpoint（HTTP CONNECT-IP） |
| 不启用 | 1.15.0 | — | `new_naiveproxy_version_bump` | NaiveProxy 组件版本更新 |
| 不启用 | 1.15.0 | — | `new_tailcat_inbound_outbound` | Tailcat 出入站（Tailscale 数据面） |
| 不启用 | 1.15.0 | — | `new_tls_certificate_sha256_pinning` | TLS 整证书 SHA-256 固定（certificate_sha256 / client_certificate_sha256） |
| 不启用 | 1.15.0 | — | `new_tun_auto_redirect_android` | Android auto_redirect 全功能支持 |
| 必须跟随 | 1.15.0 | 1.17.0 | `new_tun_sing_tun_stack` | sing-tun 自带 TCP/IP 栈（取代 tun.stack） |

决策含义：

- **必须跟随**：旧写法被取代，不是「要不要开」而是「旧字段要删」（通常配套一条 `removed` 条目）。
- **启用**：功能已采纳，配置里应当有对应字段（矩阵里写 `expect: present`，门禁会验）。
- **不启用**：明确放弃，配置里必须**没有**该字段（矩阵里写 `expect: absent`，门禁会验）。

## 三、本次锁定的正式版视角

锁定版本：**1.14.3**

### 在 1.14.3 下**已废弃但还没移除**的字段（新配置一律别用）

- `dns.rules[].strategy` — 将于 **1.16.0** 移除；改用：把 strategy 移到 DNS server 定义里
- `dns.rules[].ip_cidr` — 将于 **1.16.0** 移除；改用：match_response + 在 DNS server 上写地址过滤
- `dns.rules[].ip_is_private` — 将于 **1.16.0** 移除；改用：match_response 版 ip_is_private
- `dns.rules[].outbound` — 将于 **1.16.0** 移除；改用：在 DNS server 上加 dial fields（如 detour / domain_resolver）
- `route.rule_set[].download_detour` — 将于 **1.16.0** 移除；改用：route.rule_set[].http_client
- `remote_rule_set_without_http_client` — 将于 **1.16.0** 移除；改用：显式配置顶层 http_clients + route.default_http_client
- `dns.independent_cache` — 将于 **1.16.0** 移除；改用：直接删除（DNS 缓存行为已统一）
- `dns.rules[].rule_set_ip_cidr_accept_empty` — 将于 **1.16.0** 移除；改用：response matching（match_response）
- `experimental.cache_file.store_rdrc` — 将于 **1.16.0** 移除；改用：experimental.cache_file.store_dns
- `**.tls.acme` — 将于 **1.16.0** 移除；改用：certificate provider（configuration/certificate/ + tls.certificate_provider）

## 四、完整明细（含说明与官方链接）

### `clash_api_cache_file`

- 类别：已移除
- 废弃于：1.8.0
- 移除于：1.12.0
- 字段路径：`experimental.clash_api.cache_file`
- 替代写法：experimental.cache_file
- 官方：https://sing-box.sagernet.org/deprecated/#cache-file-and-related-features-in-clash-api

### `direct_override_fields`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 字段路径：`outbounds[type=direct].override_address`
- 替代写法：route.rules[].action = route-options + override_address
- 官方：https://sing-box.sagernet.org/deprecated/#destination-override-fields-in-direct-outbound

### `direct_override_port`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 字段路径：`outbounds[type=direct].override_port`
- 替代写法：route.rules[].action = route-options + override_port
- 官方：https://sing-box.sagernet.org/deprecated/#destination-override-fields-in-direct-outbound

### `dns_legacy_server_format`

- 类别：已移除
- 废弃于：1.12.0
- 移除于：1.14.0
- 字段路径：`dns.servers[].address`
- 替代写法：dns.servers[].type + dns.servers[].server
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-dns-server-formats

### `dns_rule_action_strategy`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`dns.rules[].strategy`
- 替代写法：把 strategy 移到 DNS server 定义里
- 备注：仅当该 DNS 规则带 action 时才算 deprecated
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-strategy-dns-rule-action-option

### `dns_rule_legacy_address_filter`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`dns.rules[].ip_cidr`
- 替代写法：match_response + 在 DNS server 上写地址过滤
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-address-filter-fields-in-dns-rules

### `dns_rule_legacy_ip_is_private`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`dns.rules[].ip_is_private`
- 替代写法：match_response 版 ip_is_private
- 备注：带 match_response 的写法不算 deprecated
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-address-filter-fields-in-dns-rules

### `dns_rule_outbound`

- 类别：废弃中
- 废弃于：1.12.0
- 移除于：1.16.0
- 字段路径：`dns.rules[].outbound`
- 替代写法：在 DNS server 上加 dial fields（如 detour / domain_resolver）
- 官方：https://sing-box.sagernet.org/deprecated/#outbound-dns-rule-item

### `download_detour`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`route.rule_set[].download_detour`
- 替代写法：route.rule_set[].http_client
- 备注：sing-box check 对这项完全静默（不报错不警告），只能靠本表兜住
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-download_detour-remote-rule-set-option

### `ech_legacy_fields`

- 类别：已移除
- 废弃于：1.12.0
- 移除于：1.13.0
- 字段路径：`**.tls.ech.**`
- 替代写法：无（改用标准库 ECH）
- 备注：涉及 pq_signature_schemes_enabled / dynamic_record_sizing_disabled
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-ech-fields

### `empty_direct_outbound_download_detour`

- 类别：语义变更
- 废弃于：1.11.0
- 替代写法：给下载用的 direct 出站加 domain_resolver（或 bind_interface / inet4_bind_address / routing_mark 等），或改走 Proxy；只写 {"type":"direct","tag":"direct"} 的空 direct 不能作为规则集下载 detour
- 备注：check 完全静默，只有 run 启动规则集时才会 FATAL: detour to an empty direct outbound makes no sense。protocol/direct/outbound.go 用 reflect.DeepEqual(DialerOptions, {UDPFragmentDefault:true}) 判定 isEmpty
- 官方：https://github.com/SagerNet/sing-box/blob/dev/common/dialer/detour.go

### `implicit_default_http_client`

- 类别：语义变更
- 废弃于：1.14.0
- 移除于：1.16.0
- 替代写法：显式配置顶层 http_clients + route.default_http_client
- 官方：https://sing-box.sagernet.org/deprecated/#implicit-default-http-client

### `independent_cache`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`dns.independent_cache`
- 替代写法：直接删除（DNS 缓存行为已统一）
- 备注：sing-box check 会 WARN
- 官方：https://sing-box.sagernet.org/deprecated/#independent_cache-dns-option

### `legacy_inbound_domain_strategy`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 字段路径：`inbounds[].domain_strategy`
- 替代写法：route.rules[].action = resolve + strategy
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-inbound-fields

### `legacy_inbound_fields`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 字段路径：`inbounds[].sniff`
- 替代写法：route.rules[].action = sniff
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-inbound-fields

### `legacy_special_outbounds`

- 类别：仅存档
- 废弃于：1.11.0
- 移除于：1.13.0
- 替代写法：rule action
- 备注：指的是把 outbounds[] 里的 block/dns 出站当作「特殊出站」来拒绝或劫持 DNS 的旧语义（已于 1.13.0 移除，改用 rule action）。注意 type:block 出站本身在 1.14 仍然合法，可用于 AD 分流组；route.rules[].action 是当前正确写法。故本条目仅存档，audit 不做路径匹配。
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-special-outbounds

### `new_cache_file_write_buffering`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`experimental.cache_file.buffer_size`
- 采纳理由：纯 I/O 优化，默认 1MB 已由内核内部生效；即便不写字段，写缓冲这层也是开着的。额外调参无收益。选择不写字段。
- 覆盖关键词：`cache file write buffering`, `buffer_size`
- 官方：https://sing-box.sagernet.org/configuration/experimental/cache-file/#buffer_size

### `new_dns_server_address_rule_item`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`**.dns_server_address`
- 采纳理由：可匹配系统/DHCP/VPN 下发的 DNS 服务器地址与搜索域；本仓库 DNS 已按域名分流，用不上。选择不启用。
- 覆盖关键词：`dns_server_address`, `dns_search_domain`
- 官方：https://sing-box.sagernet.org/configuration/route/rule/#dns_server_address

### `new_endpoint_on_demand`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`**.on_demand`
- 采纳理由：本仓库不使用任何 endpoint（无 WireGuard/Tailscale/OpenVPN/OpenConnect），该选项无从落地。选择不启用。
- 覆盖关键词：`on_demand`
- 官方：https://sing-box.sagernet.org/configuration/endpoint/wireguard/#on_demand

### `new_http_outbound_version`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`outbounds[type=http].version`
- 采纳理由：1.15 重写 HTTP 代理：默认改用 HTTP/2 并自动回退 HTTP/1.1。默认行为已生效、无需配置；显式写 version 反而可能锁死协商结果。选择不写字段。
- 覆盖关键词：`http/2`, `http/3`, `http proxy`, `connect-udp`
- 官方：https://sing-box.sagernet.org/configuration/outbound/http/#version

### `new_masque_endpoints`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`endpoints[type=masque-client]`
- 采纳理由：新增协议，本仓库节点均为 vless/vmess/trojan/hysteria2/ss/anytls/tuic，无 MASQUE 服务端可用。选择不启用。
- 覆盖关键词：`masque`
- 官方：https://sing-box.sagernet.org/configuration/endpoint/masque-client/

### `new_naiveproxy_version_bump`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 采纳理由：仅上游组件版本号更新，无配置面变化。无需动作。
- 覆盖关键词：`naiveproxy`
- 备注：无配置字段可检测（path=null），只作为 changelog 覆盖比对的目标。
- 官方：https://sing-box.sagernet.org/changelog/

### `new_tailcat_inbound_outbound`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`inbounds[type=tailcat]`
- 采纳理由：新增协议，需要 Tailscale 网络与其控制面配套。本仓库面向单机上网代理场景，用不上。选择不启用。
- 覆盖关键词：`tailcat`
- 官方：https://sing-box.sagernet.org/configuration/inbound/tailcat/

### `new_tls_certificate_sha256_pinning`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`**.tls.certificate_sha256`
- 采纳理由：在既有公钥固定之外新增整证书哈希固定。本仓库节点由用户随时更换、证书会轮换，钉死证书哈希会导致换证书后连不上，收益为负。选择不启用。
- 覆盖关键词：`certificate_sha256`, `certificate pinning`
- 官方：https://sing-box.sagernet.org/configuration/shared/tls/#certificate_sha256

### `new_tun_auto_redirect_android`

- 类别：新功能采纳
- 采纳决策：不启用（`adopt=no`）
- 自版本：1.15.0
- 配置应有状态：`absent`
- 字段路径：`inbounds[type=tun].auto_redirect`
- 采纳理由：1.15 起 Android 上通过图形客户端的 root 服务或 root shell 全功能支持。本仓库三平台走 VpnService/系统 TUN，未使用 auto_redirect（也不需要 root）。无 root 真机验证条件，按默认策略选择不启用。
- 覆盖关键词：`auto_redirect`
- 备注：该字段本身自 1.10 起存在；1.15 是 Android 上的『全功能支持』。检测字段是 auto_redirect。
- 官方：https://sing-box.sagernet.org/configuration/inbound/tun/#auto_redirect

### `new_tun_sing_tun_stack`

- 类别：新功能采纳
- 采纳决策：必须跟随（`adopt=must`）
- 自版本：1.15.0
- 决策截止：1.17.0
- 配置应有状态：`absent`
- 字段路径：`inbounds[type=tun].stack`
- 采纳理由：这不是「要不要开」而是「旧写法要删」：1.15 起 sing-tun 使用自己的 TCP/IP 栈，官方称峰值性能/能耗/内存均显著改善；删掉 stack 字段即启用。1.15/1.16 上删不删都能跑，1.17.0 起保留 stack 会 FATAL。★ 唯一风险点：本仓库 tun 写的是 mtu=9000，官方对比表用 1500/4064/65535，换栈后 mtu 取值需在正式版文档确认后再定。
- 覆盖关键词：`tcp/ip stack`, `sing-tun`
- 官方：https://sing-box.sagernet.org/migration/#migrate-tun-stack

### `platform_process_path_rule`

- 类别：平台限制
- 字段路径：`**.process_path`
- 受影响平台：android、ios
- 替代写法：移动端不可用
- 官方：https://sing-box.sagernet.org/clients/apple/features/

### `platform_process_rule`

- 类别：平台限制
- 字段路径：`**.process_name`
- 受影响平台：android
- 替代写法：在移动端改用 package_name / include_package / exclude_package
- 官方：https://sing-box.sagernet.org/clients/android/features/

### `platform_strict_route`

- 类别：平台限制
- 字段路径：`inbounds[type=tun].strict_route`
- 受影响平台：android、ios
- 替代写法：删除该字段（移动端未实现）
- 备注：sing-box check 不报错，但移动端无效果
- 官方：https://sing-box.sagernet.org/clients/android/features/

### `platform_uid_rule`

- 类别：平台限制
- 字段路径：`**.user_id`
- 受影响平台：android、ios
- 替代写法：Android 用 package_name；Apple 仅 macOS 独立版/iOS 越狱版可用
- 官方：https://sing-box.sagernet.org/clients/apple/features/

### `route_rule_geoip`

- 类别：已移除
- 废弃于：1.8.0
- 移除于：1.12.0
- 字段路径：`route.rules[].geoip`
- 替代写法：rule_set 引用 geoip 规则集
- 官方：https://sing-box.sagernet.org/deprecated/#geoip

### `route_rule_geosite`

- 类别：已移除
- 废弃于：1.8.0
- 移除于：1.12.0
- 字段路径：`route.rules[].geosite`
- 替代写法：rule_set 引用 geosite 规则集
- 官方：https://sing-box.sagernet.org/deprecated/#geosite

### `rule_set_ip_cidr_accept_empty`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`dns.rules[].rule_set_ip_cidr_accept_empty`
- 替代写法：response matching（match_response）
- 备注：sing-box check 会 WARN
- 官方：https://sing-box.sagernet.org/deprecated/#legacy-rule_set_ip_cidr_accept_empty-dns-rule-item

### `rule_set_ipcidr_match_source`

- 类别：已移除
- 废弃于：1.10.0
- 移除于：1.11.0
- 字段路径：`**.rule_set_ipcidr_match_source`
- 替代写法：rule_set_ip_cidr_match_source
- 官方：https://sing-box.sagernet.org/deprecated/#match-source-rule-items-are-renamed

### `shadowsocksr_outbound`

- 类别：已移除
- 废弃于：1.5.0
- 移除于：1.6.0
- 判定方式：outbounds/endpoints 中 `type` 等于 `{'where': 'outbounds', 'field': 'type', 'equals': 'shadowsocksr'}`
- 替代写法：无（sing-box 已不支持 SSR）
- 官方：https://sing-box.sagernet.org/deprecated/#shadowsocksr

### `store_rdrc`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`experimental.cache_file.store_rdrc`
- 替代写法：experimental.cache_file.store_dns
- 备注：sing-box check 会 WARN
- 官方：https://sing-box.sagernet.org/deprecated/#store_rdrc-cache-file-option

### `tls_inline_acme`

- 类别：废弃中
- 废弃于：1.14.0
- 移除于：1.16.0
- 字段路径：`**.tls.acme`
- 替代写法：certificate provider（configuration/certificate/ + tls.certificate_provider）
- 官方：https://sing-box.sagernet.org/deprecated/#inline-acme-options-in-tls

### `tun_gso`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 字段路径：`inbounds[type=tun].gso`
- 替代写法：直接删除
- 官方：https://sing-box.sagernet.org/deprecated/#gso-option-in-tun

### `tun_legacy_address_fields`

- 类别：已移除
- 废弃于：1.10.0
- 移除于：1.12.0
- 字段路径：`inbounds[type=tun].inet4_address`
- 替代写法：address（数组）
- 官方：https://sing-box.sagernet.org/deprecated/#tun-address-fields-are-merged

### `tun_legacy_address_fields6`

- 类别：已移除
- 废弃于：1.10.0
- 移除于：1.12.0
- 字段路径：`inbounds[type=tun].inet6_address`
- 替代写法：address（数组）
- 官方：https://sing-box.sagernet.org/deprecated/#tun-address-fields-are-merged

### `tun_stack`

- 类别：废弃中
- 废弃于：1.15.0
- 移除于：1.17.0
- 字段路径：`inbounds[type=tun].stack`
- 替代写法：直接删除 stack，使用 sing-tun 自带 TCP/IP 栈
- 备注：1.14 正式版仍合法；升到 1.15 后必须删
- 官方：https://sing-box.sagernet.org/deprecated/#tun-stack-option

### `wireguard_outbound`

- 类别：已移除
- 废弃于：1.11.0
- 移除于：1.13.0
- 判定方式：outbounds/endpoints 中 `type` 等于 `{'where': 'outbounds', 'field': 'type', 'equals': 'wireguard'}`
- 替代写法：endpoints[].type = wireguard
- 官方：https://sing-box.sagernet.org/deprecated/#wireguard-outbound

## 五、怎么更新这张表

```bash
python tools/upgrade-check.py          # 看上游新的废弃项 + 还没做决策的新功能
# 按报告把新条目写进 docs/version-matrix.json 的 entries[]
#   废弃类：kind / deprecated_in / removed_in / path / replacement
#   新功能：kind=new / since / adopt / reason / decide_by / keywords
python tools/gen-docs.py               # 重新生成本文件
python tools/audit.py                  # 门禁必须 0 ERROR
```
