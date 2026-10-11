# VERSION-MATRIX.md — 字段生命周期总表

> **本文件由 `tools/gen-docs.py` 从 `docs/version-matrix.json` 生成，请勿手改。**
> 要改内容请改 JSON，然后运行 `python tools/gen-docs.py`。

`tools/audit.py` 读的就是那份 JSON；本文件只是给人看的快照。

## 怎么用这张表

- **废弃中**：当前正式版仍能用，但官方已宣布将来移除 → 新写的配置不要再用。
- **已移除**：用即 `FATAL`，配置起不来 → 必须按「替代写法」改。
- **平台限制**：字段本身合法，但目标客户端没实现 → `sing-box check` 不会报错，要靠人看。
- **语义变更**：字段名没变但默认行为变了 → 不报错，容易悄悄出错。

## 一、按移除版本排序（越靠前越紧急）

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

## 二、本次锁定的正式版视角

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

## 三、完整明细（含说明与官方链接）

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

## 四、怎么更新这张表

```bash
python tools/upgrade-check.py          # 看上游有没有新的废弃项
# 按报告把新条目写进 docs/version-matrix.json 的 entries[]
python tools/gen-docs.py               # 重新生成本文件
python tools/audit.py                  # 门禁必须 0 ERROR
```
