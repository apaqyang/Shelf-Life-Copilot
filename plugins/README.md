# plugins/ — 企业版插件挂载点（Open Core 边界）

开源核心**不包含**任何企业版插件。付费客户拿到的私有插件包（来自独立私有仓库 /
wheel）放在这里：

```
plugins/
└── enterprise/
    ├── wecom_realtime/   # 企微回调 AES 加解密 + 签名校验（替换 PlaintextCrypto）
    │   └── __init__.py   # 暴露 register(registry)
    ├── erp_sap/          # SAP 数据源（实现 BatchRepository）
    │   └── __init__.py
    └── erp_yonyou/ ...
```

## 插件契约

每个插件是 `plugins/enterprise/<name>/` 下的一个 Python 包，`__init__.py` 暴露：

```python
def register(registry):
    """启动时由 src.plugins.load_plugins 调用。

    registry.app      — 运行中的 FastAPI 实例（挂路由 / 写 app.state）
    registry.settings — 运行时 Settings
    """
    # 例 1：替换数据源（ERP 插件）
    from src.repository import set_repository
    set_repository(MyErpRepository(registry.settings))

    # 例 2：装上真实 AES 加解密（企微实时回调插件）
    from src.webhook import set_webhook_crypto
    set_webhook_crypto(MyAesCrypto(corp_secret=...))

    # 例 3：挂企业版独有路由
    registry.app.include_router(my_admin_router)
```

`plugins/enterprise/` 不存在或为空时，服务以**纯开源模式**运行。

> `plugins/enterprise/` 已在 `.gitignore` 中——企业版代码绝不进开源仓库。
