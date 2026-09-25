# Tech Spec — Shelf-Life Copilot

> 配套：[ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md) · [DEVELOPMENT_TASKS.md](DEVELOPMENT_TASKS.md)
> 阶段：v0.1（Mock Demo）
> 更新日期：2026-09-24

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  企业微信 (用户唯一触点)                                  │
└──────────────────────┬──────────────────────────────────┘
                       │ WeCom Webhook / Bot API
┌──────────────────────▼──────────────────────────────────┐
│  Shelf-Life Copilot 后端 (Python FastAPI)               │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ 监测引擎    │  │ AI 建议器   │  │ 卡片渲染 / 派单   │  │
│  │ APScheduler│  │ Claude     │  │ WeCom SDK        │  │
│  └────────────┘  └─────┬──────┘  └──────────────────┘  │
└────────────────────────┼────────────────────────────────┘
                         │
                ┌────────▼─────────┐
                │  Anthropic API   │
                │  (Claude 4.x)    │
                └──────────────────┘

数据源：v0.1 = 本地 Mock JSON ； v0.5+ = 客户 ERP / WMS
```

---

## 2. 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| Runtime | Python 3.11+ | |
| Web | FastAPI | OpenAPI 自动文档 / async 友好 |
| 任务调度 | APScheduler | 每日 07:00 扫描 |
| LLM | provider protocol | Claude / KIMI / 本地 OpenAI-compatible / offline |
| 企微 | 企业微信群机器人 + 应用消息 API | |
| 存储 | SQLite（schema migration + WAL）/ PostgreSQL | 业务层依赖 Repository Protocol |
| 测试 | pytest + pytest-asyncio | |
| 包管理 | uv | |
| 代码质量 | ruff + black + mypy | |

---

## 3. 数据模型（v0.1 简化）

### Material（物料）
```python
material_id: str  # 主键
name: str
category: str
customer_id: str  # 多租户标识
unit: str
```

### Batch（批次）
```python
batch_id: str  # 主键
material_id: str
production_date: date
expiry_date: date
stock_qty: float
warehouse: str
status: enum  # active / consumed / disposed
```

### Alert（预警事件）
```python
alert_id: str  # 主键
batch_id: str
triggered_at: datetime
severity: enum  # yellow (≤30d) / orange (≤15d) / red (≤7d)
days_left: int
```

### Suggestion（AI 建议）
```python
suggestion_id: str  # 主键
alert_id: str
action: str           # 必须在 customer_config.enabled_actions 内（越界除外）
savings_estimate: float
rationale: str        # ≤ 30 字
confidence: float
is_standard: bool     # false → 越界，需人工复核
llm_model: str        # 留痕
llm_prompt_hash: str  # 留痕
```

### Decision（决策记录）
```python
decision_id: str  # 主键
suggestion_id: str
decision: enum  # approve / postpone / revise
decided_by: str
decided_at: datetime
final_action: str
actual_savings: float | None  # 工单完成后回填
```

### WorkOrder（处置工单）
```python
work_order_id: str
batch_id: str
customer_id: str
material_name: str
action: ActionType
status: enum  # pending / in_progress / completed / cancelled
created_at: datetime  # 必须带时区
updated_at: datetime  # 必须带时区，不得早于 created_at
actual_qty: float | None
actual_savings: float | None
completed_by: str | None
completed_at: datetime | None
completion_source: str | None
```

正常完成路径为 `pending → in_progress → completed`；`pending` 和 `in_progress` 也可转为 `cancelled`，终态不可逆转。企微“同意”回调在同一 SQLite 事务中写入 Decision 和 WorkOrder，重复回调返回原工单。工单完成时，回执与对应 Decision 的实绩字段在同一事务中更新。

### CustomerConfig（客户配置 — JSON 文件）
```python
customer_id: str
industry: str
enabled_actions: list[str]
disabled_actions: list[str]
industry_phrases: dict[str, str]
alert_thresholds: dict  # {yellow: 30, orange: 15, red: 7}
decision_makers: list[str]  # 企微 userid
business_timezone: str  # IANA 时区，默认 Asia/Shanghai
```

---

## 4. 核心接口

### 4.1 `POST /api/scans`
使用 `Authorization: Bearer <token>` 和 `Idempotency-Key` 手动触发单客户扫描，内部复用 `ScanRunner`。静态兼容模式读取 `API_TOKEN`；OIDC 模式要求 `operator` 或 `admin` 角色及目标租户声明。
- Request: `{"customer_id": "customerA", "today": "2026-05-26", "skip_llm": false}`
- Response: 批次数、预警数、建议数、卡片数，以及全部扫描批次的成功/失败摘要
- 相同幂等键完成后返回首次结果；正在处理时返回 `409`

### 4.2 `POST /webhook/wecom`
企微回调入口，处理：
- 按钮事件：同意 / 稍后 / 改方案
- 校验回调时间窗（默认 5 分钟）并持久化去重
- 生产环境拒绝明文回调加密实现

### 4.3 `POST /api/work-orders/{work_order_id}/complete`
使用 Bearer token、`Idempotency-Key` 和 `X-Operator-ID` 提交车间完成回执。仅 `in_progress` 工单可完成；服务端记录 UTC 完成时间，并原子回填关联 Decision 的实际数量和实际节省。

### 4.4 多租户查询与管理台

- `GET /api/customers`：当前主体可访问的租户。
- `GET /api/customers/{customer_id}/batches`：租户批次分页列表。
- `GET /api/customers/{customer_id}/work-orders`：租户工单分页列表。
- `GET /admin`：无构建依赖的运营界面；页面不嵌入 token。

### 4.5 跨批次处置计划

`POST /api/optimization-plans` 在质量门禁通过后生成 `pending_approval` 计划。
`POST /api/optimization-plans/{plan_id}/execute` 必须提供 `X-Operator-ID`，并在同一事务中记录批准、决策和工单。

### 4.6 工单实绩质量

`GET /api/quality/outcomes` 要求 `admin` 角色、租户声明以及带时区的 `start`/`end` 范围，返回按 provider 和动作分组的已核实偏差、绝对误差和回归门禁结果。

### 4.6 内部：`suggest(batch, customer_config) → Suggestion`
LLM 建议生成器核心函数。

### 4.7 内部：`regenerate(original_suggestion, user_feedback) → Suggestion`
改方案单轮重生成。

---

## 5. Prompt 设计

详细 Prompt 模板见 `src/suggestion/prompt.py`。

关键约束：
- **输出严格 JSON**：`{"action", "savings", "rationale", "confidence"}`
- **action 强校验**：必须在 `customer_config.enabled_actions` 内
- **越界处理**：若反馈中提及超出动作集的诉求，LLM 仍返回但 `is_standard=false`
- **模型选择**：
  - 主流程 → `claude-sonnet-4-6`
  - 跨批次联合 → `claude-opus-4-7`（v1.5）
  - 改方案 → `claude-haiku-4-5-20251001`（低延迟）

---

## 6. 配置文件示例

### `config/customer_A.actions.json`
```json
{
  "customer_id": "customerA",
  "industry": "frozen_seafood",
  "enabled_actions": [
    "transform",
    "discount_clearance",
    "transfer_warehouse",
    "report_loss"
  ],
  "disabled_actions": ["employee_canteen"],
  "industry_phrases": {
    "transform": "转加工为虾饺馅 / 鱼丸 等下游产品",
    "discount_clearance": "打折清仓至 B2B 渠道"
  },
  "alert_thresholds": {"yellow": 30, "orange": 15, "red": 7},
  "decision_makers": ["wecom_userid_zhangzong"],
  "business_timezone": "Asia/Shanghai"
}
```

### `config/customer_B.actions.json`
```json
{
  "customer_id": "customerB",
  "industry": "prepared_meals",
  "enabled_actions": [
    "employee_canteen",
    "discount_clearance",
    "transfer_warehouse",
    "report_loss"
  ],
  "disabled_actions": ["transform"],
  "industry_phrases": {
    "employee_canteen": "转员工食堂消化",
    "discount_clearance": "打折清仓至社区团购"
  },
  "alert_thresholds": {"yellow": 14, "orange": 7, "red": 3},
  "decision_makers": ["wecom_userid_lizong"],
  "business_timezone": "Asia/Shanghai"
}
```

> 注：客户 B 保质期普遍更短，阈值整体收紧。

---

## 7. 部署（v0.1）

- 本地 `docker-compose up`（Python 服务 + SQLite 卷）
- SQLite 启动时自动执行带版本迁移；迁移单版本事务失败时回滚
- 运行时使用 WAL、5 秒 busy timeout 和显式连接关闭
- PostgreSQL 通过 `uv sync --extra postgres` 安装驱动；启动时在连接池中执行幂等 schema 迁移
- 后端由 `PERSISTENCE_BACKEND` 显式选择；选择 PostgreSQL 时修订、优化、幂等、队列、月报和限流配额共享同一数据库边界
- 环境变量：
  - `ANTHROPIC_API_KEY`
  - `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET`
  - `WECOM_TEST_GROUP_ID`（Demo 推送目标群）
  - `API_TOKEN`（`/api/*` Bearer token）
  - `API_TOKEN_CUSTOMERS`（token 可访问的客户集合）
  - `AUTH_MODE`、`OIDC_ISSUER`、`OIDC_AUDIENCE`、`OIDC_JWKS_URL`（生产 JWT/OIDC）
  - `WEBHOOK_REPLAY_WINDOW_SECONDS`
  - `MAX_REQUEST_BODY_BYTES`
  - `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`
  - `SCAN_CONCURRENCY`
  - `PERSISTENCE_BACKEND`（`sqlite` / `postgres`）
  - `POSTGRES_DSN` / `POSTGRES_POOL_MIN_SIZE` / `POSTGRES_POOL_MAX_SIZE`
  - `ERP_BACKEND` / `SAP_B1_BASE_URL` / `SAP_B1_SESSION_COOKIE_FILE`
  - `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME`
  - `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL` / `LOCAL_LLM_API_KEY`
- v0.5+：客户私有化部署支持（VPC / 厂内服务器）

---

## 8. 安全 & 合规

- LLM 不直接执行任何动作，**仅生成建议**
- 所有 prompt + 模型响应留痕（用于追溯）
- 越界请求即便生成卡片，工单生成前需运营/实施二次确认
- 生产环境启动时强制使用安全的企微消息加密适配器
- 企微回调使用时间窗校验和持久化幂等记录防重放；PostgreSQL 的原子 `ON CONFLICT` 认领保证跨实例仅一个处理者
- 写接口使用请求体上限和按来源/路径限流；SQLite 单节点使用进程内滑动窗口，PostgreSQL 多实例使用数据库事务时间和原子固定窗口计数，共享同一配额；`/api/*` 还要求 Bearer token
- 共享限流后端不可用时受保护写请求失败关闭并返回 `503`
- 生产可使用 OIDC JWKS 验证 JWT 签名、issuer、audience 和时间声明；`viewer/operator/admin` 控制路由权限，租户/角色拒绝输出安全审计事件
- v0.5+ 支持私有化部署，库存数据不出客户网

---

## 9. 监控

- `/metrics` 以 Prometheus text exposition 提供扫描结果、LLM 成功/失败与延迟、推送失败、回调处理数和报告结果
- 日志事件统一包含 `customer_id`、`correlation_id`、`result` 和 `duration_ms`
- 多实例由 Prometheus 分别拉取并聚合；W3C `traceparent` 在 HTTP 入口、响应和外发企微/ERP 请求间传播，配置 OTLP endpoint 后导出 OpenTelemetry span
- `/api/quality/outcomes` 仅使用已核实工单实绩，按 provider/动作计算偏差、绝对误差和归一化误差；历史工单关联决策时刻之前的最后一条建议
- 每个租户可通过 `business_timezone` 配置 IANA 时区；每日扫描与月报按各自本地日历触发，持久化时间仍为 UTC

## 9.1 持久任务队列

APScheduler 只负责将每日扫描写入当前后端的持久队列，worker 独立认领、重试和完成任务。PostgreSQL 使用行锁与 `SKIP LOCKED` 支持多 worker 并发认领。
默认在 Web 进程内嵌一个 worker；`TASK_QUEUE_ENABLED=false` 可回退到直接执行。
可用性 SLO 和可重现负载门禁见 [AVAILABILITY.md](AVAILABILITY.md)。

---

## 10. 后续开放点

- SAP Business One 真实厂商沙箱在线验收（适配器与离线契约已完成）
- OIDC 审计日志的长期归档策略
- 已核实样本累积后的 provider 策略自动晋级
