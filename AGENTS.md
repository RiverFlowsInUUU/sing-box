# AGENTS.md — sing-box 配置生成工作流（AI 入口）

> 本文件是**给 AI 读的入口**。任何人（或任何 AI）拿到本仓库后，按本文流程即可根据用户提供的
> 节点分享链接，生成**当前 sing-box 正式版可实际运行**的 Android / iOS / Windows 配置。

## 0. 一句话任务

用户只给**节点分享链接**（`vmess://` `vless://` `trojan://` `hysteria2://` `ss://` `anytls://` …）
和**想要的落点**（Proxy / AI / AD 三个分流组之一），你负责：

1. 查证**当前正式版**是什么版本、有哪些字段已废弃/已移除 → `singbox_version.txt` + `docs/VERSION-MATRIX.md`
2. 用 `docs/PROTOCOL-MAPPING.md` 把分享链接翻译成 `outbounds[]` 里的一个节点对象
3. 把该节点塞进用户指定的分流组的 `outbounds` 列表
4. 用 `tools/audit.py` 跑一遍门禁（含 `sing-box check`）
5. 输出**平台对应**的完整 JSON 给用户

**不要凭记忆写字段。** 每个字段都必须能在 `docs/PROTOCOL-MAPPING.md` 或 schema 里查到。

## 1. 硬性铁律

| # | 铁律 |
|---|------|
| 1 | **只面向正式版**。现行正式版记在仓库根 `singbox_version.txt`；不用 `-alpha` / `-beta` / `-rc` 字段去写配置 |
| 2 | **未知字段 = 致命错误**。sing-box 对未知字段直接 `FATAL ... json: unknown field`，启动失败 |
| 3 | **已移除字段 = 致命错误**。见 `docs/VERSION-MATRIX.md` 的"已移除"列 |
| 4 | **`check` 通过 ≠ 配置正确**。`check` 对"已废弃但未移除"的字段可能完全静默（例如 `download_detour`），也不校验平台能力、不校验规则集顺序。必须同时过 `docs/VERSION-MATRIX.md` 和 `docs/PLATFORM-MATRIX.md` |
| 5 | **平台能力不同**。iOS/Android 不支持 `strict_route`；Android 无 `process_name` 权限等。见 `docs/PLATFORM-MATRIX.md` |
| 6 | **分流组只有三个**：`Proxy`（默认代理）、`AI`、`AD`；再加 `direct` 与 `block` 两个出站。国内/私有/广告**不出组**，用规则直连或落 AD |
| 7 | **任何时候仓库都不放真实节点**。`profiles/` 下只允许占位域名（`node-01.example.com`）；含真实凭据的配置一律写进仓库外的 `local/`（已在 `.gitignore`），**仅存本地，永不提交、永不推送**。`audit.py` 有 `placeholder_server` 检查兜底 |
| 8 | **规则集走 CDN**，不用 `raw.githubusercontent.com`。CDN 前缀统一 `https://testingcf.jsdelivr.net/gh/`（也可用 `cdn.` / `fastly.` / `gcore.` 镜像） |
| 9 | **广告规则集用 Jinx**，不用 `MetaCubeX` 的 `category-ads-all`。拦截集 = `jinx-ads` + `awanue-ads`；这两个**必须**先跟 `jinx-direct` 放行集，且顺序为 `jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn` |
| 10 | **旧版本配置只归档不删除**（`archive/<大版本>/`） |

### 固定规则集清单（不要自行改动）

| tag | 用途 | 格式 | 来源 | update_interval |
|---|---|---|---|---|
| `jinx-direct` | 白名单放行（47 条，包含被国内大厂 SDK 误拦的合法域名） | `source` | `RiverFlowsInUUU/Jinx@main/sing-box-direct.json` | `1d` |
| `jinx-ads` | 广告拦截（3901 条） | `source` | `RiverFlowsInUUU/Jinx@main/sing-box-ads.json` | `1d` |
| `awanue-ads` | 广告拦截补充（秋风规则，965 条） | `source` | `TG-Twilight/AWAvenue-Ads-Rule@main/Filters/AWAvenue-Ads-Rule-Singbox.json` | `1d` |
| `geosite-private` | 局域网/私有域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geosite-ai` | AI 服务域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geosite-cn` | 中国大陆域名 | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |
| `geoip-cn` | 中国大陆 IP | `binary` | `MetaCubeX/meta-rules-dat@sing` | `7d` |

全部 URL 前缀统一 `https://testingcf.jsdelivr.net/gh/`，全部带 `"http_client": "ruleset-dl"`。

**顺序铁律**（Jinx 官方要求，实测验证过为什么）：

```
jinx-direct     → outbound direct      ✅ 白名单放行，必须最先
jinx-ads        → outbound AD          🚫 拦截
awanue-ads      → outbound AD          🚫 拦截（必须排在 jinx-ads 之后）
geosite-cn      → outbound direct      🚦 常规分流，必须在拦截之后
```

原因：国内广告域名多数同时也属「中国大陆域名」。`geosite-cn` 若排到拦截之前会先命中放行，广告规则再无机会执行。
秋风（`awanue-ads`）与 Jinx 判定标准不同，**会拦掉 Jinx 白名单里的 8 个域**，所以必须排在 Jinx 之后，
且前面要有 `jinx-direct` 兵底。

## 2. 仓库结构

```
AGENTS.md                     ← 你在读的文件（AI 入口）
README.md                     ← 人类入口
singbox_version.txt           ← 当前正式版号 + 核查日期（唯一的版本真相）
docs/
  WORKFLOW.md                 ← 完整工作流（升级流程 / 生成流程 / 校验流程 / 排障）
  PROTOCOL-MAPPING.md         ← 【核心】分享链接 → outbound 字段映射表
  VERSION-MATRIX.md           ← 逐版本废弃/移除字段总表（由 version-matrix.json 生成，勿手改）
  version-matrix.json         ← 同上，机器可读（audit.py 的依据）
  PLATFORM-MATRIX.md          ← Android / iOS / Windows 能力差异表
  schema.json                 ← sing-box 官方 schema（字段白名单）
  upstream-*.md               ← 上游 deprecated / migration / changelog / tun 快照
profiles/1.14/                ← 按内核大版本归档的可运行配置（占位节点）
  desktop-lazy.json
  android-lazy.json
  ios-lazy.json
templates/groups.json         ← 固定分流组骨架（Proxy / AI / AD / Auto / direct / block）
nodes/nodes.example.json      ← 节点书写格式与分享链接对照示例
tools/
  audit.py                    ← 门禁：结构 + 废弃字段 + 平台能力 + 引用完整性 + sing-box check
  upgrade-check.py            ← 上游有新正式版/新废弃项时报告差异
  gen-docs.py                 ← 由 version-matrix.json 生成 VERSION-MATRIX.md
archive/<大版本>/             ← 旧版本配置归档（只归档不删除）
local/                        ← 【不提交】本机真实节点配置（.gitignore 已忽略）
```

## 3. 三种典型任务

### 任务 A：用户给节点 → 出配置

```
1. cat singbox_version.txt                       # 确认目标正式版
2. 读 docs/PROTOCOL-MAPPING.md 对应协议小节      # 拿到字段清单
3. 读 profiles/<ver>/{platform}-lazy.json        # 拿骨架
4. 按映射表把链接解成 outbound，插到出站列表
5. 把 outbound tag 加进用户指定的分流组（Proxy / AI / AD）的 outbounds 数组
6. python tools/audit.py profiles/<ver>/<platform>-lazy.json --platform <p>
7. 输出完整 JSON（不是 diff、不是片段）

**产物落哪里**（关键）：
- 只含占位节点的骨架 → `profiles/<ver>/<platform>-lazy.json`
- **含真实节点的成品 → `local/<platform>.json`，绝不写进 `profiles/`，绝不提交**
- 给用户的成品可以放在仓库外任意位置（例如 `android-lazy-test.json`）再发送
```

### 任务 B：上游发布新正式版

```
1. python tools/upgrade-check.py                 # 对比版本 + 抓 deprecated/migration
2. 按报告改 docs/version-matrix.json
3. python tools/gen-docs.py                      # 重新生成 VERSION-MATRIX.md
4. cp -r profiles/<旧ver> profiles/<新ver>，按报告逐项修正
5. python tools/audit.py --version <新ver> profiles/<新ver>/*.json
6. 更新 singbox_version.txt；确认无误后 upgrade-check.py --write 刷新文档快照
```

### 任务 C：用户反馈"跑不起来"

```
1. 先看错误原文（sing-box 报错自带 ^ 指向出错路径）
2. FATAL unknown field  → 字段名写错或版本不支持 → 查 VERSION-MATRIX
3. FATAL legacy/removed → 用了已移除字段 → 查 VERSION-MATRIX 的迁移写法
4. 静默但功能不对      → 查 PLATFORM-MATRIX 平台能力
5. 把这次踩坑写回对应文档
```

**分岔点：错误是 check 阶段还是 run 阶段？**

- `sing-box check -c` 就能报的 → 字段名/类型/枚举问题，直接查矩阵。
- **`check` exit=0，但 `run` 启动即 FATAL** → 属于初始化期问题。已收录的典型：
  `FATAL ... initialize rule-set[n]: ... detour to an empty direct outbound makes no sense`。
  这是「下载用的 direct 出站是空的」。处理：给 `direct-download` 加
  `domain_resolver`（或 `bind_interface` / `inet4_bind_address` / `routing_mark`）。
  **`domain_strategy` / `network_strategy` 不算数**（已 `schema:"omit"`）。
- 修完必须跑 `python tools/audit.py --run --run-seconds 20` 复现一次，确认不再有 `FATAL`；
  静态检查 + `check` + `run` 三层都过才算修完。

## 4. 校验命令

```bash
# 四项门禁（结构 / 废弃字段 / 平台能力 / 引用完整性）+ sing-box check
# audit.py 自己找 sing-box；找不到可用 --singbox 或环境变量 SINGBOX_BIN 指定
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
python tools/audit.py --singbox "C:/path/to/sing-box.exe" --version 1.14.3

# 只跑 sing-box 官方 check
sing-box check -c profiles/1.14/ios-lazy.json

# ★ 交付 / 排错前必跑：真启动一次，抓 check 看不见的启动期 FATAL
#   （会自动把 tun 入站临时换成 mixed、cache_file 指到临时目录；会真的连网拉规则集）
python tools/audit.py --run --run-seconds 20

# 上游巡检 / 重新生成人读版矩阵
python tools/upgrade-check.py
python tools/gen-docs.py
```

> **铁律：`sing-box check` 只反序列化、不初始化。**
> “check 全绿”**不等于**“能启动”。空的 direct 出站、规则集下不下来、
> 初始化期的引用问题，check 一律 exit=0。交付前至少跑一次 `--run`。

`audit.py` 退出码：`0` 全通过，`1` 有 ERROR（禁止交付）。
WARN 可以交付，但必须在回复里向用户说明。

`--version` 用来**预演**「假设客户端升级到这个版本会怎样」，例如
`python tools/audit.py --version 1.15.0 profiles/1.14/ios-lazy.json` 会提前告诉你要删 `stack`。

## 5. 交付给用户时的固定话术

必须包含：

- 目标 **sing-box 版本号**（正式版）
- 目标 **平台**（Android / iOS / Windows）
- 新增节点落在**哪个分流组**
- audit 结果（四项门禁是否全绿，有哪些 WARN）
- 完整 JSON（可复制粘贴的那种）

不得声称"已实测联网可用"——除非用户在本机真跑了 `sing-box run`。

## 6. 节点占位规则

- `profiles/` 里的文件**永远是占位值**（`node-0X.example.com`），它只是骨架与格式参考。
- 用户给了真实分享链接后，**替换占位、不要新增重复节点**，产物写进 `local/<platform>.json`。
- `local/` 已列入 `.gitignore`；提交前用 `git status` 复核，并可用
  `git grep -n -f <(printf '%s\n' "$真实域名")` 之类方式确认没有真实节点混进暂存区。
- 判断标准很简单：`python tools/audit.py` 对 `profiles/` 下任何文件报
  `placeholder_server` 就是错误，必须把真实节点挪出 `profiles/`。
