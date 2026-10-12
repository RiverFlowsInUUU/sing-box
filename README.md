# sing-box 配置模板仓库

面向 **sing-box 正式版**（非 alpha/beta/rc）的懒人配置模板 + 一套"AI 也能照做"的工作流。

**核心用途**：你只给节点分享链接（`vmess://` / `vless://` / `trojan://` / `hysteria2://` / `ss://` …）
和目标平台，任何 AI 读完本仓库的文档就能生成一份能在 sing-box 正式版上跑起来的完整配置。

## 快速开始

### 我是用户，想直接拿配置

1. 打开 `profiles/1.14/`，按平台选：
   - `desktop-lazy.json` — Windows / Linux 桌面版
   - `android-lazy.json` — Android
   - `ios-lazy.json` — iOS / iPadOS
2. 把里面**所有占位节点**（`node-0X.example.com` 那几条）删掉。
3. 按 `docs/PROTOCOL-MAPPING.md` 把你的分享链接翻译成节点对象，追加进 `outbounds`。
4. 把新节点的 `tag` 加进对应分流组的 `outbounds` 数组：
   - `Proxy` — 普通外网（**本身就是 urltest 自动测速组，加进去即完成**）
   - `AI` — AI 类站点（**同样是 urltest**，放你希望 AI 走的那几个节点）
   - `AD` — 广告拦截（**只能放 `block` / `direct`**）
5. 导入客户端。

更省事的做法：把仓库链接 + 分享链接 + 目标平台直接丢给 AI，让它按 `AGENTS.md` 生成。

### 我是 AI / 想按规范生成

从 `AGENTS.md` 开始读，它是给 AI 的入口。

## 仓库结构

```
AGENTS.md                     AI 入口与 17 条铁律
README.md                     你在读的文件
singbox_version.txt           当前锁定的 sing-box 正式版
docs/
  LESSONS.md                  【开工先读】事故台账：现象→根因→修法→对应门禁
  DECISIONS.md                【开工先读】决策记录：新功能为何启用/不启用、备选方案、前提风险
  WORKFLOW.md                 完整工作流（怎么用 + 怎么维护）
  PROTOCOL-MAPPING.md         【核心】分享链接 → outbound 字段映射
  PLATFORM-MATRIX.md          Android / iOS / Windows 能力差异
  VERSION-MATRIX.md           废弃/移除字段总表（人读版，自动生成）
  version-matrix.json         同上，机器可读（门禁的依据）
  schema.json                 sing-box 官方 schema（字段白名单）
  upstream-*.md               官方 deprecated / migration / changelog / tun 快照
  evidence/                   事故证据存档（脱敏后入库；铁律 11 的 debug 日志证据）
profiles/1.14/                可运行配置（占位节点）
templates/                    片段骨架
nodes/nodes.example.json      节点书写示例
tools/
  audit.py                    门禁：8 类配置风险 + 教训台账 / 决策记录 / 防泄漏 / 工具自检 / 模板文字
  diff_config.py              两份配置的字段差异比对（铁律 0 的执行工具，跨平台）
  upgrade-check.py            上游有新正式版 / 新废弃项 / 未决策的新功能时报告差异
  gen-docs.py                 由 JSON 生成 VERSION-MATRIX.md（勿手改后者）
archive/                      旧大版本配置归档
```

## 这套仓库解决什么问题

sing-box 迭代快，字段会改名、合并、废弃、移除。而 `sing-box check` 只验证“字段名对不对”，下面每一类它都拦不住：

| 风险 | 只靠 `sing-box check` 会怎样 | 本仓库的兜底 |
|---|---|---|
| 未知字段 | ✅ 会 `FATAL` | `sing-box check` |
| 已移除字段 | ✅ 会 `FATAL` | `sing-box check` + 矩阵表 |
| **已废弃未移除** | ❌ **完全静默**（典型：`download_detour`） | `version-matrix.json` + `audit.py` |
| **平台能力差异** | ❌ **完全不校验**（iOS 写 `strict_route` 也 exit=0） | `PLATFORM-MATRIX.md` + `audit.py` |
| **引用完整性** | ❌ 出站/规则集/DNS server 写错也不报 | `audit.py` |
| **新增能力没决策** | ❌ **完全不知道多了什么**（1.15 的 MASQUE / Tailcat / sing-tun 栈） | `upgrade-check.py` 第 5 节 + `version-matrix.json` 的 `kind=new` + `DECISIONS.md` |
| **真实节点地址泄到公开仓库** | ❌ **完全不校验**（写在 `docs/` 散文里也一样） | `audit.py` 的 `sensitive_ip_in_repo`（扫全部被跟踪文件 + commit message） |
| **门禁自己坏了 / 静默跳过** | ❌ **完全看不出来**（门禁不审自己，工具语法错也能全绿） | `audit.py` 的 `tool_syntax_error` + `tool_selftest_failed` |
| **模板里的文字过期** | ❌ 无影响但会误导人（`templates/groups.json` 的 `_rules_of_thumb`） | `audit.py` 的 `template_thumb_stale` |
| 上游又改了 | —（靠人工发现） | `upgrade-check.py` |

## 门禁命令

```bash
# 体检所有 profile（会自己找 sing-box：ROOT/bin/ 或 PATH，也认 SINGBOX_BIN）
python tools/audit.py

# ⚠️ 本机没装 sing-box 时，--run 会静默降级为 INFO 跳过（看起来照样 PASS）。
#    要真跑就把路径放环境变量（仓库里不许写本机绝对路径）：
#    export SINGBOX_BIN="C:/path/to/sing-box.exe"
python tools/audit.py --run --run-seconds 20

# 单个文件 + 指定平台
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios

# 预演"升到 1.15 会炸什么"
python tools/audit.py --version 1.15.0 profiles/1.14/ios-lazy.json

# 上游巡检：新正式版 / 新废弃项 / 新功能清点（第 5 节）
python tools/upgrade-check.py
```

`audit.py` 退出码：`0` 全通过；`1` 有 ERROR，禁止交付。

除配置门禁外，每次跑还会连带做五道“无参数也会跑”的自检：
教训台账双向校验（`docs/LESSONS.md` ↔ 代码里的门禁 code）、决策记录双向校验（`docs/DECISIONS.md` ↔ 矩阵 `kind=new`）、
防泄漏扫查（被跟踪文件 + commit message）、**工具自检**（`tools/*.py` 能否编译 + 关键工具不变量）、
**模板文字检查**（`templates/groups.json` 的 `_rules_of_thumb` 有没有写过期的口径）。

## 铁律（摘要，详见 `AGENTS.md`）

1. 只面向**正式版**
2. 未知字段 = 致命
3. 已移除字段 = 致命
4. **`check` 通过 ≠ 能启动**——`check` 只反序列化、不初始化。交付前必须 `audit.py --run` 真启动一次
5. 平台能力不同，iOS/Android **没有** `strict_route`
6. 分流组只有 `Proxy` / `AI` / `AD` + `direct` / `block`；`Proxy` 与 `AI` 都是 urltest，组内只放真实节点、不嵌套组
7. **任何时候、任何文件都不放真实节点**——范围是**整个被跟踪仓库**（不只是 `profiles/`，`docs/` 的散文同样公开）；含真实节点的配置只存仓库外的 `local/`（已在 `.gitignore`），永不提交、永不推送。`audit.py` 有 `placeholder_server` + `sensitive_ip_in_repo` 兜底
8. 规则集走 jsdelivr CDN，不用 `raw.githubusercontent.com`
9. 广告规则集用 Jinx；顺序 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`
10. 旧版本配置只归档不删除
11. **不在本机乱试**——本机有 OpenClash 网关会劫持 DNS，本机连通性结论一律作废；只读配置 / 官方文档 / 源码
12. **tun + auto_route 必须写 `route.auto_detect_interface: true`**——不写就是“能启动但没网”
13. 日志里的 `using outbound/selector[AD]: operation not permitted` 是**拦截成功的正常日志**，不要去“修” AD 组；AD 的 `default` 必须始终是 `block`
14. **「只走 IPv4」必须端到端**——`dns.strategy` 只管本地 DNS；`route.rules` 里必须有 `{"action": "resolve", "strategy": "ipv4_only"}`，**且位置必须在 `hijack-dns` 之后、第一个 route/reject/bypass 之前**（放末尾等于没放，因为一命中就 break match），否则目标域名会被原样交给代理服务端解析
15. **出口 IP 的地址族不由客户端决定**——`resolve` 只管到「本地→服务端」这一段；「服务端→目标站」由服务端决定。看到 IPv6 出口先去确认它是不是节点自身的 AAAA 记录，别在本地配置里继续加固
16. **上游新增能力必须显式写下「启用 / 不启用 / 必须跟随」**——不写就是隐式选了“不启用”（往往因为没注意到）。矩阵建 `kind="new"` 条目 + `docs/DECISIONS.md` 记理由与备选方案
17. **改配置、改流程都先拉仓库、先看 diff**——不直接覆盖已有文件（有把已更正的文档改回错误结论的先例）；`git commit` / `git push` / 改 `singbox_version.txt` / 改 `adopt` / 删除任何现有字段 / `upgrade-check.py --write` 这六个动作**必须事先取得用户同意**

每条铁律背后的事故、源码证据与对应门禁见 [`docs/LESSONS.md`](docs/LESSONS.md)。
**开工前先扫一遍那份台账**，那些坑都是真机上踩过的。

## 常见坑

| 坑 | 正确做法 |
|---|---|
| 规则集用 GitHub raw，国内打不开 | 用 `https://testingcf.jsdelivr.net/gh/…`（CDN 前缀统一）|
| `rule_set` 写了 `download_detour` | 已废弃，改用顶层 `http_clients` + 规则集上的 `http_client` |
| `cache_file.path` 写 `../cache/cache.db` | sing-box **不会**自动建父目录，父目录不存在直接 `FATAL`。写 `cache.db` |
| 规则集下载 detour 指向裸的 `direct` 出站 | **启动即 FATAL**：`detour to an empty direct outbound makes no sense`，而 `check` 完全静默。下载走专用 `direct-download`，且它必须带 `domain_resolver` |
| 想用 `domain_strategy: ipv4_only` 把 direct 凑成“非空” | 不行。它已 `schema:"omit"`，**填了也不算数**，而且 1.14 下直接触发 legacy domain strategy 的 FATAL。用 `domain_resolver` |
| reality `public_key` 随便填占位 | 必须是合法 base64url，否则 `FATAL invalid public_key` |
| SS 2022 密码随便填 | 必须是合法 base64（aes-128 解 16 字节、aes-256 解 32 字节） |
| iOS 配置里留了 `strict_route` | Apple 客户端未实现，删掉 |
| 把用户给的真实节点直接写进 `profiles/` 并提交 | 真实节点写 `local/<platform>.json`（不提交）；`audit.py` 的 `placeholder_server` 检查会报 ERROR 拦住 |
| 广告拦截用了 `MetaCubeX` 的 `category-ads-all` | 改用 Jinx 的 `jinx-ads` + 秋风 `awanue-ads`，并配套 `jinx-direct` 放行集 |
| 规则集顺序随意摆 | 顺序错了等于没加：`jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| 用 `resolve` 强制 IPv4，却把它放在 `route.rules` 末尾 | 末尾等于没放：第一条 route/reject 一命中就 break match，resolve 根本没跑。必须紧跟 `hijack-dns` |
| 上游发了新版，只看“什么被废弃了” | 新能力同样要清点：`upgrade-check.py` 第 5 节会列出 changelog 里的新功能，逐条写进矩阵 `kind="new"` + `DECISIONS.md` |
| 看到日志里 `using outbound/selector[AD]: operation not permitted` 以为是坏了 | 这是 `block` 出站拦广告的**正常**输出（`syscall.EPERM`），说明广告确实被拦了。不用改配置；嫌刷屏就把 `log.level` 设成 `"panic"`。详见 `docs/LESSONS.md` L16 |
| tun 配置里没有 `route.auto_detect_interface` | **能启动、不报错，但真机完全没网**（节点全无延迟、只有上传没下载、内存爆 1GB）。这是 Android 唯一可行的防回环手段，`check` 对此完全静默 |
| 拿本机跑出来的连通性当证据 | 本机有 OpenClash 网关会劫持 DNS（无 fakeip 的最小配置也会被返回 `198.18.0.x`），本机结果一律作废。只读配置 / 官方文档 / 源码 |

## 版本

现行锁定版本见 `singbox_version.txt`。上游发布新正式版时的处理流程见 `docs/WORKFLOW.md` 流程 B。

## 声明

- 仓库内所有节点均为**占位值**，不含真实服务器信息。
- 本仓库只做配置生成与校验，**不保证**任何节点的连通性或速度。
- 配置通过 `sing-box check` 只代表**语法与字段合法**，不代表实际能联网。
