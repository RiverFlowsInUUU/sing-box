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
   - `AI` — AI 类站点（默认跟随 `Proxy`）
   - `AD` — 广告拦截（**只能放 `block` / `direct`**）
5. 导入客户端。

更省事的做法：把仓库链接 + 分享链接 + 目标平台直接丢给 AI，让它按 `AGENTS.md` 生成。

### 我是 AI / 想按规范生成

从 `AGENTS.md` 开始读，它是给 AI 的入口。

## 仓库结构

```
AGENTS.md                     AI 入口与 12 条铁律
README.md                     你在读的文件
singbox_version.txt           当前锁定的 sing-box 正式版
docs/
  WORKFLOW.md                 完整工作流（怎么用 + 怎么维护）
  PROTOCOL-MAPPING.md         【核心】分享链接 → outbound 字段映射
  PLATFORM-MATRIX.md          Android / iOS / Windows 能力差异
  VERSION-MATRIX.md           废弃/移除字段总表（人读版，自动生成）
  version-matrix.json         同上，机器可读（门禁的依据）
  schema.json                 sing-box 官方 schema（字段白名单）
  upstream-*.md               官方 deprecated / migration / changelog / tun 快照
profiles/1.14/                可运行配置（占位节点）
templates/                    片段骨架
nodes/nodes.example.json      节点书写示例
tools/
  audit.py                    门禁：结构 + 废弃字段 + 平台能力 + 引用完整性 + 防回灌 + sing-box check
  upgrade-check.py            上游有新正式版 / 新废弃项时的巡检报告
  gen-docs.py                 由 JSON 生成 VERSION-MATRIX.md
archive/                      旧大版本配置归档
```

## 这套仓库解决什么问题

sing-box 迭代快，字段会改名、合并、废弃、移除。而现有工具兜不住这四类问题：

| 风险 | 只靠 `sing-box check` 会怎样 | 本仓库的兜底 |
|---|---|---|
| 未知字段 | ✅ 会 `FATAL` | `sing-box check` |
| 已移除字段 | ✅ 会 `FATAL` | `sing-box check` + 矩阵表 |
| **已废弃未移除** | ❌ **完全静默**（典型：`download_detour`） | `version-matrix.json` + `audit.py` |
| **平台能力差异** | ❌ **完全不校验**（iOS 写 `strict_route` 也 exit=0） | `PLATFORM-MATRIX.md` + `audit.py` |
| **引用完整性** | ❌ 出站/规则集/DNS server 写错也不报 | `audit.py` |

## 门禁命令

```bash
# 体检所有 profile（会自己找 sing-box；也可用 --singbox 指定路径）
python tools/audit.py

# 单个文件 + 指定平台
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios

# 预演"升到 1.15 会炸什么"
python tools/audit.py --version 1.15.0 profiles/1.14/ios-lazy.json

# 上游巡检：有没有新正式版 / 新废弃项
python tools/upgrade-check.py
```

`audit.py` 退出码：`0` 全通过；`1` 有 ERROR，禁止交付。

## 铁律（摘要，详见 `AGENTS.md`）

1. 只面向**正式版**
2. 未知字段 = 致命
3. 已移除字段 = 致命
4. **`check` 通过 ≠ 能启动**——`check` 只反序列化、不初始化。交付前必须 `audit.py --run` 真启动一次
5. 平台能力不同，iOS/Android **没有** `strict_route`
6. 分流组只有 `Proxy` / `AI` / `AD` + `direct` / `block`
7. **任何时候仓库都不放真实节点**——含真实节点的配置只存仓库外的 `local/`（已在 `.gitignore`），永不提交、永不推送
8. 规则集走 jsdelivr CDN，不用 `raw.githubusercontent.com`

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

## 版本

现行锁定版本见 `singbox_version.txt`。上游发布新正式版时的处理流程见 `docs/WORKFLOW.md` 流程 B。

## 声明

- 仓库内所有节点均为**占位值**，不含真实服务器信息。
- 本仓库只做配置生成与校验，**不保证**任何节点的连通性或速度。
- 配置通过 `sing-box check` 只代表**语法与字段合法**，不代表实际能联网。
