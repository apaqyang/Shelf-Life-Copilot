# Tech Spec — Shelf-Life Copilot

> 配套：[PRD.md](PRD.md)
> 阶段：v0.1（Mock Demo）
> 更新日期：2026-05-26

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
| 存储 | SQLite (v0.1) → PostgreSQL (v0.5+) | |
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

### 4.1 `POST /alerts/scan`
触发批次扫描（手动 / APScheduler 定时调用）。
- Request: `{"customer_id": "customerA"}` 或为空（扫描全部）
- Response: `{"alerts_generated": 5, "cards_sent": 5}`

### 4.2 `POST /webhook/wecom`
企微回调入口，处理：
- 按钮事件：同意 / 稍后 / 改方案
- 文字反馈：进入改方案单轮重生成
- 工单回执：车间"已完成"按钮

### 4.3 `GET /customers/{id}/decisions`
查询客户历史决策（管理后台用，v0.5 接入）。

### 4.4 内部：`suggest(batch, customer_config) → Suggestion`
LLM 建议生成器核心函数。

### 4.5 内部：`regenerate(original_suggestion, user_feedback) → Suggestion`
改方案单轮重生成。

---

## 5. Prompt 设计

详细 Prompt 模板见 [PRD.md §6.2](PRD.md)。

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
- 环境变量：
  - `ANTHROPIC_API_KEY`
  - `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_SECRET`
  - `WECOM_TEST_GROUP_ID`（Demo 推送目标群）
- v0.5+：客户私有化部署支持（VPC / 厂内服务器）

---

## 8. 安全 & 合规

- LLM 不直接执行任何动作，**仅生成建议**
- 所有 prompt + 模型响应留痕（用于追溯）
- 越界请求即便生成卡片，工单生成前需运营/实施二次确认
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
- 月度 PDF 报告生成（v0.5）
- 工单完成情况的反向校准（v0.5）
