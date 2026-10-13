# AI-ENTRY — 机器入口卡片

> **本文件面向 LLM，不面向人。**
> 判据不是「好读」，是：① **不重复任何别处内容**；② 每条都能**直接执行或直接检索**。
>
> 全文只有五节：**是什么 / 一条命令 / 入口表 / 校验判据 / 边界与指针**。
> 规则的**正文一律不在这里** —— 此处只给 key 与坐标。

---

## 1. 是什么

sing-box **正式版**配置工作流仓库。

- 唯一版本真相：`singbox_version.txt`
- 只放**模板**（`profiles/<大版本>/`，占位节点）；真实节点配置**永不入库**
- 交付方式：节点 → 生成配置 → **直接发给用户**，不写盘

---

## 2. 一条命令（最常用）

```bash
python tools/mknode.py '<分享链接>' --platform <desktop|android|ios> --group <proxy|ai>
```

→ 解码 → 套骨架 → 加组 → 跑门禁 → 落 `local/<平台>.json`。退出码 `0` = 可交付。

---

## 3. 入口表

| 要做的事 | 入口命令 | 正文在哪 |
|---|---|---|
| 改配置 / 出配置 / 排障 | `python tools/mknode.py` | `AGENTS.md` |
| 改规则（升级内核 / 加门禁 / 改矩阵 / 改组 tag） | — | `MAINTAINERS.md` |
| 全量校验 | `bash tools/check-all.sh --run` | 本文件 §4 |
| 上游有新版本了 | `python tools/upgrade-check.py` | `docs/SINGBOX_UPGRADE.md` |
| **改任何文件** | `python tools/patch-text.py` | `AGENTS.md` §0（**硬规则**） |
| 换设备 / 换 Agent | — | `AGENTS.md` §8（三步清单） |

---

## 4. 校验判据

```bash
bash tools/check-all.sh          # 静态门禁 + 负向回归 + markdown + 指纹 + 规则重复 + 逐份 check
bash tools/check-all.sh --run    # 追加启动级验证（约 1 分钟）
```

**判据**：退出码 `0`。有 `[E]` 不许交付。

> ⚠️ `sing-box check` **只反序列化、不初始化** —— 通过 ≠ 能启动，必须跑过 `--run`。
> ⚠️ 内核缺失时 `check`/`run` **静默跳过**（现为 WARN）。登记方法见 `AGENTS.md` §8。

---

## 5. 边界与指针

**边界**（正文各自的归属文档）

| 线 | 归属 |
|---|---|
| 真实节点永不入库；`profiles/` 只允许占位域名 | `AGENTS.md` H11 |
| 不自动升级；需授权口令才进升级流程 | `docs/SINGBOX_UPGRADE.md` |
| 内容只走文件；含反斜杠的内容禁止 inline | `AGENTS.md` §0 |
| 不编造上游；唯一权威来源是 sing-box 官方 | `docs/AI_SYNC_WORKFLOW.md` §六 |
| 不直接推 main；必须分支 + PR | `docs/AI_SYNC_WORKFLOW.md` §九 |

**指针**（需要细节时去哪）

```
AGENTS.md                        指路牌 + H1–H15 硬规则 + 换设备三步清单
MAINTAINERS.md                   改规则：升级 / 加门禁 / 改矩阵 / 改组 tag
docs/AI_SYNC_WORKFLOW.md         总工作流：5 模块 + 图 + 指令模板 + 异常处理
docs/SINGBOX_UPGRADE.md          模块 2：升级状态机 / 功能条目 / 三栏分类
docs/TEMPLATE_MIGRATION.md       模块 3：迁移清单格式 / 校验
docs/CLIENTS_IOS_ANDROID_WINDOWS.md  模块 4：三端差异 / 流程 A 全流程
docs/EXPERIENCES.md              模块 5 + 排障（按报错分流）+ 常见误区
docs/LESSONS.md                  事故台账【查时读，别整读】
docs/DECISIONS.md                决策记录【查时读】
docs/PROTOCOL-MAPPING.md         分享链接 → outbound 字段映射
docs/PLATFORM-MATRIX.md          三端能力差异表
docs/VERSION-MATRIX.md           字段废弃/移除总表（自动生成，勿手改）
docs/version-matrix.json         同上，机器可读（门禁依据）
docs/PROMPT-DEVIATIONS.md        任务要求 vs 实际的偏离对账（含未覆盖项）
profiles/<大版本>/               三端可运行模板（占位节点）
templates/                       分流组骨架 + 三端索引入口
tools/                           各工具跑 --help 自带说明
local/                           【不提交】真实节点与私有状态
```

---

## 6. 声明（**本文件独有的内容，别处没有**）

- 仓库内所有节点均为**占位值**，不含真实服务器信息。
- 本仓库只做配置生成与校验，**不保证**任何节点的连通性或速度。
- 配置通过 `sing-box check` 只代表**语法与字段合法**，不代表实际能联网。

---

## 7. 维护本文件的规矩

- **不重复别处内容。** 同一件事只在一处完整陈述（单一来源），此处只放 key + 坐标。
  要加规则，加到它的**归属文档**，这里最多加一行指针。
- **每条都要可执行或可检索。** 散文式解释不写在这里。
- 改本文件走 `patch-text.py`（见 `AGENTS.md` §0）。
- 门禁 `rules_dupe` 会检查本文件与其它文档的规则重复。
