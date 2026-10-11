# WORKFLOW.md — 完整工作流

> 本文件说明「怎么用这套仓库」和「怎么维护这套仓库」。给 AI 的下手顺序见根目录 `AGENTS.md`，
> 分享链接怎么翻译成 outbound 见 `docs/PROTOCOL-MAPPING.md`。

## 零、这套仓库要解决什么问题

sing-box 迭代快，字段会**改名、合并、废弃、移除**，而且：

- 未知字段 → `FATAL ... json: unknown field` → 配置起不来
- 已移除字段 → `FATAL ... deprecated in X and removed in Y` → 配置起不来
- **已废弃但未移除** → 很多字段 `sing-box check` **完全静默**（典型：`download_detour`）
- **平台差异** → `check` 完全不校验（iOS 写 `strict_route` 照样 exit=0，但没效果）

所以只靠"让 AI 背文档"必然出错。本仓库把这四类知识**固化成可执行的检查**：

| 风险 | 兜底手段 |
|---|---|
| 未知字段 / 已移除字段 | `sing-box check`（内核自己报） |
| 已废弃未移除字段 | `docs/version-matrix.json` + `tools/audit.py` |
| 平台能力差异 | `docs/PLATFORM-MATRIX.md` + `tools/audit.py` |
| 引用完整性（出站/规则集/DNS server 不存在） | `tools/audit.py`（`check` 不校验！） |
| 规则集**顺序**（放行/拦截/分流先后错了等于没加） | `tools/audit.py` 的 Jinx 顺序检查 |
| 上游又改了 | `tools/upgrade-check.py` |

## 一、目录职责

```
singbox_version.txt        当前锁定的正式版（唯一真相）
AGENTS.md                  AI 入口与铁律
README.md                  人类入口
docs/PROTOCOL-MAPPING.md   分享链接 → outbound 字段映射（核心知识）
docs/PLATFORM-MATRIX.md    三平台能力差异
docs/version-matrix.json   机器可读字段生命周期（audit.py 的依据）
docs/VERSION-MATRIX.md     上表的人读版（由 tools/gen-docs.py 生成）
docs/schema.json           sing-box 官方 schema（字段白名单）
docs/upstream-*.md         上游 deprecated / migration / changelog / tun 的本地快照
profiles/<大版本>/          可运行配置（**占位节点**），按平台分文件
local/                      【不提交】本机真实节点配置（.gitignore 已忽略，仅存本地）
nodes/nodes.example.json   用户节点在该仓库里的书写示例
templates/                 片段骨架（节点、分流组）
tools/audit.py             门禁
tools/upgrade-check.py     升级巡检
tools/gen-docs.py          由 JSON 生成人读版矩阵
archive/                   旧大版本配置归档
```

**为什么 `profiles/` 按大版本分目录**：1.14 的配置在 1.15 上可能直接 `FATAL`（例如 1.17 移除
`stack` 后就起不来）。按大版本分目录后，升级＝新开一个目录，旧配置原地保留、随时可回退。

## 二、流程 A：用户给节点 → 出配置（最高频）

### A0. 产物落哪里（先看这条，别搞错）

| 产物 | 位置 | 是否提交 |
|---|---|---|
| 只含占位节点的骨架 | `profiles/<ver>/<platform>-lazy.json` | ✅ 提交 |
| **含真实节点的成品** | `local/<platform>.json` | ❌ **永不提交** |
| 给用户下载的成品 | 仓库外任意位置（如桌面 `android-lazy-test.json`） | ❌ 不提交 |

**铁律：任何时候仓库都不放真实节点，含真实节点的文件仅存留本地。**

- `local/` 已写进 `.gitignore`，`git status` 看不到它。
- `tools/audit.py` 内置 `placeholder_server` 检查：只要 `profiles/` 下出现非 `.example.com`
  这类占位域名的 `server`，直接报 ERROR。所以"不小心把真实节点写进 profiles"会在门禁那步被挡住。
- 提交前可再自查一遍：`git status` 应只有 `profiles/` / `docs/` / `tools/` 等预期改动。

### A1. 收集输入

需要用户提供：

1. **节点分享链接**（可多个）：`vless://…` `vmess://…` `trojan://…` `hysteria2://…` `ss://…` …
2. **落点分流组**：`Proxy`（普通外网）、`AI`（AI 类网站走更干净的出口）、`AD`（广告拦截）
3. **目标平台**：Android / iOS / Windows
4. （可选）**是否把这些节点合并进现有 Auto 组**

缺哪个就问，不要自己猜。用户只说"A 放 AI 组"，那就只动 AI 组。

### A2. 查版本

```bash
cat singbox_version.txt          # 例如 1.14.3   2026-10-12
```

配置必须能在这个版本上跑起来。如果用户客户端版本比这个低，先让用户升级客户端
（正式版之间也可能有字段移除，例如 1.13 → 1.14 移除了 legacy DNS server 格式）。

### A3. 翻译链接

打开 `docs/PROTOCOL-MAPPING.md`，找到对应协议的小节，逐字段抄。

三条最容易出错的：

- **`vmess://` 后面是 base64**，解出来是 JSON；字段名是 v2rayN 的（`scy` `aid` `net` `type`），
  sing-box 的字段名不一样（`security` `alter_id` `transport.type`）。
- **`ss://` 有两种形态**：`ss://base64(method:password)@host:port#tag` 和
  `ss://base64(method:password@host:port)#tag`。都要能识别。
- **`hysteria2://` 的 `user:pass` 里 user 部分官方客户端会忽略**，整串 `user:pass` 可能都被
  当成密码。以客户端实际发的为准，拿不准就问用户。

### A4. 落地到配置

从 `profiles/<版本>/<平台>-lazy.json` 拿骨架（**不要新写一份配置**），然后：

1. 在 `outbounds[]` 末尾追加节点对象，`tag` 用「节点名-地区-协议」这种可读名，
   且**不得与既有 tag 重复**（`Proxy` `AI` `AD` `Auto` `direct` `block` 是保留名）。
2. 把新 tag 加进目标分流组的 `outbounds` 数组。
   建议同时加进 `Auto`（urltest）——除非用户明确说不要。
3. **不要动** `route.rules`、`dns`、`inbounds`、`rule_set`，除非用户另外要求。
   其中规则集与规则顺序是**固定骨架**（见 `AGENTS.md` 的「固定规则集清单」）：
   `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`，少一个、换个位置都不行。
4. `AD` 分组**只允许** `block` 和 `direct`，永远不要把代理节点放进去。

### A5. 跑门禁

```bash
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
```

`audit.py` 会自己找 `sing-box`，也可以显式指定：

```bash
python tools/audit.py --singbox "C:/path/to/sing-box.exe" profiles/1.14/ios-lazy.json --platform ios
# 或设环境变量
export SINGBOX_BIN=/path/to/sing-box
```

要求：**0 ERROR**。有 ERROR 不许交付。WARN 要看清是什么，并写进给用户的说明里。

### A6. 交付

回复里必须写清：

- 目标 **sing-box 正式版号**
- 目标 **平台**
- 每个新节点**落在哪个组**
- audit 结论（`sing-box check` 是否通过、有没有 WARN）
- **完整 JSON**（能直接复制粘贴的那种，不要只给 diff）
- 一句提醒：配置里的占位域名（`node-01.example.com`）必须已被替换成真实地址；
  含真实节点的成品放 `local/`，**不要提交进仓库**

## 三、流程 B：上游发布新正式版

### B1. 巡检

```bash
python tools/upgrade-check.py
```

报告包含：最新正式版号、文档快照差异、矩阵对账、升级风险、受影响配置。

### B2. 判断跨度

- **补丁版（1.14.2 → 1.14.3）**：通常只是修 bug，配置一般不用改。仍要跑一遍报告。
- **小版本（1.14 → 1.15）**：一定有废弃项。**必须**逐条处理。
- **跨多个小版本**：按版本顺序逐段处理 `docs/upstream-deprecated.md`。

### B3. 处理废弃项

对报告里每一条：

1. 找到官方原文（`docs/upstream-deprecated.md` 对应段 + 链接的 migration 锚点）
2. 在 `docs/version-matrix.json` 的 `entries[]` 里补一条，字段含义：

```json
{
  "id": "唯一标识",
  "kind": "deprecated | removed | platform | semantic | info",
  "deprecated_in": "1.15.0",
  "removed_in": "1.17.0",
  "path": "inbounds[type=tun].stack",
  "replacement": "改成什么",
  "doc": "官方链接",
  "note": "补充说明"
}
```

`path` 语法（`audit.py` 用的）：

| 写法 | 含义 |
|---|---|
| `route.rule_set[].download_detour` | 数组任意元素 |
| `inbounds[type=tun].stack` | 数组里 `type == "tun"` 的元素 |
| `**.tls.acme` | 任意深度下匹配 |
| `dns.rules[].ip_cidr` | 同上 |

若字段是"某类出站"整体移除（如 `type: wireguard`），用：

```json
"type_check": { "where": "outbounds", "field": "type", "equals": "wireguard" }
```

3. 如果废弃项有前提条件，用 `require_present` / `require_absent` 限定，例如
   "只有 DNS 规则带 `action` 时 `strategy` 才算废弃"：

```json
"path": "dns.rules[].strategy",
"require_present": ["action"]
```

### B4. 改配置

```bash
cp -r profiles/1.14 profiles/1.15
# 在 profiles/1.15/ 里逐项删除/替换已废弃字段
python tools/audit.py --version 1.15.0 profiles/1.15/*.json
```

`--version` 参数就是"假设我在这个版本上跑"——用它可以**提前**发现"升到新版会炸什么"。

### B5. 收尾

```bash
python tools/gen-docs.py          # 重新生成人读版矩阵
python tools/audit.py             # 全仓库配置体检
# 全部 0 ERROR 后：
echo "1.15.0  checked 2026-xx-xx" > singbox_version.txt
python tools/upgrade-check.py --write    # 更新上游文档快照
```

## 四、流程 C：用户反馈"跑不起来"

按报错形态分流：

| 报错 | 原因 | 处理 |
|---|---|---|
| `FATAL ... json: unknown field "xxx"` | 字段名写错，或该版本没有这个字段 | 查 `docs/schema.json` 是否有该字段；查 `docs/VERSION-MATRIX.md` 是否已改名 |
| `FATAL ... deprecated in X and removed in Y` | 用了已移除字段 | 查 `docs/VERSION-MATRIX.md` 的替代写法 |
| `FATAL ... decode config at` 后面跟着具体路径 | 类型/枚举值不对 | 看错误里指出的路径 |
| `FATAL ... initialize outbound[n]: invalid public_key / illegal base64` | 密钥格式不对 | reality public_key 必须是合法 base64url；SS 2022 密码必须是合法 base64 |
| `FATAL ... http_client is conflict with deprecated download_detour field` | 两者同时出现 | 删掉 `download_detour` |
| 启动成功但某类流量走错 | 平台能力 / 规则顺序 | 查 `docs/PLATFORM-MATRIX.md`、检查 `route.rules` 顺序 |
| 崩溃/无日志 | 工作目录问题 | Android 看 `$working_directory/stderr.log`；Windows 看 `C:\ProgramData\sing-box-daemon` |

**修完必须回写**：把这次踩坑补进 `docs/PROTOCOL-MAPPING.md` 的"常见解码坑"表，
或 `docs/version-matrix.json`。否则下次还会踩。

## 五、维护这张表的规矩

1. **`docs/version-matrix.json` 是唯一真相**，`docs/VERSION-MATRIX.md` 由它生成。
2. 每条 `removed_in` 必须能在 `docs/upstream-deprecated.md` 里找到原文。
3. 不确定"什么时候移除"的，`removed_in` 留空或写 `null`，别猜。
4. 每条都要有 `doc` 链接。
5. 改完必须 `python tools/audit.py` 全绿才算完。

## 六、常见误区

| 误区 | 事实 |
|---|---|
| "`sing-box check` 过了就没问题" | 错。`download_detour` 这类废弃字段它一句话都不说，平台能力也不校验 |
| "字段没了内核会提示" | 未知字段/已移除字段会，**已废弃未移除的常常不会** |
| "iOS 和 Windows 配置可以通用" | 大部分可以，但 `strict_route`、`clash_api`、TUN 地址这些要分开 |
| "规则集用 GitHub raw 就行" | 国内经常打不开，必须走 jsdelivr CDN，且配置里显式指定下载用的 `http_client` |
| "广告用 `category-ads-all` 就够了" | 本仓库用 Jinx (`jinx-ads`) + 秋风 (`awanue-ads`)，且**必须**配 `jinx-direct` 放行集，顺序 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| "规则顺序无所谓" | 顺序错了等于没加。`geosite-cn` 排在拦截之前，国内广告域名会先命中直连，广告规则再无机会执行 |
| "`cache_file.path` 可以写 `../cache/cache.db`" | sing-box **不会**自动建父目录，父目录不存在直接 `FATAL` 起不来。写 `cache.db` |
| "分流组越多越好" | 本仓库只要 `Proxy` / `AI` / `AD` 三个 + `direct` / `block` |
