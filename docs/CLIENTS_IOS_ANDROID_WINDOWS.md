# CLIENTS_IOS_ANDROID_WINDOWS.md — 三端差异与交付

> 本文是 [`AI_SYNC_WORKFLOW.md`](AI_SYNC_WORKFLOW.md) **模块 4** 的详细展开。
> 一句话：仓库只留模板，我提供节点后 AI 生成**三端各自**的可运行配置，**直接发给我，不写入仓库**。
>
> ⚠️ **三端差异必须以 sing-box 上游官方文档为准**，不得凭经验猜测。
> 本文件只描述**流程、位置、交付格式**；具体某个功能在哪端可用，必须查官方。

---

## 一、三端与模板的对应关系

| 端 | 模板文件（本仓实际结构） | 目标客户端 |
|---|---|---|
| **Windows / Linux 桌面版** | `profiles/<大版本>/desktop-lazy.json` | sing-box 桌面内核 |
| **Android** | `profiles/<大版本>/android-lazy.json` | sing-box for Android |
| **iOS / iPadOS** | `profiles/<大版本>/ios-lazy.json` | sing-box for Apple |

> 📌 **任务描述与本仓结构的差异**：任务描述举例 `templates/ios`、`templates/android`、`templates/windows`，
> 本仓实际是**按内核大版本分目录、按平台分文件**（上表）。两者是同一件事的两种组织方式，
> 本文按**实际结构**描述。`templates/` 目录在本仓**只有一个 `groups.json`**（分流组骨架），
> 不是平台模板目录。三端索引已建在 `templates/{ios,android,windows}/`，见
> [`../templates/README.md`](../templates/README.md)。
>
> 大版本目录如 `1.14/` 对应 `singbox_version.txt` 锁定版本的主次版本号。

**其他相关文件**

| 文件 | 作用 |
|---|---|
| `templates/groups.json` | 三个分流组的固定骨架 |
| `nodes/nodes.example.json` | 节点书写示例（分享链接 ↔ JSON 对照） |
| `docs/PLATFORM-MATRIX.md` | 三端能力差异对照表（本仓维护） |
| `archive/<大版本>/` | 旧版本配置归档（只归档不删除） |
| `local/` | 【不提交】真实节点配置 |

---

## 二、模板 vs 实际配置（严格分开）

| | 模板 | 实际配置 |
|---|---|---|
| 位置 | `profiles/` | **不写入仓库** |
| 节点 | 占位（`node-0X.example.com`） | 我提供的真实节点 |
| 内容 | 骨架 + 格式参考 | 完整可运行 |
| 去向 | 提交、公开 | **直接发给我** |

**硬规则**：

- 仓库中**只保留模板**。
- AI 生成的实际配置**直接发给我** —— 不得写入仓库、不得提交、不得持久化节点。
- 真实节点**永不进 git**；`profiles/` 下出现非占位域名会被 `placeholder_server` 门禁报 ERROR。

> 📌 **现状说明**：任务描述称「仓库不保存可运行配置」，但本仓 `profiles/1.14/` 下存有三份
> **可运行配置**（占位节点、无真实凭据）—— 这是仓库既有设计，且是门禁的对账基准。
> 本仓保留三份可运行配置作为门禁对账基准；**不是**真实节点，已受 `placeholder_server` 保护。

---

## 三、三端差异处理原则

对每一个功能/字段，三端**分别**标注：

| 标注 | 含义 |
|---|---|
| **可用** | 该端支持，可写入配置 |
| **不适用** | 该端场景不存在此需求 |
| **需客户端支持** | 内核支持，但该端客户端尚未提供入口 |
| **不确定** | 上游文档未写明 —— **不得由另外两端推断本端** |

**判断依据必须写出**，例如：需要 TUN、需要特定协议、需要客户端 UI 支持、
仅服务端、仅移动端、平台限制。

**已知的差异落点**（**以官方文档为准**，此处仅提示去查）：

- 平台能力差异表在 [`PLATFORM-MATRIX.md`](PLATFORM-MATRIX.md)。
- 该表 §4 与三份 profile 由 `matrix_platform_stale` / `profile_drift` 逐格对账，
  §4 未登记的差异一律报 ERROR。
- ⚠️ 平台的能力清单（§1/§1a/§2/§2a）**无法机器核对**（没有可靠的官方机读源），
  只能人工按「来源」一栏复核 —— 别误以为它也上了锁。

---

## 四、生成配置的流程

```
0. 收集输入（见 §四·A1）—— 缺哪个就问，不要自己猜
1. 我提供节点（分享链接）
2. Agent 读取对应端的模板     profiles/<大版本>/<平台>-lazy.json
3. 按官方映射翻译节点          docs/PROTOCOL-MAPPING.md
4. 把节点放进我指定的分流组     🚀 Proxy / 🤖 AI（🚫 AD 只放 block，不放节点）
5. 套用该端的差异            → 依据上游官方文档 + PLATFORM-MATRIX.md
6. 跑校验                    → audit.py / check-all.sh（见 §四·A5）
7. 按 §五 格式直接发给我
```

### A0. 产物落哪里（先看这条，别搞错）

| 产物 | 位置 | 是否提交 |
|---|---|---|
| 只含占位节点的骨架 | `profiles/<版本>/<平台>-lazy.json` | ✅ 提交 |
| **含真实节点的成品** | `local/<平台>.json` | ❌ **永不提交** |
| 给我下载的成品 | 仓库外任意位置 | ❌ 不提交 |

**铁律：任何时候仓库都不放真实节点。**

- `local/` 已写进 `.gitignore`，`git status` 看不到它。
- `tools/audit.py` 内置 `placeholder_server` 检查：`profiles/` 下出现非占位域名的 `server` 直接报 ERROR。
  所以「不小心把真实节点写进 profiles」会在门禁那步被挡住。
- 提交前可再自查一遍：`git status` 应只有 `profiles/` / `docs/` / `tools/` 等预期改动。

### A0bis. 改我给的**现成配置**时：先做字段差异比对

如果我不是「从零给链接」，而是给了一份**已有配置**让你改（哪怕只改一个字段），
**必做字段差异比对**，并把每个差异都说得出理由：

```bash
python tools/diff_config.py <我的原始配置.json> <你改完的.json>
```

输出三段：`只在原始配置里（可能被我删了）` / `只在生成配置里（可能是我加的）` / `两边都有但值变了`。
**说不出原因的差异，一律按原始配置保留。**

来历：曾凭印象重写模板，把用户原始配置里本来就有的 `auto_detect_interface: true` 删了，
直接导致真机没网（`LESSONS.md` L4）。

### A1. 收集输入

需要我提供：

1. **节点分享链接**（可多个）：`vless://` `vmess://` `trojan://` `hysteria2://` `ss://` …
2. **落点分流组**：代理组（普通外网）/ 智能组（AI 类网站走更干净的出口）
3. **目标平台**：Android / iOS / Windows
4. **智能组要放哪些节点**（智能组与代理组是**两个独立的 urltest 组**，各自在组内优选；
   我不说就先把所有代理节点都放进去，**不要**用代理组当子节点）

**缺哪个就问，不要自己猜。** 我只说「A 放智能组」，那就只动智能组。

### A2. 查版本

```bash
cat singbox_version.txt          # 例如 1.14.3   2026-10-12
```

配置必须能在这个版本上跑起来。如果我的客户端版本比这个低，先让我升级客户端
（正式版之间也可能有字段移除，例如 1.13 → 1.14 移除了 legacy DNS server 格式）。

### A3. 翻译链接（三条最容易出错的）

- **`vmess://` 后面是 base64**，解出来是 JSON；字段名是 v2rayN 的（`scy` `aid` `net` `type`），
  sing-box 的字段名不一样（`security` `alter_id` `transport.type`）。
- **`ss://` 有两种形态**：`ss://base64(method:password)@host:port#tag` 和
  `ss://base64(method:password@host:port)#tag`。都要能识别。
- **`hysteria2://` 的 `user:pass`**：官方客户端会忽略 user 部分，整串可能都被当成密码。
  拿不准就问。

### A4. 落地到配置

从 `profiles/<版本>/<平台>-lazy.json` 拿骨架（**不要新写一份配置**），然后：

1. 在 `outbounds[]` 追加节点对象，`tag` 用可读名，且**不得与既有 tag 重复**
   （三个分流组 tag 与 `direct` `block` 都是保留名）。
2. 把新 tag 加进目标分流组的 `outbounds` 数组。
   代理组与智能组都是 urltest，加进去即自动测速 —— **不再有单独的 Auto 组**；
   两个组的 `outbounds` 里**只放真实节点，不要嵌套组 tag**。
3. **不要动** `route.rules`、`dns`、`inbounds`、`rule_set`，除非我另外要求。
   规则集与规则顺序是**固定骨架**：`jinx-direct` → `jinx-ads` → `awanue-ads` → `geosite-cn`，
   少一个、换个位置都不行。若启用了 DNS 层前置拦截，`dns.rules` 里还有**第二套顺序**
   需要同步维护 —— 两张表各写各的，排错即静默失效（L28）。
4. 去广告组**只允许** `block`，永远不要把代理节点放进去。
5. **组 tag 逐字用规范名**：`🚀 Proxy` / `🤖 AI` / `🚫 AD`（emoji + 一个 ASCII 空格 + 名字）。
   写错一个字符 = `route.final` / 规则引用全部落空（`check` 不会报）。

### A5. 跑门禁

```bash
# 推荐：一条命令串完三层（静态门禁 + 负向回归 + 逐份 sing-box check）
bash tools/check-all.sh
bash tools/check-all.sh --run      # 再加启动级验证（约 1 分钟）

# 只想跑单份时：
python tools/audit.py profiles/1.14/ios-lazy.json --platform ios
# 交付前至少再真启动一次（check 只反序列化，验不了能不能起来）
python tools/audit.py --run --run-seconds 20 profiles/1.14/ios-lazy.json --platform ios
```

`audit.py` 会自己找 `sing-box`，也可以显式指定（`--singbox <path>` 或 `SINGBOX_BIN`）。

要求：**0 ERROR**。有 ERROR 不许交付。WARN 要看清是什么，并写进给我的说明里。

### A6. 交付话术

回复里必须写清：

- 目标 **sing-box 正式版号**
- 目标 **平台**
- 每个新节点**落在哪个组**
- audit 结论（`check` 是否通过、有没有 WARN）
- **完整 JSON**（能直接复制粘贴的那种，不要只给 diff）
- 一句提醒：配置里的占位域名必须已被替换成真实地址；含真实节点的成品放 `local/`，**不要提交**
- ⚠️ **不得声称「实测能上网」** —— 本机环境不可信，`check` / `--run` 只证明**能启动**。
  真机联网结论只能由我给出。若我报了新问题，修完追加一条 `LESSONS.md` 条目。

### A7. 修完必须回写

把这次踩的坑补进 [`PROTOCOL-MAPPING.md`](PROTOCOL-MAPPING.md) 的「常见解码坑」表，
或 `docs/version-matrix.json`。**否则下次还会踩。**

**本仓现有的加速路径**：`python tools/mknode.py '<链接>' -p <平台> -g <组>`
一条命令完成 3–6 步（解码 → 套骨架 → 加组 → 跑门禁 → 落 `local/<平台>.json`）。
详见 [`AGENTS.md`](../AGENTS.md)。

---

## 五、交付格式

**按端分别交付**，每条包含：

```
适用端：         iOS / Android / Windows（明确哪一端）
基于版本：       sing-box <稳定版号>
模板来源：       profiles/<大版本>/<平台>-lazy.json
变更点：         <相对模板改了什么、为什么>
完整可粘贴配置： <完整 JSON，不是 diff、不是片段>
校验命令与结果： <命令 + 结果>
风险与待确认项： <未验证项、平台差异、待人工判断>
```

**校验命令**

```bash
python tools/audit.py local/<平台>.json --platform <平台>
bash tools/check-all.sh              # 全仓；加 --run 再验启动期
```

> ⚠️ **不得声称「已实测联网可用」** —— 除非真在目标端跑过。
> ⚠️ **`sing-box check` 通过 ≠ 配置正确**：它不校验平台能力、不校验规则集顺序，
> 对「已废弃但未移除」的字段可能完全静默，且只反序列化、不初始化。

---

## 六、红线

- ❌ 不得把实际配置或节点写入仓库
- ❌ 不得凭经验猜测三端差异（必须查官方）
- ❌ 不得由另外两端的结论推断第三端
- ❌ 不得宣称「已实测联网可用」（除非真跑过）
- ❌ 不得跳过校验就交付
