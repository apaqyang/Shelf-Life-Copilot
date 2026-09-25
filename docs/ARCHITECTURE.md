# Architecture — Shelf-Life Copilot

> 阶段：v0.1（Mock Demo）
> 配套文档：[TECH_SPEC.md](TECH_SPEC.md) · [ROADMAP.md](ROADMAP.md) · [DEVELOPMENT_TASKS.md](DEVELOPMENT_TASKS.md)
> 更新日期：2026-09-24

本文档讲清楚**代码长什么样**——分层、依赖方向、关键模块的边界。
面向：新加入的工程师、客户 IT 评估、未来回头看 trade-off 的自己。

---

## 1. 一图看懂

```
┌────────────────────────────────────────────────────────────┐
│                       Entry Points                          │
│   ┌────────────────┐         ┌────────────────────────┐   │
│   │  src/cli.py    │         │  src/main.py (FastAPI) │   │
│   │  one-shot scan │         │  webhook + command API │   │
│   └────────┬───────┘         └────────┬───────────────┘   │
│            │                          │                    │
└────────────┼──────────────────────────┼────────────────────┘
             │                          │
             ▼                          ▼
┌────────────────────────────────────────────────────────────┐
│                  Orchestration Layer                        │
│   ┌──────────────────────┐    ┌──────────────────────┐    │
│   │  ScanRunner          │    │  DailyScheduler      │    │
│   │  (per-cycle编排)     │◄───┤  (APScheduler 包装)  │    │
│   └─────────┬────────────┘    └──────────────────────┘    │
└─────────────┼──────────────────────────────────────────────┘
              │
       ┌──────┼──────┬──────────────────┐
       ▼      ▼      ▼                  ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ Business     │ │ Business     │ │   I/O Layer          │
│ Logic        │ │ Logic        │ │                      │
│              │ │              │ │  ┌────────────────┐  │
│ alerts/      │ │ suggestion/  │ │  │ repository/    │  │
│ ──────────── │ │ ──────────── │ │  │  JSON loaders  │  │
│ scan_batch   │ │ Suggestion-  │ │  └────────┬───────┘  │
│ classify     │ │ Engine       │ │           │          │
│ days_left    │ │ Prompt/Tool  │ │           ▼          │
│ (pure funcs) │ │ (async LLM)  │ │  ┌────────────────┐  │
│              │ │              │ │  │ data/  (JSON)  │  │
└──────┬───────┘ └──────┬───────┘ │  │  batches/      │  │
       │                │         │  │  config/       │  │
       ▼                ▼         │  └────────────────┘  │
       └────────┬───────┘         └──────────────────────┘
                ▼
   ┌─────────────────────────────┐         ┌─────────────────────┐
   │      Data Models (Pydantic) │         │  External Services  │
   │                              │         │                     │
   │  Batch / Alert / Severity   │◄────────┤   Anthropic API     │
   │  Suggestion / ActionType    │  (via   │   (Claude tool_use) │
   │  AlertThresholds            │ AsyncAn-│                     │
   │  CustomerConfig             │ thropic)│   (Future) 企业微信 │
   │  ScanResult / ScanError     │         │                     │
   │   ── all frozen=True ──     │         └─────────────────────┘
   └─────────────────────────────┘
```

---

## 2. 分层与依赖方向

依赖严格单向（**箭头从依赖者指向被依赖者**）：

```
entry points (cli, main)
       │
       ▼
orchestration (scheduler)
       │
       ▼
business logic (alerts, suggestion)
       │           │
       │           ▼
       │    external SDK (anthropic)
       ▼
i/o (repository) ──► filesystem (data/)
       │
       ▼
data models (models/) ──► (no dependencies, leaf layer)
```

**关键不变量**：`models/` **不依赖任何业务层**。这是循环导入的"防火墙"——`AlertThresholds` 一度放在 `alerts/monitor.py` 导致 `models.customer ↔ alerts.monitor` 循环，已重构到 `models/thresholds.py` 修复。

---

## 3. 模块目录与职责

```
src/
├── cli.py                      # 入口 ① 一次性扫描的 CLI
├── main.py                     # 入口 ② FastAPI app（health/webhook/command API）
│
├── api/                        # Bearer 鉴权的手动扫描 / 工单完成命令
│   ├── router.py               # 幂等命令、租户查询与优化计划 API
│   └── schemas.py              # API request/response contracts
│
├── models/                     # 数据契约层（叶子层，无业务依赖）
│   ├── action.py               # ActionType (StrEnum)
│   ├── alert.py                # Alert
│   ├── batch.py                # Batch + Severity
│   ├── customer.py             # CustomerConfig（含不变量校验）
│   ├── suggestion.py           # Suggestion
│   ├── thresholds.py           # AlertThresholds
│   └── work_order.py           # WorkOrder + 状态转移不变量
│
├── alerts/                     # 业务层 · 监测引擎（纯函数，无 IO）
│   └── monitor.py              # calculate_days_left / classify_severity / scan_batch
│
├── suggestion/                 # 业务层 · LLM 建议（async，provider-agnostic）
│   ├── engine.py               # SuggestionEngine（依赖注入 LLMProvider）
│   ├── providers.py            # LLMProvider Protocol + Anthropic/Moonshot 实现
│   ├── prompt.py               # SYSTEM_PROMPT + build_user_prompt（含越界规则）
│   └── schema.py               # build_suggestion_tool（全集 enum + enabled 首选）
│
├── repository/                 # I/O 层 · JSON 加载
│   └── loader.py               # load_customer_config / load_batches
│
├── persistence/                # 持久化 port + SQLite adapter
│   ├── protocols.py            # Decision/Suggestion/WorkOrder Repository
│   ├── migrations.py           # 带版本、事务化 schema 迁移
│   ├── sqlite.py               # WAL / busy timeout / 连接生命周期
│   └── *_store.py              # SQLite 具体实现
│
├── runtime/                    # 应用装配、配置与横切安全控制
│   ├── lifespan.py             # 插件加载、存储与 runner 生命周期
│   └── security.py             # Bearer auth / body limit / rate limit
│
├── webhook/                    # 企微回调校验、持久化去重与决策路由
│
├── scheduler/                  # 编排层
│   ├── runner.py               # ScanRunner + ScanResult + ScanError
│   └── scheduler.py            # DailyScheduler（APScheduler 包装）
│
├── task_queue.py              # 持久队列 + 可独立运行的扫描 worker
├── optimization.py            # 跨批次模型、质量门禁与确定性基线
├── admin.py                   # 仅消费稳定 API 的轻量管理界面
│
├── wecom/                      # 渲染层 · 4 套卡片 + 推送 client（Protocol）
│   ├── cards.py                # render_alert / render_work_order /
│   │                           #   render_receipt / render_out_of_scope
│   │                           #   + render_card_for_alert (dispatcher)
│   └── client.py               # WecomClient Protocol + DryRunWecomClient
│
└── reports/                    # 月度 PDF 报告管道（数据 → 渲染分离）
    ├── aggregator.py           # list[Decision] → MonthlyReportData (纯函数)
    └── renderer.py             # MonthlyReportData → PDF bytes (reportlab)
```

**测试镜像**：`tests/` 与 `src/` 1:1 对应。

---

## 4. 一次完整扫描的流程（sequence）

```
 CLI / Cron                ScanRunner             SuggestionEngine            Claude API
   │                          │                        │                         │
   │ run_for_customer("A")    │                        │                         │
   ├─────────────────────────►│                        │                         │
   │                          │                        │                         │
   │                          │ load_customer_config   │                         │
   │                          ├─► repository.loader    │                         │
   │                          │   data/config/A.json   │                         │
   │                          │                        │                         │
   │                          │ load_batches           │                         │
   │                          ├─► repository.loader    │                         │
   │                          │   data/batches/A.json  │                         │
   │                          │                        │                         │
   │                          │ for batch in batches:  │                         │
   │                          │   scan_batch ──► Alert │                         │
   │                          │                        │                         │
   │                          │   if alert:            │                         │
   │                          │     suggest(batch,     │                         │
   │                          │       alert, customer) │                         │
   │                          ├───────────────────────►│                         │
   │                          │                        │ build prompt + tool     │
   │                          │                        │ messages.create(...)    │
   │                          │                        ├────────────────────────►│
   │                          │                        │ tool_use response       │
   │                          │                        │◄────────────────────────┤
   │                          │                        │ validate via Pydantic   │
   │                          │     Suggestion         │                         │
   │                          │◄───────────────────────┤                         │
   │                          │                        │                         │
   │                          │ collect alerts + sugg. │                         │
   │                          │ catch per-batch errors │                         │
   │                          │                        │                         │
   │     ScanResult           │                        │                         │
   │◄─────────────────────────┤                        │                         │
   │                          │                        │                         │
```

---

## 5. 关键设计决策

### 5.1 LLM 输出靠 tool_use / function calling 强制 JSON
- 比"prompt 里请求输出 JSON 然后正则提取"可靠 10×
- `action` 字段的 `enum` **覆盖 ActionType 全集**；description 把 `enabled_actions` 列为首选
  - 这是改方案越界兜底的实现：LLM 默认走 enabled，但用户反馈明确要求 disabled 时可越界
  - `is_standard` 由 Python 端 `action in enabled_actions` 判断，越界则路由到红标卡片
- 见 `src/suggestion/schema.py` `build_suggestion_tool` + `src/suggestion/prompt.py` SYSTEM_PROMPT

### 5.1.1 LLM Provider 抽象（多供应商支持）
- `src/suggestion/providers.py::LLMProvider` Protocol 定义 `call_with_tool(system, user, tool_schema) → dict`
- 两个实现：
  - `AnthropicProvider`：Claude tool_use（默认）
  - `MoonshotProvider`：Moonshot / KIMI via OpenAI 协议 function calling（国内可访问）
- CLI 通过 `--provider {anthropic,moonshot}` 切换；engine 完全 vendor-agnostic
- 质量验证脚本 `tools/validate_llm.py` 同时支持两个 provider

### 5.2 LLM 调用被依赖注入隔离
- `SuggestionEngine.__init__(client: AsyncAnthropic)` 接受 client 实例
- 测试用 `MagicMock(spec=AsyncAnthropic)` 替换 → 100% 测试覆盖，零真实 HTTP 调用
- 生产代码：CLI/scheduler 入口构造真实 `AsyncAnthropic(api_key=...)` 注入

### 5.3 per-batch 错误隔离
- ScanRunner 的扫描循环里，单批次 LLM 失败被 `try/except Exception` 包住
- 失败信息记到 `ScanResult.errors[i]`，**不阻塞其他批次**
- 上游（CLI、scheduler）拿到的 ScanResult 既有成功的 suggestions 也有失败的 errors，可观测

### 5.4 时间是参数化的
- `calculate_days_left(expiry_date, today=None)` 的 `today` 参数可注入
- 全链路向上传递：`scan_batch → ScanRunner.run_for_customer → CLI --today`
- 让 demo 现场可以演示"如果今天是 2026-05-26 那预警是这样"，可重现

### 5.5 配置 per-customer，从 JSON 加载
- `data/config/<customer_id>.actions.json` 持有：
  - `enabled_actions` 白名单 → tool schema enum
  - `disabled_actions` 显式禁用（人类可读）
  - `industry_phrases` 行业话术映射
  - `alert_thresholds` 三档天数
  - `avg_savings_per_batch` 单批次均值（用于 prompt 提示金额量级）
  - `decision_makers` 企微 userid（v0.5 企微推送目标）

### 5.6 数据模型全部 `frozen=True`
- `Batch / Alert / Suggestion / CustomerConfig / AlertThresholds / ScanResult / ScanError` 都是不可变
- 避免下游对原始数据做误改导致的 heisenbug
- 副作用集中在 ScanRunner（构造新对象）与 CLI/scheduler（IO）

---

## 6. 配置加载流

```
ANTHROPIC_API_KEY (env)  ─────►  CLI/scheduler 入口
                                       │
                                       ▼
                              AsyncAnthropic(api_key=...)
                                       │
                                       ▼
                          SuggestionEngine(client=...)

data/config/customerA.actions.json  ──┐
                                       ▼
                          repository.load_customer_config
                                       │
                                       ▼
                          CustomerConfig (frozen Pydantic)
                                       │
                                       ▼
                          ScanRunner.run_for_customer(...)

data/batches/customerA.json  ──┐
                                ▼
                          repository.load_batches
                                │
                                ▼
                          list[Batch]  (frozen Pydantic)
```

---

## 7. 测试架构

```
tests/
├── conftest.py                    # FastAPI TestClient fixture
│
├── models/                        # 数据模型：约束 / frozen / serialization
├── alerts/                        # 业务逻辑：边界值 + invariant
├── suggestion/                    # LLM 调用：MagicMock(spec=AsyncAnthropic)
│   ├── test_prompt.py             # prompt 构建（纯函数）
│   ├── test_schema.py             # tool schema enum 限定
│   └── test_engine.py             # 假 Message → 真 Suggestion 转换链
├── repository/                    # JSON loader：临时目录 + 真实 mock 数据 smoke
├── scheduler/                     # 编排 + cron 注册
└── test_cli.py                    # CLI argparse / format_result / main(--dry-run)
```

**覆盖率约束**：`100%`（含分支覆盖）。CI 通过即代表此约束被守住。

**绝对不做**：
- 不调用真实 Anthropic API
- 不打开真实 HTTP 端口
- 不依赖系统时钟（用 `today=` 注入）

---

## 8. 已知边界 / v0.1 不做的事

| 项 | 当前状态 | v0.5 计划 |
|---|---|---|
| 真实 ERP / WMS 对接 | SAP Business One Service Layer adapter（待真实沙箱验收） | 用友 / 金蝶适配器作为企业插件部署 |
| 企微卡片渲染 | ✅ `src/wecom/cards.py`（4 模板，纯函数） | — |
| 企微真实推送 | ✅ 群机器人 webhook | 交互式应用消息由企业插件提供 |
| 决策与工单持久化 | ✅ SQLite/PostgreSQL 全边界 adapters，运行时显式选择且 PostgreSQL 使用连接池 | 管理式 PostgreSQL 托管 |
| 改方案对话 | ✅ 单轮，会话与原建议可靠关联并审计 | 保持单轮边界 |
| 月度 PDF 报告 | ✅ 持久化决策日志驱动 + 按租户时区定时生成/分发 | 多实例任务协调 |
| 命令接口鉴权 | ✅ 静态 Bearer 兼容模式 + OIDC JWT/JWKS + viewer/operator/admin RBAC | 细粒度策略引擎 |
| 回调防重放 | ✅ 时间窗校验 + SQLite/PostgreSQL 幂等记录；PostgreSQL 原子认领支持多实例 | 幂等记录保留策略 |
| Prompt caching | ❌（每次完整发送） | v0.5 评估收益 |

---

## 9. 跨切面 / 横向关注点（cross-cutting）

| 关注点 | v0.1 实现 | 演进方向 |
|---|---|---|
| 日志 | 统一事件字段：customer/correlation/result/duration；OTLP trace export | 集中审计归档 |
| 配置（API key 等） | `pydantic-settings` 从环境变量加载并校验 | 外部 secrets manager |
| 错误处理 | per-batch try/except，ScanError 留痕 | + retry policy（指数退避） |
| 并发 | LLM 有界并发；SQLite WAL；PostgreSQL `SKIP LOCKED` 多 worker 任务队列 | 独立 worker 自动扩缩容 |
| 时区 | 持久化统一 UTC，扫描/月报按租户 IANA 业务时区 | 按租户配置独立执行时间 |
| 数据库生命周期 | FastAPI lifespan 拥有 SQLite 连接或 PostgreSQL 连接池；关闭时统一释放 | 托管平台连接代理 |
| 指标 | `/metrics` Prometheus exposition；W3C trace context；可选 OTLP exporter | 多实例 SLO 告警规则 |
| 接口安全 | 生产回调加密；OIDC/RBAC；body limit；PostgreSQL 共享限流与幂等 | 审计归档与细粒度策略 |

---

## 10. 如何加一个新模块（指南）

如果你要加 `src/foo/`：

1. **先问**：它属于哪一层？entry / orchestration / business / i/o / model？
2. **守纪律**：依赖方向必须**只向下指**。不要让 `models/` 反向依赖 `foo/`。
3. **入口**：`src/foo/__init__.py` 用 `__all__` 显式导出（mypy strict 要求显式 re-export）。
4. **测试**：`tests/foo/__init__.py` 加上，每个公共函数至少 1 个用例 + 边界 / 失败路径。
5. **跑 `make check`**：100% 覆盖、ruff 通过、mypy strict 通过——才算就绪。

---

## 11. 常用命令速查

| 场景 | 命令 |
|---|---|
| 装依赖 + pre-commit | `make dev` |
| 跑全套检查（CI 等效） | `make check` |
| 自动修格式 | `make fmt` |
| 跑测试 | `make test` |
| 启动 FastAPI dev server | `make run` |
| 一次性扫描客户 A（dry-run） | `make scan CUSTOMER=customerA TODAY=2026-05-26 DRY=1` |
| 一次性扫描客户 A（Anthropic） | `ANTHROPIC_API_KEY=sk-... make scan CUSTOMER=customerA` |
| 一次性扫描客户 A（KIMI/Moonshot） | `MOONSHOT_API_KEY=sk-... uv run python -m src.cli --customer customerA --provider moonshot` |
| 渲染所有卡片到终端预览 | `... uv run python -m src.cli --customer customerA --today 2026-05-26 --render-cards` |
| 离线生成 demo 卡片样本 | `make demo` |
| 生成月度 PDF 报告（mock 数据） | `make report` |
| 真实 LLM 质量验证 | `MOONSHOT_API_KEY=sk-... make validate-llm PROVIDER=moonshot` |

---

*文档维护人：（待填）*
