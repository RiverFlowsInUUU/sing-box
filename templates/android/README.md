# templates/android/ — Android

> ⚠️ **这里不是配置模板的存放处。** 本端可运行模板在
> [`../../profiles/<大版本>/android-lazy.json`](../../profiles/)。
>
> 本目录是**该端的索引入口**，不放可运行配置，避免出现"改哪份才对"的混乱。

## 对应关系

| 项 | 值 |
|---|---|
| **可运行模板** | [`profiles/<大版本>/android-lazy.json`](../../profiles/) |
| **目标客户端** | sing-box for Android |
| **大版本目录** | 与 `singbox_version.txt` 锁定的主次版本号对应，如 `1.14/` |

## 交付时怎么走

按 [`../../docs/CLIENTS_IOS_ANDROID_WINDOWS.md`](../../docs/CLIENTS_IOS_ANDROID_WINDOWS.md) 的流程与格式：

```bash
python tools/mknode.py '<分享链接>' --platform android --group <proxy|ai>
```

产物落 `local/android.json`（含真实节点，**已 gitignore，永不提交**）→ **直接发给我**。

## 本端的已知差异从哪查

**以 sing-box 上游官方文档为准**，不要凭经验猜：

1. [`../../docs/PLATFORM-MATRIX.md`](../../docs/PLATFORM-MATRIX.md) —— 三端能力差异对照表（本仓维护）
2. 上游官方 `docs/clients/android/` —— 该端的权威源
3. [`../../docs/EXPERIENCES.md`](../../docs/EXPERIENCES.md) —— 排障与常见误区

> ⚠️ `PLATFORM-MATRIX.md` 的 §4（具体字段差异）有门禁逐格对账；
> 但 §1/§1a/§2/§2a（**能力清单**）**无法机器核对**，只能人工按「来源」一栏复核 —— 别以为它也上了锁。

## 该端要注意的

- **`route.auto_detect_interface: true` 在 Android 上是唯一可行的防回环手段** ——
  官方另两个办法（`route.default_interface` / `outbound.bind_interface`）都需要真实网卡名，
  而图形客户端走的是 `VpnService.protect(fd)`，不是桌面那套网卡绑定。
  缺了它表现为「能启动、不报错，但完全没网」（节点全无延迟、只有上传没下载、内存飙 1GB）。
  详见 [`../../docs/EXPERIENCES.md`](../../docs/EXPERIENCES.md) 的「三层问题模型」。
- 平台相关的字段改动**必须同时落三处**：profile + `PLATFORM-MATRIX.md` §4 一行 + 门禁。
- 交付时**不得声称「已实测联网可用」** —— 除非真在 Android 上跑过。
