# AGENTS.md — 指路牌

> 本文件是**指路牌 + 硬规则入口**，不承载详细技术内容。
> 每条硬规则只有一句话，**详细解释一律在 `docs/` 里**。

---

## 0. 动手改文件之前，先读这一条（**不是文档，是操作手册**）

### 0.1 硬规则：**内容只走文件，不走命令行**

改文件用 `python tools/patch-text.py`。**含反斜杠、换行、引号的内容，
一律写进文件再用 `find_file` / `replace_file`，禁止塞进 `--spec-inline` / heredoc。**

```bash
# ❌ 会翻车：内容经过命令行
python tools/patch-text.py --spec-inline '[{"file":"x.py","find":"a\nb","replace":"c"}]'

# ✅ 正确：内容写在文件里，命令行只传文件名
#   1) 把「要找的原文」写到 local/_pt/find.txt
#   2) 把「要换成的文」写到 local/_pt/repl.txt
python tools/patch-text.py --spec-inline \
  '[{"file":"x.py","find_file":"local/_pt/find.txt","replace_file":"local/_pt/repl.txt"}]'
```

### 0.2 为什么 —— 实测数据（本机量出来的，不是推的）

命令行参数里的反斜杠，穿过调用链后**折半（向上取整）**：

| 发出（个） | 收到（个） |
|---|---|
| 1 | 1 |
| 2 | **1** ← 丢了一个 |
| 3 | 2 |
| 4 | 2 |
| 5 | 3 |
| 6 | 3 |

**⇒ 你用两个反斜杠想写出「一个字面反斜杠」，到手只有一个 —— 内容静默变了。**

后果：`\n` 变真换行、`\x00` 变真 NUL 字节、markdown 表格被劈断，
**而你从命令输出里看不出来**。我在这个仓库里为此回滚过 7 次。

> ⚠️ **这一层配不了环境。** 实测三层：Bash/shell **正常**（`<<'EOF'` 原样透传）、
> Python **正常**（`\n` 转义是它该有的行为）—— 折半发生在**调用链**那一层，
> 配 `chcp` / `$OutputEncoding` / `PYTHONIOENCODING` / `core.autocrlf` **全都治不到它**。
> ⇒ 换设备后先跑 `python tools/check-shell-escapes.py` **量一下**，别猜。

### 0.3 工具层已加拦截

`patch-text.py` 现在会**拒绝执行**含反斜杠的 `--spec-inline`（退出码 2），
并打印正确的两步写法。**不是建议，是拒绝。** 少绕路，工具会把你拽回正轨。

### 0.4 另外三个老坑（`tools/patch-text.py` 文件头有完整说明，比本文档更该先读）

| 坑 | 后果 |
|---|---|
| `open(p,'w')` 先截断再算内容 | 中途异常文件只剩半截（真实事故：`audit.py` 曾从 1919 行被截成 828 行） |
| 拿「某短 token 第一次出现」当锚点 | 命中的是文件里第一个 `try:`，替换点完全错位 |
| **`replace_file` 落盘后不核对** | 报 ✅ 但内容丢了 —— 实测：`if args.spec_inline:` 两行没进去，**语法仍合法、逻辑全错** |

**绕过它会留下指纹，会被抓到**（`edit_method_fingerprint` 门禁）：
BOM / NUL / 行尾混用 / 整文件 CRLF。仓库已由 `.gitattributes` 统一 LF ——
本门禁上线当天就抓到了 `tools/audit.py` 是仓内唯一的 CRLF 文件，
而那正是我此前裸写它留下的。

---
## 1. 项目一句话定位

**sing-box 正式版配置工作流仓库** —— 只做**工作流定义、模板维护、经验总结**，
按客户端（iOS / Android / Windows）维护配置模板；实际可运行配置由我提供节点、AI 生成后**直接发给我**，不写入仓库。

---

## 2. 必读顺序

| # | 读什么 | 为什么 |
|---|---|---|
| 1 | **本文件** | 硬规则与文档索引 |
| 2 | [`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md) | 总工作流 SOP（5 个模块 + Mermaid 图） |
| 3 | [`docs/EXPERIENCES.md`](docs/EXPERIENCES.md) | 先看已知的坑（含浅克隆问题） |
| 4 | 按任务类型选读 | 改配置 → 见下方 §4 的对应文档；改规则 → [`MAINTAINERS.md`](MAINTAINERS.md) |

> **不要**把 `docs/LESSONS.md`（事故台账，2000+ 行）当开工读物整读 —— 它是**查时读**。
> 出错了再按报错关键词 `grep`。

---

## 3. 硬规则清单

### 3.1 安全与权限（最高优先级）

| # | 规则 | 详情 |
|---|---|---|
| H1 | **换设备 / 换 AI Agent / 换运行环境后，第一步必须完整克隆。严禁浅克隆。** | [§七](docs/AI_SYNC_WORKFLOW.md#七完整克隆规则最高优先级) · [E1](docs/EXPERIENCES.md) |
| H2 | **只在我手动触发后行动。** 不允许自动定时同步。 | [§三](docs/AI_SYNC_WORKFLOW.md#三触发条件与准入规则) |
| H3 | **只跟 sing-box 上游 latest stable**，禁 beta / alpha / rc / nightly / pre-release / 测试版 / 预览版。 | [§三](docs/AI_SYNC_WORKFLOW.md#三触发条件与准入规则) |
| H4 | **模块 2（上游升级）不自动升级** —— 可提醒、可询问、需我授权口令。 | [SINGBOX_UPGRADE](docs/SINGBOX_UPGRADE.md) |
| H5 | **新功能逐点请示**，不默认开启、不批量开启。 | [§五](docs/SINGBOX_UPGRADE.md#五功能条目的结构化格式) |
| H6 | **模板语法迁移逐文件、逐字段、逐端确认**，不得自动批量替换。 | [TEMPLATE_MIGRATION](docs/TEMPLATE_MIGRATION.md) |
| H7 | **不得编造上游内容。** 唯一权威来源是上游官方文档；找不到依据就标「未能确认」。 | [§六](docs/AI_SYNC_WORKFLOW.md#六唯一权威来源原则) |
| H8 | **不得直接改 `main`/`master`**，必须分支 + PR；不得自动合并 PR。 | [§九](docs/AI_SYNC_WORKFLOW.md#九分支提交pr-规范) |
| H9 | **不得写入节点或可运行配置** —— 实际配置只发给我。 | [CLIENTS](docs/CLIENTS_IOS_ANDROID_WINDOWS.md) |
| H10 | **不得删除我未确认移除的内容/模板**；不得重建仓库结构。 | [§十二](docs/AI_SYNC_WORKFLOW.md#十二禁止事项与红线) |

### 3.2 本仓既有的技术铁律（改配置时用得上）

> 走 `tools/mknode.py` 快车道时，下列大部分已**编译进工具与门禁**，不用背。
> 真正需要主动记住的只有 **H9** 与 **H11**。

| # | 规则 |
|---|---|
| H11 | **任何时候、任何文件都不放真实节点。** `profiles/` 只允许占位域名；真实凭据只进 `local/`（已 gitignore）。范围是**整个被跟踪仓库**（`docs/` 散文同样公开）。 |
| H12 | **改配置/改流程先拉仓库、先看 diff**，**先给人看、得到同意、才 commit/push**；不得直接覆盖已有文件。 |
| H13 | 三个分流组 tag 是**契约**：`🚀 Proxy` / `🤖 AI` / `🚫 AD`（emoji + 一个 ASCII 空格 + 名字），改 tag 必须端到端改。 |
| H14 | **`check` 通过 ≠ 配置正确**：不校验平台能力、不校验规则集顺序、只反序列化不初始化。 |
| H15 | 依据优先级：**官方文档 > 官方源码 > 本仓文档**；冲突时以官方为准并当场修本仓。 |

完整铁律表与「谁在守」见 [`MAINTAINERS.md`](MAINTAINERS.md)。

---

## 4. 文档索引

| 文档 | 一句话用途 |
|---|---|
| [`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md) | **总工作流**：5 个模块、角色、触发、指令模板、异常处理 |
| [`docs/SINGBOX_UPGRADE.md`](docs/SINGBOX_UPGRADE.md) | 模块 2 详版：升级状态机、功能条目格式、升级计划模板 |
| [`docs/TEMPLATE_MIGRATION.md`](docs/TEMPLATE_MIGRATION.md) | 模块 3 详版：迁移清单格式、校验方式、矩阵条目写法 |
| [`docs/CLIENTS_IOS_ANDROID_WINDOWS.md`](docs/CLIENTS_IOS_ANDROID_WINDOWS.md) | 模块 4 详版：三端差异、模板位置、交付格式 |
| [`docs/EXPERIENCES.md`](docs/EXPERIENCES.md) | 模块 5：经验总结（区分官方确认 / 经验推测 / 本仓约定） |
| [`MAINTAINERS.md`](MAINTAINERS.md) | **改规则**的操作手册：升级流程、加门禁、改矩阵、改组 tag |
| [`docs/EXPERIENCES.md`](docs/EXPERIENCES.md) | 排障（按报错分流）、三层问题模型、常见误区、经验总结 |
| [`docs/PROTOCOL-MAPPING.md`](docs/PROTOCOL-MAPPING.md) | 分享链接 → outbound 字段映射 |
| [`docs/PLATFORM-MATRIX.md`](docs/PLATFORM-MATRIX.md) | 三端能力差异表 |
| [`docs/VERSION-MATRIX.md`](docs/VERSION-MATRIX.md) | 字段废弃/移除总表（自动生成，勿手改） |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 决策记录：新功能为何启用/不启用 |
| [`docs/LESSONS.md`](docs/LESSONS.md) | 事故台账（**查时读**，别整读） |
| [`docs/upstream-*.md`](docs/) | 上游官方文档快照（testing 分支，**早于正式版**，勿当当前版本说明） |
| [`README.md`](README.md) | 机器入口卡片（面向 LLM，不面向人） |

---

## 5. 标准工作流一句话概览

**我手动触发 → Agent 只读比对 → 报告 → 我逐点拍板 → 落文件 → 分支 → PR → 我合并。**

五个模块：**版本同步 / 上游升级（需授权） / 模板迁移（需授权） / 三端交付 / 经验总结**。
流程图与完整步骤见 [`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md#二工作流总览)。

**改配置的快车道**（只需这一条命令）：

```bash
python tools/mknode.py '<分享链接>' --platform <desktop|android|ios> --group <proxy|ai>
```

---

## 6. 禁止事项

- ❌ 浅克隆后继续操作
- ❌ 未经我授权：升级 / 启用新功能 / 迁移语法 / 更新版本记录 / 创建 PR / 合并 PR
- ❌ 直接推 `main`/`master`
- ❌ 编造上游功能、版本号、配置项、语法、平台支持
- ❌ 依据本仓旧模板反推上游行为
- ❌ 把真实节点、可运行配置、secrets 写入仓库
- ❌ 删除我未确认移除的现有内容或模板
- ❌ 运行会改变上游或生产配置的命令

完整清单见 [`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md#十二禁止事项与红线) §十二。

---

## 7. 回复格式要求

**报告类**（检查、比对、请示）：

1. 结论先行（一句话）
2. 依据（**附官方来源链接**；无来源标「未能确认」）
3. 分端列出（iOS / Android / Windows 各自结论）
4. 待我确认的事项（**逐条、可勾选**）
5. 下一步我需要说什么

**配置交付类**：按 [`CLIENTS_IOS_ANDROID_WINDOWS.md`](docs/CLIENTS_IOS_ANDROID_WINDOWS.md) §五 的固定格式 ——
适用端 / 基于版本 / 模板来源 / 变更点 / 完整可粘贴配置 / 校验命令与结果 / 风险与待确认项。

**不得**声称「已实测联网可用」，除非真在目标端跑过。

---

## 8. 完整克隆要求（**最高优先级**）

**每次换设备、换 AI Agent、换运行环境后，在修改本仓库前必须完整克隆。**

```bash
git rev-parse --is-shallow-repository   # 必须返回 false
```

**完整规则、禁止的克隆参数、无法克隆时的处置** →
[`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md#七完整克隆规则最高优先级) §七 ·
实例 [`E1`](docs/EXPERIENCES.md)。

> **单一来源原则**：这一节此前把「四条验证命令 + 浅克隆处置 + 指向」在本文件、
> `AI_SYNC_WORKFLOW.md` §七、`EXPERIENCES.md` E1 **各写了一遍**。
> 现收敛到 §七（详版），本文件只留一句判据 + 指针。
>
> ⚠️ **有意保留的两处重复**（改这里之前先读）：
> ① 那句「每次换设备…必须完整克隆」—— 这是**规则名**，两处都要有，
>    否则只读 `AI_SYNC_WORKFLOW.md` 的人看不到它在入口的地位；
> ② `git rev-parse --is-shallow-repository` 这一条命令 —— 它是**判据**，
>    入口必须能直接执行、不必翻页。
> **除这两样之外，本节不再新增任何正文。**

### 换设备三步清单（只有顺序，正文在别处）

| # | 做什么 | 正文 |
|---|---|---|
| 1 | **完整克隆**（禁浅克隆） | `docs/AI_SYNC_WORKFLOW.md` §七 |
| 2 | **手敲一次转义层自检** | 本文件 §0.2（必须手敲，不能进 `check-all.sh`） |
| 3 | **登记内核路径** | 见下方 |

**第 3 步：登记内核路径**

```bash
mkdir -p local
echo '/绝对路径/to/sing-box' > local/.singbox-bin    # local/ 已 gitignore，不进仓库
```

解析顺序：`SINGBOX_BIN` → `bin/sing-box[.exe]` → `PATH` → `local/.singbox-bin`。

**登记完自己验一下**（本仓曾因漏报「跳过」而发过假绿灯）：

```bash
python tools/audit.py 2>&1 | grep -i "matrix_probe_skipped"
```

**没有输出** = 内核已就位。有输出 = 内核没找到，门禁不完整，**别拿这时的「全绿」当结论**。

> ⚠️ `local/` **不入库**，所以这一步**每次换设备都要重做** —— 它不会跟着克隆过来。

## 9. 关键事项确认表

| 项 | 状态 |
|---|---|
| 上游项目 | ✅ sing-box 官方 — `https://github.com/SagerNet/sing-box` · `https://sing-box.sagernet.org/` |
| 模板目录 | ✅ 可运行模板在 `profiles/<大版本>/<平台>-lazy.json`；[`templates/{ios,android,windows}/`](templates/) 为索引入口 |
| 版本记录文件 | ✅ `singbox_version.txt` |

完整清单 → [`docs/AI_SYNC_WORKFLOW.md`](docs/AI_SYNC_WORKFLOW.md#十四待补充信息清单) §十四。
