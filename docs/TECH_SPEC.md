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
| LLM | `anthropic` Python SDK | Sonnet 4.6 默认 / Opus 4.7 复杂 / Haiku 4.5 改方案 |
| 企微 | 企业微信群机器人 + 应用消息 API | |
| 存储 | SQLite（schema migration + WAL）→ PostgreSQL | 业务层依赖 Repository Protocol |
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
```

---

## 4. 核心接口

### 4.1 `POST /api/scans`
使用 `Authorization: Bearer <API_TOKEN>` 和 `Idempotency-Key` 手动触发单客户扫描，内部复用 `ScanRunner`。
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

### 4.4 内部：`suggest(batch, customer_config) → Suggestion`
LLM 建议生成器核心函数。

### 4.5 内部：`regenerate(original_suggestion, user_feedback) → Suggestion`
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
  "decision_makers": ["wecom_userid_zhangzong"]
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
  "decision_makers": ["wecom_userid_lizong"]
}
```

> 注：客户 B 保质期普遍更短，阈值整体收紧。

---

## 7. 部署（v0.1）

- 本地 `docker-compose up`（Python 服务 + SQLite 卷）
- SQLite 启动时自动执行带版本迁移；迁移单版本事务失败时回滚
- 运行时使用 WAL、5 秒 busy timeout 和显式连接关闭
- 环境变量：
  - `ANTHROPIC_API_KEY`
  - `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET`
  - `WECOM_TEST_GROUP_ID`（Demo 推送目标群）
  - `API_TOKEN`（`/api/*` Bearer token）
  - `WEBHOOK_REPLAY_WINDOW_SECONDS`
  - `MAX_REQUEST_BODY_BYTES`
  - `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`
- v0.5+：客户私有化部署支持（VPC / 厂内服务器）

---

## 8. 安全 & 合规

- LLM 不直接执行任何动作，**仅生成建议**
- 所有 prompt + 模型响应留痕（用于追溯）
- 越界请求即便生成卡片，工单生成前需运营/实施二次确认
- 生产环境启动时强制使用安全的企微消息加密适配器
- 企微回调使用时间窗校验和 SQLite 幂等记录防重放
- 写接口使用请求体上限和按来源/路径的滑动窗口限流；`/api/*` 还要求 Bearer token
- v0.5+ 支持私有化部署，库存数据不出客户网

---

## 9. 监控（v0.5 起接入）

- LLM 调用成功率 / 平均延迟 / token 消耗
- 卡片送达率（企微回调 ACK）
- 决策响应时长（推送 → 同意 时间差）
- 采纳率（approve / total）

---

## 10. v0.1 不解决的开放点

- ERP / WMS 真实对接
- 多租户隔离的鉴权设计
- 跨批次联合优化（v1.5）
- 报告自动定时生成与分发
- 工单实绩驱动的模型反向校准
