# TEMPLATE_MIGRATION.md — 模板 / 闸门文件语法迁移

> 本文是 [`AI_SYNC_WORKFLOW.md`](AI_SYNC_WORKFLOW.md) **模块 3** 的详细展开。
> 一句话：上游升级后语法可能变，**迁移必须逐文件、逐字段、逐端经我确认**，不得自动批量替换。
>
> ⚠️ 唯一权威来源是 sing-box 上游官方 migration 文档 / changelog。本文件只描述**流程与清单格式**，
> 不裁定某个字段是否废弃 —— 那必须查官方依据。

---

## 一、什么是「模板 / 闸门文件」

仓库中**依赖 sing-box 版本语法**的文件，包括：

- 配置模板（本仓为 `profiles/<大版本>/{desktop,android,ios}-lazy.json`）
- 片段骨架（`templates/groups.json`）
- 节点书写示例（`nodes/nodes.example.json`）
- 平台模板（三端有差异的部分）

> 📌 **本仓的模板位置说明**：任务描述里提到 `templates/ios`、`templates/android`、`templates/windows`，
> 但本仓实际是按**内核大版本**分目录、按**平台**分文件：
> `profiles/1.14/desktop-lazy.json`、`profiles/1.14/android-lazy.json`、`profiles/1.14/ios-lazy.json`。
> 本文与 [`CLIENTS_IOS_ANDROID_WINDOWS.md`](CLIENTS_IOS_ANDROID_WINDOWS.md) 均按**实际结构**描述。
> 是否新建 `templates/<平台>/` 待确认（见 `AI_SYNC_WORKFLOW.md` §十四）。

---

## 二、迁移清单格式（逐文件 × 逐字段 × 逐端）

每个受影响的 **文件 + 字段 + 端** 组合单独一行：

| 字段 | 说明 |
|---|---|
| **文件** | 仓库相对路径 |
| **端** | iOS / Android / Windows（三端分别列，**不得合并**） |
| **JSON 路径** | 如 `route.rules[].download_detour` |
| **当前语法/字段** | 现在写的是什么 |
| **目标版本状态** | `仍有效` / `deprecated` / `removed` / `renamed` / `行为变更` |
| **官方依据** | changelog / migration 文档 / PR 链接（**必填**） |
| **迁移建议** | 改成什么 |
| **影响范围** | 只这一处 / 波及引用 / 需连带改模板 |
| **可否自动迁移** | 可 / 需人工判断 |
| **三端是否都受影响** | 是 / 仅某端 |

**示例骨架**（数值与结论以官方为准，此处仅示范格式）：

```
文件：profiles/1.14/ios-lazy.json
端：   iOS
路径：inbounds[type=tun].stack
当前： "system"
状态： deprecated（<官方依据链接>）
建议： <按官方 migration 写法>
影响： 需连带检查 PLATFORM-MATRIX.md §4 与本文件的行
自动： 需人工判断（与 Apple 客户端 "Include All Networks" 互斥）
三端： 仅 iOS 受影响
```

---

## 三、执行步骤

1. **扫描**仓库所有模板/闸门文件，识别哪些字段/结构是版本相关的。
2. **逐文件、逐字段、逐端**按 §二 格式产出迁移清单。
3. **生成 diff 或新版本草稿** —— 但**不得直接覆盖可用模板**。
4. **跑官方校验**（见 §四），失败要报告。
5. 无法确定是否兼容的语法 → 标「**待人工判断**」，保持原样，**不要强行改**。
6. 我**逐文件确认**后才落盘。
7. 迁移完成后更新版本记录文件（`singbox_version.txt`），并写 changelog。

---

## 四、校验方式

| 用途 | 命令 |
|---|---|
| 单份配置官方校验 | `sing-box check -c <file>` |
| 全仓一条命令（静态门禁 + 负向回归 + 启动级 + 逐份 check） | `bash tools/check-all.sh` |
| 加启动级验证（抓 `check` 看不见的启动期 FATAL） | `bash tools/check-all.sh --run` |
| 字段废弃/移除门禁 | `python tools/audit.py <file> --platform <p>` |
| 与用户原配置比对（改用户现成配置时必做） | `python tools/diff_config.py <原> <新>` |

> ⚠️ **`sing-box check` 通过 ≠ 配置正确**：`check` 不校验平台能力、不校验规则集顺序，
> 对「已废弃但未移除」的字段可能完全静默，也**只反序列化、不初始化**。
> 三条都过才算数：`check` + `VERSION-MATRIX` + `PLATFORM-MATRIX`。

**内核缺失时**：`audit.py` 会找 `bin/` → `PATH` → `local/.singbox-bin`，也认 `SINGBOX_BIN`。
找不到时那一项会**跳过**（现为 WARN，不再静默 PASS）—— 见 `EXPERIENCES.md`。

---

## 五、迁移的红线

- ❌ 不得自动批量替换语法
- ❌ 不得直接覆盖可用模板（先给 diff / 草稿）
- ❌ 不得对「不确定」的语法强行改
- ❌ 不得删除我未确认移除的模板
- ❌ 不得在浅克隆上做迁移判断（历史信息不全会让版本对比出错）
- ❌ 不得依据本仓旧模板反推上游行为

---

## 六、模板的既有约束（复用现有约定）

本仓模板已经有一批**机器可检**的结构性约定，迁移时不要破坏它们（详见 `MAINTAINERS.md`）：

- 三个分流组 tag 是**契约**：`🚀 Proxy` / `🤖 AI` / `🚫 AD`（emoji + 一个 ASCII 空格 + 名字）。
  改 tag 必须**端到端**改，引用面靠 `grep` 列，不能靠记忆。
- 平台差异必须**同时落三处**：profile + `PLATFORM-MATRIX.md` §4 一行 + 门禁。缺一就是静默失效。
- `profiles/` 下**只允许占位域名**（`node-0X.example.com`）；含真实节点的一律进 `local/`（已 gitignore）。
- 去广告组 `🚫 AD` 的 `outbounds` 恒为 `["block"]`，`default` 恒为 `"block"`。

改**任何**文件用 `python tools/patch-text.py spec.json`（原子写 + 唯一锚点 + 不经 shell），
不要临时写 heredoc/python 重写 —— 三条各对应一次真实事故。

---

## 七、写矩阵条目的语法（迁移的证据落地）

迁移结论要落进 `docs/version-matrix.json`，`audit.py` 靠它做门禁。`path` 写法：

| 写法 | 含义 |
|---|---|
| `route.rule_set[].download_detour` | 数组任意元素 |
| `inbounds[type=tun].stack` | 数组里 `type == "tun"` 的元素 |
| `**.tls.acme` | 任意深度下匹配 |

若字段是「某类出站」整体移除（如 `type: wireguard`）：

```json
"type_check": { "where": "outbounds", "field": "type", "equals": "wireguard" }
```

有前提条件的用 `require_present` / `require_absent` 限定：

```json
"path": "dns.rules[].strategy",
"require_present": ["action"]
```

完整字段说明与门禁维护见 [`MAINTAINERS.md`](../MAINTAINERS.md) 与 [`VERSION-MATRIX.md`](VERSION-MATRIX.md)。
