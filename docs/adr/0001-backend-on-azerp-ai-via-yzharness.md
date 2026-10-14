# 后端长在 azerp，AI 能力走 yzharness-ai 中台

CAD 插件需要服务端支撑（图库维护、按图搜索、账号鉴权）。备选：新起一个 JeecgBoot 实例、找更轻量的开源后台、挂在 guoji（云筑国际 ERP）上、直接挂在 azerp 上。决定：**图库与插件 API 全部长在 azerp（`D:\phpstudy_pro\WWW\azerp`，`newerp` 下新模块），复用 `/sys/login` JWT 与按门店的数据权限；视觉模型调用经 yzharness-ai 中台（8081）代理，API Key 不进插件。**

理由：门店人员已有 azerp 账号（下单在用），数据权限按门店隔离现成；guoji 与 azerp 账号体系完全独立，打通成本远超收益；guoji 的 AI 优势实际来自两家共享的 yzharness-ai 中台，azerp 调用平权。否掉新起实例：多一套部署与账号体系，无对应收益。

## Considered Options

- 新起 JeecgBoot / 更轻量开源后台：被否，多一套账号与部署
- 挂 guoji：被否，账号独立、跨系统鉴权不值当；AI 能力经中台共享后无剩余优势
- azerp + AI 直连模型 API：被否，Key 管理分散；中台已统一管理供应商与计费
