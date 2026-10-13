# templates/ — 模板目录索引

> ⚠️ **先读这段，否则会走错门。**

本仓库的**可运行配置模板**放在 **`profiles/<大版本>/`**，不是 `templates/`。

| 你要找的 | 在哪 | 说明 |
|---|---|---|
| **可运行配置模板**（三端） | [`../profiles/<大版本>/`](../profiles/) | `desktop-lazy.json` / `android-lazy.json` / `ios-lazy.json`（**占位节点**） |
| 分流组骨架 | [`groups.json`](groups.json) | 三个固定分流组的结构 |
| 三端模板的**差异与交付说明** | [`../docs/CLIENTS_IOS_ANDROID_WINDOWS.md`](../docs/CLIENTS_IOS_ANDROID_WINDOWS.md) | 三端能力差异、模板位置、交付格式 |
| 节点书写示例 | [`../nodes/nodes.example.json`](../nodes/nodes.example.json) | 分享链接 ↔ JSON 对照 |

## 三端目录（`ios/` `android/` `windows/`）

这三个目录是**三端各自的占位与索引入口**。它们**不是**配置模板的存放处 ——
可运行模板统一在 `profiles/<大版本>/`，按**内核大版本**分目录、按**平台**分文件。

每个目录下有一份 `README.md`，说明该端：

- 对应哪份模板文件
- 该端的已知差异从哪查（**以 sing-box 上游官方文档为准**）
- 交付给用户时的注意事项

| 目录 | 对应端 | 对应模板 |
|---|---|---|
| [`ios/`](ios/) | iOS / iPadOS | `profiles/<大版本>/ios-lazy.json` |
| [`android/`](android/) | Android | `profiles/<大版本>/android-lazy.json` |
| [`windows/`](windows/) | Windows / Linux 桌面版 | `profiles/<大版本>/desktop-lazy.json` |

## 为什么保留两套组织方式？

- `profiles/<大版本>/` —— 按**内核版本**组织。1.14 的配置在 1.15 上可能直接 `FATAL`，
  按大版本分目录后**升级 = 新开一个目录**，旧配置原地保留、随时可回退。
- `templates/<平台>/` —— 按**端**组织，是给人找东西用的**索引层**，不含可运行配置。

> 两处若出现不一致，**以 `profiles/` 为唯一实现**；`templates/<平台>/README.md` 只做指路。

## 不在这里放什么

- ❌ **真实节点**：`profiles/` 下只允许占位域名；含真实节点的配置放仓库外的 `local/`（已 gitignore）。
- ❌ **可运行配置的副本**：不要在 `templates/<平台>/` 里再存一份配置 —— 会造成"改哪份才对"的混乱。
