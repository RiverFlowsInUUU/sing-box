# archive/ 历史文件

本目录存放**不再维护**的旧配置，仅供对照查阅。请不要直接使用这里的文件。

> ⚠️ **本目录不被门禁扫描。** `tools/audit.py` 的目标是 `profiles/**/*.json` 与
> `templates/groups.json`；这里的东西是历史快照，字段可能已经废弃甚至移除。
> 想拿来做参考，先按 `docs/version-matrix.json` 自行核对字段生命周期。

## singbox-ios-1.14.2.json

本仓库最早的版本，单文件 iOS 分流配置。已被 `profiles/1.14/ios-lazy.json` 取代，原因：

| 问题 | 说明 |
|---|---|
| `inbounds[0].strict_route: true` | **iOS 客户端未实现该选项**（见 `docs/PLATFORM-MATRIX.md`）。写上去不会报错，但行为未定义。 |
| 没有 AD 分流组 | 缺少广告拦截分组，只有「节点-国外 / 节点-AI」。本仓库统一使用 Proxy / AI / AD 三组。 |
| 无 `http_clients` 显式配置 | 依赖隐式默认 HTTP client，该写法在 1.14.0 已废弃、1.16.0 移除。 |
| 规则集走 `cdn.jsdelivr.net` | 未固定 CDN 镜像；本仓库统一使用 `testingcf.jsdelivr.net`。 |

替代文件：`profiles/1.14/ios-lazy.json`
