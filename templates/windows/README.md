# templates/windows/ — Windows / Linux 桌面版

> ⚠️ **这里不是配置模板的存放处。** 本端可运行模板在
> [`../../profiles/<大版本>/desktop-lazy.json`](../../profiles/)。
>
> 本目录是**该端的索引入口**，不放可运行配置，避免出现"改哪份才对"的混乱。

## 对应关系

| 项 | 值 |
|---|---|
| **可运行模板** | [`profiles/<大版本>/desktop-lazy.json`](../../profiles/) |
| **目标客户端** | sing-box 桌面内核（Windows / Linux） |
| **大版本目录** | 与 `singbox_version.txt` 锁定的主次版本号对应，如 `1.14/` |

> 📌 **注意命名**：本仓用 `desktop`（平台标识）而不是 `windows`。
> 因为同一份模板同时服务 Windows 与 Linux 桌面版。
> 目录名 `windows/` 是任务约定的三端命名，**平台标识仍是 `desktop`** ——
> 传给工具时用 `--platform desktop`。

## 交付时怎么走

按 [`../../docs/CLIENTS_IOS_ANDROID_WINDOWS.md`](../../docs/CLIENTS_IOS_ANDROID_WINDOWS.md) 的流程与格式：

```bash
python tools/mknode.py '<分享链接>' --platform desktop --group <proxy|ai>
```

产物落 `local/desktop.json`（含真实节点，**已 gitignore，永不提交**）→ **直接发给我**。

## 本端的已知差异从哪查

**以 sing-box 上游官方文档为准**，不要凭经验猜：

1. [`../../docs/PLATFORM-MATRIX.md`](../../docs/PLATFORM-MATRIX.md) —— 三端能力差异对照表（本仓维护）
2. 上游官方 `docs/clients/desktop/` —— 该端的权威源
3. [`../../docs/EXPERIENCES.md`](../../docs/EXPERIENCES.md) —— 排障与常见误区

> ⚠️ `PLATFORM-MATRIX.md` 的 §4（具体字段差异）有门禁逐格对账；
> 但 §1/§1a/§2/§2a（**能力清单**）**无法机器核对**，只能人工按「来源」一栏复核 —— 别以为它也上了锁。

## 该端要注意的

- 桌面端**支持的能力通常比移动端多**（例如移动端不支持的某些字段）——
  但**不要**由桌面端能用来推断移动端也能用；反过来同样不行。
- ⚠️ **本机（Windows）挂着 OpenClash 网关，DNS 会被劫持** ——
  在本机跑出来的「能上网 / 不能上网」结论**一律作废**。
  `sing-box check` 与 `audit.py --run` 只验「能不能启动」，**不准验「能不能上网」**。
- 平台相关的字段改动**必须同时落三处**：profile + `PLATFORM-MATRIX.md` §4 一行 + 门禁。
- 交付时**不得声称「已实测联网可用」** —— 除非真在桌面端跑过。
