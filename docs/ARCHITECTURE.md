# Architecture — Shelf-Life Copilot

> 阶段：v0.1（Mock Demo）
> 配套文档：[PRD.md](PRD.md) · [TECH_SPEC.md](TECH_SPEC.md) · [TODO.md](TODO.md)
> 更新日期：2026-05-27

本文档讲清楚**代码长什么样**——分层、依赖方向、关键模块的边界。
面向：新加入的工程师、客户 IT 评估、未来回头看 trade-off 的自己。

---

## 1. 一图看懂

```
┌────────────────────────────────────────────────────────────┐
│                       Entry Points                          │
│   ┌────────────────┐         ┌────────────────────────┐   │
│   │  src/cli.py    │         │  src/main.py (FastAPI) │   │
│   │  one-shot scan │         │  /health (placeholder) │   │
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
├── main.py                     # 入口 ② FastAPI app（v0.1 仅 /health）
│
├── models/                     # 数据契约层（叶子层，无业务依赖）
│   ├── action.py               # ActionType (StrEnum)
│   ├── alert.py                # Alert
│   ├── batch.py                # Batch + Severity
│   ├── customer.py             # CustomerConfig（含不变量校验）
│   ├── suggestion.py           # Suggestion
│   └── thresholds.py           # AlertThresholds
│
├── alerts/                     # 业务层 · 监测引擎（纯函数，无 IO）
│   └── monitor.py              # calculate_days_left / classify_severity / scan_batch
│
├── suggestion/                 # 业务层 · LLM 建议（async，调 Anthropic）
│   ├── engine.py               # SuggestionEngine（依赖注入 AsyncAnthropic）
│   ├── prompt.py               # SYSTEM_PROMPT + build_user_prompt
│   └── schema.py               # build_suggestion_tool（动态 enum）
│
├── repository/                 # I/O 层 · JSON 加载
│   └── loader.py               # load_customer_config / load_batches
│
├── scheduler/                  # 编排层
│   ├── runner.py               # ScanRunner + ScanResult + ScanError
│   └── scheduler.py            # DailyScheduler（APScheduler 包装）
│
└── wecom/                      # 渲染层 · 4 套卡片 + 推送 client（Protocol）
    ├── cards.py                # render_alert / render_work_order /
    │                           #   render_receipt / render_out_of_scope
    │                           #   + render_card_for_alert (dispatcher)
    └── client.py               # WecomClient Protocol + DryRunWecomClient
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

### 5.1 LLM 输出靠 tool_use 强制 JSON
- 比"prompt 里请求输出 JSON 然后正则提取"可靠 10×
- `action` 字段的 `enum` **在每次调用时动态生成**，限定到该客户的 `enabled_actions`
- LLM 在生成阶段就被约束，**不需要后置过滤**
- 见 `src/suggestion/schema.py` `build_suggestion_tool`

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
| 真实 ERP / WMS 对接 | ❌ 只读 JSON | 加 ERPAdapter Protocol，实现 SAP/用友/金蝶 |
| 企微卡片渲染 | ✅ `src/wecom/cards.py`（4 模板，纯函数） | — |
| 企微真实推送 | ❌（仅 `DryRunWecomClient`） | v0.5 加 `HttpWecomClient`，订阅 DailyScheduler 的 on_result |
| 决策日志持久化（Decision 表） | ❌ | SQLite → PostgreSQL |
| 改方案的多轮对话 | ❌（仅支持单轮） | v0.5 视情况再决定（PRD 决策已锁定单轮） |
| 月度 PDF 报告 | ❌ | reportlab / weasyprint |
| 多租户隔离的鉴权 | ❌ | FastAPI 接口层做 JWT |
| Prompt caching | ❌（每次完整发送） | v0.5 评估收益 |

---

## 9. 跨切面 / 横向关注点（cross-cutting）

| 关注点 | v0.1 实现 | 演进方向 |
|---|---|---|
| 日志 | `logging.basicConfig` 在 CLI 入口 | v0.5 结构化 JSON + correlation_id |
| 配置（API key 等） | 环境变量 (`os.environ`) | v0.5 pydantic-settings Settings 类 |
| 错误处理 | per-batch try/except，ScanError 留痕 | + retry policy（指数退避） |
| 并发 | scan 循环串行（每批次串行调 LLM） | v0.5 用 `asyncio.gather` 并行多批次 |
| 时区 | 用户输入 `--today` 是本地日期 | v0.5 确认是否考虑客户跨时区 |

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
| 一次性扫描客户 A（含 LLM） | `ANTHROPIC_API_KEY=sk-... make scan CUSTOMER=customerA` |
| 渲染所有卡片到终端预览 | `ANTHROPIC_API_KEY=sk-... uv run python -m src.cli --customer customerA --today 2026-05-26 --render-cards` |

---

*文档维护人：（待填）*
