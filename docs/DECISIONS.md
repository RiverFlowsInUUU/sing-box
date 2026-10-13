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
- **触发**：2026-10-12 的节点信息泄漏事故（L18 的证据文档把节点域名与它的 A/AAAA 记录一起推到了公开仓库）
- **决策**：**新建 `audit_redaction()` 门禁** —— 按 `git ls-files` 扫**全部被跟踪文件**，
  发现未审阅的公网 IP 即报 ERROR。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：铁律 7 写的是「仓库里不放真实节点」，但当时唯一的防泄漏门禁 `placeholder_server`
  **只管 `profiles/` 目录里的 JSON 字段** —— 而这次泄漏发生在 `docs/` 的散文里。
  所有门禁都是“按字段”审的，**散文没人管**。道理很硬：**门禁的作用域必须与铁律的作用域一致**，
  否则一个缺口就能让整条铁律形同虚设。另外，当时事后才发现 force-push 只重置分支指针，
  旧对象仍可按 SHA 直取（2026-10-12 晚删库重建后才彻底消失）—— 依赖“事后补救”远比“事前拦住”昂贵。
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

## D10 指针层脱敏：事故的 commit SHA 不得写进仓库（含“黑名单自败”的教训）

- **日期**：2026-10-12
- **触发**：D9 上线后追问“脱敏到底脱干净了吗”，发现**指向泄漏内容的指针**没洗 ——
  事故那个 commit 的 SHA 被写进了 `AGENTS.md`、`docs/DECISIONS.md`、`docs/LESSONS.md` 三处已推送文件。
- **决策**：① 三处 SHA 全部换成「**日期 + 背景**」（如「2026-10-12 的节点信息泄漏事故」）；
  ② `audit_redaction()` 的扫查范围从「被跟踪文件」扩到**commit message**；
  ③ 追溯起点用**不点名任何 commit 的单调时间常量** `LEAK_SCAN_START_DATE`。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：分两点。
  1. **force-push 删不掉旧对象**，实测证明：当时 `gh api .../commits/<事故 SHA>` 仍 HTTP 200，
     `.patch` 页仍能搜到已脱敏过的域名。⇒ 那个 SHA 是**能直取原文的 URL**，不是编号。
     只洗内容不洗指针 = 把钥匙留在锁旁边。
     ⚠️ **2026-10-12 晚删库重建后，上述取法已变 404**（旧仓连同旧对象一起消失）。
     但本决策不因此作废 —— “先 force-push 就没事了”这个直觉仍然是错的，
     重建是最后手段，不能当成常规修法。
  2. **第一版实现是错的，写下来避免再犯**：我先用的是「已泄漏 SHA 黑名单」常量。
     写完立刻自相矛盾 —— 要在仓库里拦住某个 SHA，**就必须把那个 SHA 明文写进仓库**，
     而它正是不能写的东西。而且这会**递归**：拦住“写 SHA”这件事的清单，自己就得写 SHA。
     ⇒ 改成**不需要知道“漏过什么”也能判定**的时间切点（门禁从此刻生效，之后必须干净）。
- **备选方案**：
  - **SHA 黑名单 / 后缀匹配**（已实现，已废弃）。自败，理由见上。
  - 把「不写 SHA」写进铁律靠人自觉（已入 AGENTS.md 铁律 7）—— 但自觉不能兜住“指针”这个概念，
    因为写的人多半以为自己写的是个无意义的编号。
  - 给仓库做历史重写 / 删库重建（彻底，但会丢掉协作历史，且 GitHub 侧对象仍要 Support 才能回收）。
- **前提 / 风险**：
  - 门禁**不追溯** `LEAK_SCAN_START_DATE` 之前的 commit message —— 那之前的历史已知含泄漏，
    而“把要拦的 SHA 写进仓库”会重新泄漏一次（这正是本条决策的由来）。只保证“从此之后干净”。
  - 因此**时间常量不能往回调**：改小等于把已泄漏的历史重新纳入扫查，门禁会立刻报错，
    而“修”的方式就是再次写 SHA —— 正是要避免的事。
  - 常量取一个**手选、整齐、落在窗口内**的时刻，窗口 = (已知最脏的那次提交, 引入门禁的那次提交]：
    窗口内任取一刻都对，早了就漏、晚了就误报。`--since` 是严格大于比较且 git 只有秒级精度。
    **故意不取“引入门禁那次提交的精确时间”** —— 那样每改一次代码就得重取常量，形成自指循环。
  - 也不把该数值抄进台账：代码里就有、改了 git 里看得见，抄一遍只会多一处不同步。
  - 彻底注销旧对象只能靠 GitHub Support 或删库；本决策管的是“别再扩散”。

---

## D11 指针层脱敏的落地口径：门禁允许宽进、人工判定只和“结果”挂钩（自评补充）

- **日期**：2026-10-12
- **触发**：落 D10 时发现被跟踪文件已经写下那个 SHA，本次必须把三处替换掉；
  同时要回答“以后别人写出别的 SHA 怎么办”。
- **决策**：门禁只做**形状识别**、不做**清单比对** —— `audit_redaction()` 扫的是「未审阅的**公网 IP**」
  这一族事实（含 commit message）；对 SHA 只保留“写事故不写 SHA”的口径，不建可枚举名单。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：只要判定条件里出现“该 SHA 是坏事”的判断，就必须把它存下来。
  反之，如果门禁的判定条件是**从内容自身成立的**（“这是一个未审阅的公网 IP”），
  就无需任何名单，也不可能因为“写名单”而二次泄漏。
  ⇒ **能自洽判定的就不存名单**。同一条思路以后套用到其它“禁止出现 X”类门禁：
  先问「判定 X 是否必须存下 X？」。
- **备选方案**：
  - 建 `已泄漏指针清单`（同一件事的第三次尝试，已否决）。
  - 用哈希存 SHA（不可反查）—— 比明文好，但 SHA 空间小到可暴力枚举，等于装锁不拔钥匙。
- **前提 / 风险**：意味着**新出现的泄漏指针类型**（如外部 paste 链接、issue 编号里的引用）
  不会自动被拦 —— 要靠铁律 7 的“日期 + 背景”口径 + 事后人工评审兜。
  **宁可少拦一类，也不要再写一份清单。**

---

## D12 台账里的“风险点”要有字段承载 —— 新增 `follow_up`（基础设施决策）

- **日期**：2026-10-12
- **触发**：全仓梳理时发现，`new_tun_sing_tun_stack` 的唯一风险点
  （“本仓库 tun 写的是 `mtu: 9000`，官方对比表用 1500/4064/65535，换栈后 mtu 怎么定”）
  只写在 `reason` 那段散文里。到 1.15 真正发布时，“删 `stack`”有门禁管，
  “`mtu` 要不要跟着改”却只靠那天有人恰好读到那句话。
- **决策**：矩阵 schema 新增 `follow_up`（数组；元素 = 一句话待办，或 `{todo, when}`），
  承载“迁移时还需重新决策”的附加项；`audit_new_features()` 每次碰到非空 `follow_up` 就打
  INFO 提醒（门禁 code `matrix_follow_up_reminder`）。sing-tun 那条的 mtu 风险已从 `reason` 搬进 `follow_up`。
  ⚠️ 这个 code **刻意不用 new_ 前缀** —— 因为它不是矩阵条目，
  而 `audit_decisions()` 会把 D 条目正文里所有反引号包住的 new_ 开头标识当成“引用了某个矩阵 id”，
  写成那种形式会被 `decision_references_unknown` 误报（本轮踩过：解释性文字本身触发了门禁）。
  ⇒ **门禁 code 的命名空间与矩阵 id 的命名空间重叠，是设计缺陷**，
  已在 L27 记下；以后新增非矩阵类 code 一律用「行为」命名（如 `matrix_follow_up_reminder`）。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：现有门禁的前提是“**判据在配置里**”（能读 JSON 判对错）。
  而 mtu 该取多少的判据**在上游正式版文档里** —— 而且 1.15 还没发布，
  本地 `docs/upstream-tun.md` 的 `#### mtu` 只有一句 “The maximum transmission unit.”（无默认值、无建议值）。
  这类待办**天然落在静态检查能力之外**，需要的是“提醒”而不是“校验”。
  放在 `reason` 里之所以不行：`reason` 只被校“非空”，不会被重复展示 ——
  写进去就等于“只读一次、读完就忘”。
- **备选方案**：
  - 写进 `docs/DECISIONS.md` 的「前提 / 风险」栏（已写）。**不够**：那是一段说明，不是可触发的提醒，
    而且同样只被人工阅读一遍（D1 就是这么写的，然后本轮才发现它的风险点没落地）。
  - 建一个独立的 `TODO.md`。否决：会再开一份需要人工维护、无人校对的清单，
    与 L22/L27 的教训（多份副本必然漂移）同类型。
  - 直接把 `mtu` 改成某个具体值。否决：1.15 正式版文档还没出，现在改就是猜。
- **前提 / 风险**：`follow_up` 只做 **INFO 提醒**，不拦交付 —— 提醒会被忽略。
  这是刻意的：这个时点上“mtu 该取什么值”真的无法判定，把不确定的事写成 ERROR
  会逼出“为了过关而乱填一个值”的假修完。待 `decide_by`（1.17.0）到期时，
  未清空的 `follow_up` 应当升级为 ERROR（见 L26 的修法第 3 条）。

---

## D13 DNS 层前置广告拦截 —— 启用（route 层保留作兜底）

- **日期**：2026-10-12
- **触发**：用户提问「Jinx / 秋风广告规则能否前置到 DNS 层处理，规则集保留作兜底拦截/直连」
- **决策**：**启用**（Android 先行；`profiles/1.14/*-lazy.json` 待真机确认后再推广）
- **矩阵 ID**：（基础设施类，不进矩阵 —— 不涉及上游新功能）
- **为什么**：广告域名在**解析阶段**就被拒，连接根本不会建立，
  比「连上后由 `block` 出站拒绝」更早、更省 —— Android 上后台重试的广告域名直接 NXDOMAIN，
  省掉一整轮 TCP 握手开销。实现方式是 `dns.rules` 插两条（白名单放行 → 拦截集 NXDOMAIN），
  **不新增任何 `rule_set` 条目**：DNS 规则自 1.8.0 起可复用 `route.rule_set` 的 tag，
  不增加下载体积，也不增加启动依赖。
- **备选方案**：
  - **只做 route 层拦截**（现状）：可行，但每次拦截都要先建立连接、再由 `block` 出站拒绝，
    且 `docs/LESSONS.md` L16 的拦截日志会持续刷屏。
  - **改成 `reject`（回 REFUSED）**：考虑过。放弃理由：NXDOMAIN 的语义是「这个域名不存在」，
    应用通常直接放弃；REFUSED 更像「服务器拒绝解析」，部分应用会换一个 DNS 服务器重试。
  - **用 AdGuard 格式的过滤列表**：用户最初的想法。**不可行** —— 官方明确 AdGuard 格式
    **不能作为 source 直接引用**，必须 `sing-box rule-set convert --type adguard` 预编译；
    而本案用的 Jinx / 秋风本来就是 sing-box 自己的 source 格式，无需转换。
- **前提 / 风险**：
  1. **route 层规则不能删**，且不只是「兜底」：任何绕过 sing-box DNS 的解析
     （应用自带 DoH/DoT、系统私有 DNS）只有 route 层拦得住。
  2. **两处顺序各自维护**：`dns.rules` 与 `route.rules` 是两份独立的顺序表，
     排错即静默失效 —— 已由 `dns_ad_order` / `dns_ad_without_whitelist` 门禁机器化（L28）。
  3. **顺序依赖实测数据**：Jinx 白名单 47 条域 100% 被拦截集覆盖（如 `gm.mmstat.com` ← `mmstat.com`），
     所以白名单必须先命中；`geosite-cn` 必须排在拦截之后，否则国内广告域名先被放行。
     上游若改变白名单/拦截集的覆盖关系，这个结论需要重新实测。

---

## D14 防泄漏门禁的扫描范围含「尚未 add 的新文件」（基础设施决策）

- **日期**：2026-10-12
- **触发**：`docs/evidence/2026-10-12-dns-layer-adblock-feasibility.md` 首次提交时，
  本地 `audit.py` 全绿、CI 报 5 个 `sensitive_ip_in_repo`。根因是
  `audit_redaction()` 的文件名单只来自 `git ls-files`（已跟踪文件），
  新文档在 `git add` 之前不在名单里（L29）。
- **决策**：名单改为 `git ls-files` **并** `git ls-files --others --exclude-standard`，
  合并去重。同时明确流程纪律：**交付前跑 audit 必须先 `git add -A`**，与 CI 同条件。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：门禁的语义是「仓库里不许出现未审阅的公网 IP」，
  而 `git ls-files` 只能回答「现在已经有什么」——「即将有什么」它看不见。
  这个缺口不是靠人记得先 `add` 能补的：把正确性寄托在流程记忆上，等于没有门禁。
- **备选方案**：
  - **CI 加一道「本地必须先跑过 audit」的检查**。否决：无法验证，且把责任推回给人。
  - **改用 `git status --porcelain` 取全部变更文件**。等价，但 `--others --exclude-standard`
    更直白地表达「未被 ignore 的新文件」，且与既有 `startswith("local/")` 跳过逻辑自然衔接。
  - **把 `docs/evidence/` 整体排除**。否决：那正是最需要扫的地方 —— L18 的泄漏就发生在这里。
- **前提 / 风险**：列入未跟踪文件后，工作区里**临时/实验性的文件**也会被扫。
  这在本仓库是可接受的：`local/` 与 `_probe` 类临时物一律在 `.gitignore` 里，
  而 `--exclude-standard` 恰好按 `.gitignore` 过滤。若将来有「确实该忽略、又没写进 .gitignore」
  的临时文件，应补 `.gitignore`，**不是**收窄扫描范围。

---

## D15 DNS 层广告拦截从「本地试验」推广到三份 profile（基础设施决策）

- **日期**：2026-10-13
- **触发**：`local/android-usai.json` 上实测通过 DNS 层前置拦截（`jinx-direct` 先放行、
  `jinx-ads + awanue-ads` 回 `NXDOMAIN`）后，用户确认「按你推荐的来」，随后要求
  「把你认为合理的都做了吧」。
- **决策**：把这两条规则**推广进 `profiles/1.14/{android,desktop,ios}-lazy.json`**
  （`dns.rules` 4 → 6 条），route 层的三条广告规则**保留不动**作为兜底。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：DNS 层拦在**解析之前**，设备拿不到 IP 就连不上，也省掉一整条 TCP 连接；
  route 层拦在**连接之后**，是「已经解析了才拒绝」。两层都留是因为它们拦的不是同一类东西：
  - DNS 层只能按**域名**拦（`predefined` 没有 `ip_cidr` 条件，见 D13）；
  - route 层能按**域名或 IP** 拦，且覆盖「客户端绕过本地 DNS 直连 IP 字面量」的场景
    （规则集里只有极少数 IP 型条目，但保留了这条通路）。
  - 反过来，**只留 DNS 层不行**：客户端自带的 DoH、或直接写 IP 的请求，DNS 层根本看不见。
- **备选方案**：
  - **只在 DNS 层拦、删掉 route 层三条**。否决：丢掉 IP 型拦截与绕过本地 DNS 的场景。
  - **只留 route 层**。否决：每次被拦都白跑一次 DNS 查询 + 一次 TCP 连接。
  - **三份 profile 里各写一份 DNS 拦截、互不引用**。否决：顺序语义（白名单必须在前）
    会在三处各错一次，而门禁 `_audit_dns_adblock` 是按「顺序 + 动作」校验的，集中更容易守。
- **前提 / 风险**：
  - `jinx-direct` 白名单的 47 个域名**几乎全部被拦截集覆盖**（实测 100%），
    所以白名单规则一旦被删或排到拦截之后，被覆盖的正常域名会**静默变成 NXDOMAIN** ——
    门禁 `dns_ad_without_whitelist` / `dns_ad_order` 守着这两点。
  - `NXDOMAIN` 的选择见 D13：比 `predefined` 空应答更「硬」，且客户端报错明确。
  - 若上游 Jinx 仓库改了发布格式（当前是 sing-box source 格式 JSON），
    `format: "source"` 会解析失败 ⇒ 启动 FATAL，不会静默失效。

---

## D16 平台差异矩阵上锁：从「人读的文档」变成「机器校验的表」（基础设施决策）

- **日期**：2026-10-13
- **触发**：用户问「你是否有修改建议」，排查发现 `docs/PLATFORM-MATRIX.md` 第 1 节把
  `route_address_set` / `route_exclude_address_set` 与普通 `_address` 混成一行「✅ ✅ ✅」，
  而 `_set` 变体在 **Android 图形客户端静默失效**（内核 `protocol/tun/inbound.go:384` 与 `:418`
  两处 `platformInterface` 闸门）—— 文档错了很久，没有任何门禁发现（L32）。
- **决策**：把 §4 速查表改成**可机读的三列表格**（`JSON 路径` × 三平台 × `JSON 字面量`/`**删除**`），
  新增两道门禁：`matrix_platform_stale`（矩阵 ⟺ 配置，逐格对账）与 `profile_drift`
  （三份配置出现任何未登记差异即 ERROR）；同时新增 `audit_matrix_coverage()`
  把 `templates/groups.json` 与三份 profile 双向对账（L33）。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：这台仓库反复出现同一个形状的失效 —— **文档与人话没有校验，就一定会腐烂**
  （L26 台账风险点无字段、L27 文件头声明无人校、L32 矩阵零门禁）。
  单个字段的 ✅/❌ 判断**无法**交给机器（没有可靠的官方机读源，官方 `features.md`
  是给 Markdown 渲染器看的表格），但「文档登记的差异 = 配置实际的差异」这件事**可以**。
  把能锁的部分锁死，人只需复核「锁不住的那部分」。
- **备选方案**：
  - **爬官方 `features.md` 自动生成矩阵**。否决：那是 HTML 注释驱动的渲染源，
    格式变动不受本仓控制；一旦上游改写法，门禁会先坏掉，反而制造噪音。
  - **只做 `matrix_platform_stale`（单向）**。否决：单向只能发现「矩阵说 A、配置是 B」，
    发现不了「配置多了个差异、矩阵没登记」，而后者恰是 L32 的另一种形态。
  - **把 §1/§2 的能力清单也机读化**。见「前提 / 风险」。
- **前提 / 风险**：
  - **§1/§1a/§2/§2a 的能力清单仍靠人工复核**（来源、行号、官方标注都写在表里）。
    文件头已明写「本表中可机器核对的部分己上锁」，避免下次误以为整份文档都被门禁守着。
  - `profile_drift` 会让**任何**未登记的平台差异报 ERROR —— 这是刻意的：
    新增差异的成本是「改配置 + 加一行矩阵」，比事后查错便宜。
    代价是**临时实验**必须放在 `local/`（已被 `matrix_platform_stale` 跳过），不能直接改 `profiles/`。

---

## D17 删掉桌面端只有 `default_mode` 的 `clash_api` 空壳（基础设施决策）

- **日期**：2026-10-13
- **触发**：全仓梳理时核对 `profiles/1.14/desktop-lazy.json` 的
  `experimental.clash_api: {"default_mode": "Rule"}`：通读源码发现它既不监听端口、
  也改不了任何分流行为，却仍创建统计组件（L32 同轮发现）。用户授权「按最优选择决定」。
- **决策**：**删除**桌面的 `clash_api`，三份配置统一不写；将来要用再按需补全（见下）。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：这条配置的**注释意图**是「显式写 `Rule` 以免客户端默认成 `Global`」，
  但源码里根本不是这个默认值 —— 它是个**看起来有用的假信号**，比不写更糟：

  | 检查点 | 源码事实 |
  |---|---|
  | 端口 | `experimental/clashapi/server.go` 的 `if s.externalController {`（`externalController = options.ExternalController != ""`）才是监听开关；只有 `default_mode` 时**不开端口** |
  | 模式 | `experimental/clashmode/manager.go`：`if defaultMode == "" { defaultMode = "Rule" }` —— 不写也是 `Rule` |
  | 分流效果 | `route/rule/rule_item_clash_mode.go` 的 `Match` 只有在 `route.rules`/`dns.rules` 里存在 `clash_mode` 条件时才可能命中 —— 本仓库 **0 条** |
  | 代价 | `box.go:243` 的 `if needClashAPI \|\| needAPIService \|\| options.PlatformLogWriter != nil {`，而 `needClashAPI` 只要求 `experimentalOptions.ClashAPI != nil` ⇒ 键存在即创建 Traffic Manager 与连接统计 |

- **备选方案**：
  - **保留并在 `docs/DECISIONS.md` 记录用途**（原第 13 条建议的另一个选项）。否决：
    记录用途也改变不了「这个键只带来开销、不带来能力」；把空转配置写进文档只会让它更难删。
  - **改成完整可用（补 `external_controller` + `secret` + `external_ui`）**。否决：
    仓库不允许写本机绝对路径与端口约定（铁律 7），且桌面端目前没有用面板的需求；
    真要加时**按需加**比现在预埋一个半成品干净。
- **前提 / 风险**：将来在桌面上启用 Clash 面板时，必须同时补 `external_controller`、`secret`、
  `external_ui` 三项，**并更新 `docs/PLATFORM-MATRIX.md` §4 那一行**（铁律 19 要求
  矩阵 ⟺ 配置一致，否则 `matrix_platform_stale` 会报错）。这正好是门禁该起作用的地方。

---

## D18 分流组 tag 加 emoji 前缀，AD 组删掉 `direct`（用户要求的显示与语义调整）

- **日期**：2026-10-13
- **触发**：用户原话「给 Proxy 改名为🚀 Proxy，给 AI 改名为🤖 AI，给 AD 改名为 🚫 AD，
  同时 AD 组只要 block 作为出口删掉 direct」。
- **决策**：① 三个固定组的 tag 由 `Proxy` / `AI` / `AD` 改为 `🚀 Proxy` / `🤖 AI` / `🚫 AD`；
  ② `🚫 AD` 的 `outbounds` 由 `["block", "direct"]` 收成 `["block"]`，`default` 仍是 `"block"`。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：
  1. **tag 就是显示名**：三个组的 tag 直接出现在 sing-box 客户端的策略组列表里，
     与节点 tag（`🇺🇸 US AI` 这种 emoji 形状）混在一起时，裸 ASCII 的 `Proxy` / `AI` / `AD`
     在列表里看不出「这是组而不是节点」，也一眼分不出哪个是广告组。
  2. **tag 是引用目标**：`route.final`、`route.rules[].outbound`、`dns.rules[].server` 都按字符串引用，
     写错一个字符就是「找不到」（`check` 不报）。所以改 tag 必须端到端改，
     且必须有门禁盯着 —— 这正是 `group_tag_incomplete` / `template_group_tag_incomplete` 的由来。
  3. **AD 里的 `direct` 是纯风险、零收益**：AD 组只在「广告规则命中」时被路由到，
     想直连的域名本来就该在 `route.rules` 里走 `direct`，不需要在 AD 组里放一个「放行档」；
     而 `direct` 一旦被用户手选、或被写成 `default`，就是**全部广告静默直连**。
     删掉它以后 AD 组的语义变成「命中即拦」，不可能被误配成放行。
- **备选方案**：
  - **保留 `Proxy` / `AI` / `AD` 的字面 tag，另用客户端侧的「显示名」功能改名**。
    否决：仓库是跨客户端（SFA / SFI / SFM / SFT / SFW）的配置源，显示名属于客户端 UI 能力，
    配置里没有跨平台字段可写；改 tag 是唯一端到端有效的做法。
  - **AD 组保留 `direct` 作为「临时放行」开关**。否决：见上第 3 点；要临时放行应当改规则，
    而不是在拦截组里留一个会让全部广告静默放行的档位。
- **前提 / 风险**：
  - 改 tag 是**破坏性变更**：本地既有配置（`local/` 下未入库的那几份）与新配置的
    `route.final` / 规则引用 / `cache` 命名会对不上，必须同步改（本轮已改 `local/android-usai.json`）。
  - 客户端里的旧策略组选择会失效（用户之前若手动选过 `AD`，改 tag 后会回到 `default`）。
  - 门禁覆盖：`group_tag_incomplete`（配置侧）+ `template_group_tag_incomplete`（模板侧）
    盯 emoji 形态；`ad_group_polluted` / `template_ad_polluted` / `ad_group_default_not_block` /
    `template_ad_default_not_block` 盯「AD 只留 block」；`matrix_platform_stale` 中若登记了组相关行会一并兜底。
- **事后补记（同轮发现的漏改，2026-10-13）**：本决策执行后核查发现，
  仓库外 `local/` 下四份运行配置里 `dns.servers[].detour` 这一处引用被漏改
  （`local/android-usai.json` 的 `dns-proxy` 仍指向已不存在的 `Proxy`）。
  这是**引用面清单不完整**造成的：`route.rules[].outbound` 改了，`dns.servers[].detour` 没改。
  `sing-box check` 对此 exit=0，只有真启动才 FATAL（`start dns-transport: ... outbound detour not found`）。
  已修数据并新增门禁 `dns_server_detour_missing`（`dns.servers[].detour` 必须在出站 tag 集合中）
  与 `domain_resolver_missing`（`outbounds[]` / `route.rule_set[]` / `http_clients[]` 的
  `domain_resolver.server` 必须在 `dns.servers[].tag` 中）。完整复盘见 `docs/LESSONS.md` L35。

---

## D19 门禁的验证方式产品化：负向回归从「临时脚本」变成常驻套件

- **日期**：2026-10-13
- **触发**：用户原话「我的目标就是提升处理速度，修剪流程冗余，提升结果准确性、正确性和可用性。」
  —— 起因是组改名那次明明只有 28 处必须改的引用位，却花了约 20 分钟。
- **决策**：新增 `tools/negtest.py`（24 个负向用例，约 1 秒） + `tools/check-all.sh`（一条命令串三层），
  并把负向回归接进 CI；同时**定下规矩**：以后加门禁必须往 `CASES` 登用例，不得再临时现写脚本跑完就删。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：
  1. **门禁的「不会响」和「没事」输出完全相同**——`audit.py` 的设计原则是「干净时安静」，
     这恰好使一个彻底失效的门禁（L34 按已废弃字面量匹配）与一个正常无事的门禁不可区分。
     于是「验证门禁」这件事本身变成了必须常驻的一层，而不是写完检查一次就完。
  2. **双向绑定的缺口**：`audit_lessons()` 能证明 code「在代码里存在」与「有文档出处」，
     但证明不了它「会响」。存在性与行为性是两件事（同 L25 工具自检、L30 常量自检）。
  3. **成本可累积**：临时脚本一次性用完即删 ⇒ 下一轮从零再写；固化成套件后，
     每道新门禁都是一次资产积累，也是后来人的反例文档。
- **备选方案**：
  1. **只靠人肉审查门禁代码**——否决。L34 的门禁写了很久无人发现它是死的，
     说明人读一遍看不出「这个字面量早就不用了」。
  2. **在 `audit.py` 内部写自测**——否决。自测与被测代码同一个进程、同一个 import 路径，
     测不出「CLI 的参数/输出格式变了」这类集成层问题；`negtest.py` 故意走真实 CLI、不 mock。
  3. **把负向样本写成 pytest 用例**——否决。仓库没有 Python 测试基设（无 `pyproject.toml`），
     引入 pytest 是一次工具链升级；而当前需求只是一个「能跑、能报错、零依赖」的脚本。
- **前提/风险**：
  1. `negtest.py` 里有 2 个用例必须写**真实仓库文件**（`repo` 作用域）才能触发对账类门禁，
     用 `try/finally` + 字节比对保证还原；若进程被硬杀可能留下脏工作区。
     代价换来的能力：能验证 `template_profile_group_missing` / `doc_group_name_stale` 这类
     「必须与真实文件对账」的门禁（临时文件根本触发不了，`_load_profiles()` 读真实路径）。
  2. `CASES` 与门禁必须同步演进——新增门禁而忘了登用例，本套件不会报错。
     这是已知缺口（无门禁约束「每道 code 必有负向用例」），因为部分 code 确实无法构造
     （如 `run_skipped` 这类环境依赖型）。若日后要上锁，方向是「按 audit 的 code 白名单反向比对」。
  3. 负向样本必须自带旧名/错写（如旧组名 `Proxy`）——这是**故意**的，
     所以 `doc_group_name_stale` 的豁免按「谁需要旧名」用 `_is_negative_fixture()` 判定（词根 `neg`/`_neg`），
     而**不是**按文件名硬编码。
## D20 门禁报错必须自带你该改的那一行（基础设施决策）

- **日期**：2026-10-13
- **触发**：用户定的目标「提升处理速度、修剪流程冗余、提升结果准确性、正确性和可用性」。
  实测一次门禁报错后要人工回文件搜行号才能动手，而这个行号在代码里本来就有。
- **决策**：
  ① `Report.error/warn/info(code, msg, where=None)` 增加第三参数 `where`（`文件:行号`，
  相对仓库根、统一 `/`）——终端输出 `[E] <消息>   ← docs/PLATFORM-MATRIX.md:179`，
  `--json` 每条 item 多一个 `where` 字段；
  ② `_sec4_rows()` 顺带返回每行在原文中的行号（§4 起始行 + 段内偏移）；
  ③ 先在**要改的东西不是配置本身**的那几道门禁上落地：`matrix_platform_stale`（→ §4 那一行）、
  `profile_drift`（→ §4 表头，因为要做的是加一行）、
  `template_profile_group_missing` / `template_profile_group_type` / `profile_group_not_in_template`
  （→ 出事的那份 profile）、`doc_group_name_stale`（→ 那个 `.md` 的行）。
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：
  ① 「错在哪」与「改哪里」是两个信息，后者本来就在门禁手里（表格是逐行解析出来的），
  丢掉它等于把搜索成本**转嫁给每一个读报错的人**（还每次都要重付）；
  ② 统一的 `文件:行号` 形制能与编辑器、`grep`、CI 标注直接对接，比散文描述可靠；
  ③ 这属于「提升结果可用性」——同一份结论，带上定位才能立刻动手。
- **备选方案**：
  ① 让每道门禁自己在 `msg` 里拼位置 —— **否决**：既有实现里只有一部分拼了、格式还各不相同，
  证明「靠自觉」不可持续；接口缺字段就该补字段；
  ② 报错时只给文件名不给行号 —— **否决**：文件动辄两三百行，只给文件名等于没给；
  ③ 等所有门禁一起改 —— **否决**：先落在「改哪里不是显而易见的配置路径」的门禁上收益最大，
  其余门禁（如 `dup_tag`，配置里搜 tag 就能定位）可以慢慢跟。
- **前提 / 风险**：
  ① `where` 是**可选的**，现有调用点无需改动即可继续工作；但新门禁应当默认带上，
  否则又回到「靠自觉」；
  ② 行号会随文件编辑漂移 —— 它只用于**当下这一次**排查，不作为稳定标识；
  ③ `_matrix_sec4_lineno()` 在模块导入时求值一次，若同一进程内改写了矩阵文件不会自动刷新
  （审计是单次运行、不存在这个场景；但若将来做长驻进程需注意）。


---

## D22 新功能覆盖窗口的起点，必须显式声明而不是从别处推导

- **日期**：2026-10-13
- **触发**：用户问「1.14.3 上是不是有些新特性没开启」，排查中发现 1.14.0 的 49 条正式版新功能**从建仓起就没被盘点过一次**（见 L43）
- **决策**：**矩阵里显式写 `policy.coverage_floor`**（初始 `"1.14.0"`），并配 `policy.inventories` 逐版登记盘点记录；**禁止**用锁定版或 `min(since)` 推导窗口起点（`adopt` 层面属于基础设施决策）
- **矩阵 ID**：（基础设施类，不进 `version-matrix.json`）
- **为什么**：
  ① 三个不同的量此前共用一个变量 —— 「窗口从哪开始比对」「哪几版已经盘点过」「下一个要盯的正式版」。
  ② 用**锁定版**当窗口（原实现）：`ver_ge(ver, floor)` 语义是「>=」，1.14.0 永远进不了窗口 ——
  而且一旦升版到 1.15.0，窗口会把 1.14.0 整段拉回来，**一次性炸出 49 条**。实测把 floor 降到 1.14.0，
  `_changelog_features` 从 10 条跳到 112 条。
  ③ 用 `min(since)` 推导：只要登记一条历史条目，窗口就自动降低 ⇒ 引爆炸弹。
  ④ 只有**显式声明**才能同时满足「1.14.0 已盘点、不再反复拉回窗口」与「1.15.0 正式版一发布就自动进窗口」。
- **备选方案**：
  ① 逐条登记 1.14.0 的 49 条 —— **否决**：其中约 29 条（OpenVPN / Snell / USB-IP / Tailscale SSH / go 版本…）
  与「Android/iOS/Windows 三份 tun 型 profile」毫无关系，会产出 29 条 `adopt: no` + 一句套话理由的垃圾条目；
  ② 只降 floor 到 1.14.0、不配 inventories —— **否决**：那 49 条会立刻变成 49 条「新功能未做采纳决策」的 ERROR；
  ③ 把 1.14.0 段从 changelog 快照里删掉 —— **否决**：等于篡改上游事实，升级时还会被 `upgrade-check.py` 重新拉回来。
- **前提 / 风险**：
  ① `coverage_floor` 与 `inventories` 最大 version **必须相等**（`audit_coverage_window()` 双向拦）；
  ② 窗口是**半开区间** `(floor, 锁定版]` ⇒ 起点那一版自己不再进比对，它的盘点靠 `by-class` +
  `evidence` 文档保证；因此 `since == floor` 的条目也必须在盘点文档里有反向链接；
  ③ 升级到 1.15.0 后**必须补一条 `inventories` 记录**，否则新的 `coverage_inventory_missing` 会响
  （这是这套机制唯一需要人主动做的事，也是它存在的目的）。

---

## D23 1.14.0 走 `by-class` 口径盘点：只登记两条真启用的，其余按类归档

- **日期**：2026-10-13
- **触发**：用户指令「把你认为有用的补齐」+「只跟正式版，不跟测试版」（1.15 是测试版，锁 1.14.3）
- **决策**：1.14.0 那一版采用 **`by-class`（按类归档）** 而非逐条登记：49 条正式段里，
  只把**真正写进配置**的两条建成矩阵条目 —— `new_dns_optimistic_cache`（启用）与
  `new_udp_nat_max`（启用，只定上限）；其余按 A/B/C 三类归档到
  `docs/evidence/2026-10-13-features-1.14.0-inventory.md`
- **矩阵 ID**：`new_dns_optimistic_cache`、`new_udp_nat_max`
- **为什么**：
  ① 盘点的目的是「每一条都有归处」，不是「每一条都建条目」。49 条里真正与三份 tun 型 profile 相关的只有约 20 条，
  其中已经用上的（`sniff` pre-match、统一 HTTP 客户端、JSON Schema…）不需要新条目；
  ② 逐条建条目会让矩阵从 42 条膨胀到 90+ 条，其中一半是「与我们无关」，
  反而把真正需要看的决策淹掉 —— 矩阵的价值在**能一眼看完**；
  ③ 但**归档必须成文**：`by-class` 要求的 `evidence` 文档让「已盘点」有据可查，
  并给每条新条目提供反向链接（`inventory_doc_unlinked` 拦「文档没提到这个条目」）。
- **备选方案**：
  ① 逐条 `per-entry` 登记 49 条 —— **否决**：见 D22（垃圾条目）；
  ② 只写一句「1.14.0 已看过，无重要项」 —— **否决**：那正是原实现的问题所在（无凭无据的声称），
  而且删掉后无法复核「为什么 1.14.0 的 X 没启用」；
  ③ 把 15 条「已用但仍未登记」的（如 `sniff` pre-match）也补条目 —— **否决**：它们已在用、无决策可做，
  补条目只会增加噪音（`keywords` 覆盖比对也不要求它们存在）。
- **前提 / 风险**：
  ① `by-class` 的覆盖强度低于 `per-entry` ⇒ 若将来某条历史功能出了事故，需要在文档里补一条专门说明；
  ② 1.14.0 的 53 条**预发布段**条目（如 OpenVPN / L3 forwarding / Hysteria Realm）不在正式版发布说明里，
  已明确排除，不在盘点范围（L43 的另一面：`_changelog_features` 必须先 `break` 掉脚注定义体、
  再按 `include_prerelease=False` 过滤，否则 49 条会膨胀成 102 条）。

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-12 | 建档；记录 D1–D8（对应 1.15.0 的 10 条新功能） |
| 2026-10-12 | 新增 D9（防泄漏门禁，基础设施决策；事故：2026-10-12 节点信息泄漏） |
| 2026-10-12 | 新增 D10、D11（指针层脱敏 + 黑名单自败的教训；同一事故的续篇） |
| 2026-10-12 | 全仓梳理：D10 补注「删库重建后旧对象已 404」（历史事实 vs 当前状态分开写） |
| 2026-10-12 | 新增 D12（`follow_up` 字段；源自 L26） |
| 2026-10-12 | 新增 D13（DNS 层前置广告拦截；源自用户提问，route 层保留兜底） |
| 2026-10-12 | 新增 D14（防泄漏扫查纳入未跟踪新文件；CI 抓到本地漏过的 5 个 IP，见 L29） |
| 2026-10-13 | 新增 D15（DNS 层广告拦截推广进三份 profile，route 层保留兜底） |
| 2026-10-13 | 新增 D16（平台差异矩阵上锁：matrix_platform_stale / profile_drift / 模板覆盖对账，见 L32、L33） |
| 2026-10-13 | 新增 D17（删除桌面端 `clash_api` 空壳；只写 `default_mode` 既不监听也不分流，却创建统计组件） |
| 2026-10-13 | 新增 D18（组 tag emoji 化 `🚀 Proxy` / `🤖 AI` / `🚫 AD`；AD 组删掉 `direct` 只留 `block`） |
| 2026-10-13 | D18 事后补记 + 新增门禁 `dns_server_detour_missing` / `domain_resolver_missing`（组改名时 `dns.servers[].detour` 漏改，见 L35） |
| 2026-10-13 | 新增 D19（门禁负向回归产品化：`tools/negtest.py` + `tools/check-all.sh`，见 L37） |
| 2026-10-13 | 新增 D20（门禁报错自带 `where` 定位：`Report` 加第三参数，先在 §4 / profile / 散文三类门禁落地，见 L38） |
| 2026-10-13 | 新增 D21（矩阵 path ⟺ 内核交叉对账探针；平台能力两页纳入文档快照；三类门禁的复核责任写进铁律 21，见 L39） |
| 2026-10-13 | 新增 D22（新功能覆盖窗口起点显式声明 + inventories 逐版盘点）、D23（1.14.0 走 by-class 口径盘点；只有两条真启用），见 L43 / L44 |
