# Shelf-Life Copilot · 食品行业临期 AI 副驾

> **每天早 7 点，把"哪个批次快过期 + 该怎么处置 + 能省多少钱"通过企微卡片推给总监，一键决策、自动派单。**
> 客户 A（年损 150 万）实测：3 个月帮抠回 60-90 万。

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![CI](https://github.com/apaqyang/Shelf-Life-Copilot/actions/workflows/ci.yaml/badge.svg)](https://github.com/apaqyang/Shelf-Life-Copilot/actions/workflows/ci.yaml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](#)
[![Tests](https://img.shields.io/badge/tests-390%2B-brightgreen)](#)

---

## 🚀 5 分钟自助试用（零配置）

不需要 Anthropic / KIMI API key，不需要企业微信管理员，不需要任何注册。

```bash
git clone https://github.com/apaqyang/Shelf-Life-Copilot.git
cd Shelf-Life-Copilot
docker compose up
```

然后在另一个终端：

```bash
# 跑一次客户 A 的临期扫描，看 AI 在干什么
docker compose exec app uv run python -m src.cli \
  --customer customerA --today 2026-05-26 --provider offline --render-cards

# 离线渲染示例企微卡片到 docs/demo_samples/
docker compose exec app make demo

# 跑销售线索评估问卷（PRD §12.1）
docker compose exec app make qualify
```

完整食品厂 IT 主管视角 5 步跑通流程：[**docs/QUICKSTART.md →**](docs/QUICKSTART.md)

---

## 🍱 这个工具解决什么问题

食品厂总监每天最头疼的两个数字：

| 痛点 | 现状 | 用了之后 |
|---|---|---|
| 报损率 | 年损 50-300 万，"凭车间经验"猜哪批快过期 | AI 提前 3-25 天预警 + 处置建议（转加工 / 打折清仓 / 员工食堂消化） |
| 决策延迟 | 信息从仓库到总监走 N 个微信群，延迟 1-3 天 | 早 7:00 企微卡片直送总监手机，一键决策 |
| 派单失真 | 总监同意了，车间没收到 / 收到延迟 | 同意自动派工单 @ 车间主任，全程留决策日志 |
| ROI 不透明 | 试了某 SaaS，3 个月后不知道帮没帮到 | 月度 PDF 报告（节省总额 / ROI / 最佳动作）一页纸给老板汇报 |

---

## 🧱 架构一图

```
07:00 DailyScheduler ──┐
                       ↓
                    ScanRunner ──→ AI 建议（offline / KIMI / Claude）
                       ↓
                    企微卡片（群机器人 webhook 或自建应用）
                       ↓
                总监点 ✅ 同意 / ❌ 稍后 / 💬 改方案
                       ↓
            POST /webhook/wecom → DecisionStore (SQLite)
                       ↓
                每月 1 号 MonthlyReportScheduler
                       ↓
            真实数据驱动 → 月度 PDF + 摘要卡推给总监
```

完整模块分层 / 依赖图 / 设计决策见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 💼 商业模式（Open Core）

Apache/GPL 的开源核心保证 **下载即用、源码可审、私有化部署无供应商绑定**。
企业版功能（路径 B 实时回调、ERP 对接、多租户管理后台）按插件商业授权。

| 客户体量 | 推荐档 | 大概 ROI |
|---|---|---|
| 年损 < 100 万 | 开源版自托管，免费 | — |
| 年损 100-300 万 | 商业版 8-15 万 / 年 + 必选插件 | 2-4× |
| 年损 > 300 万 | 议价（建议起步 25 万） + 私有化部署服务 | 4-6× |

填一份 5 分钟问卷拿到你的报价 + 一页纸 ROI PDF：

```bash
make qualify
# 输出 markdown 摘要 + data/leads/<客户名>_<日期>.pdf
```

[完整销售流程文档（PRD §12.1） →](docs/PRD.md#121-年损快速诊断问卷销售前置工具)

---

## 📦 模块清单（v0.1 完成度）

| 模块 | 路径 | 状态 |
|---|---|---|
| 监测引擎（3 档预警阈值） | `src/alerts/` | ✅ |
| LLM 建议生成器（Claude / KIMI / offline） | `src/suggestion/` | ✅ |
| 企微卡片（4 模板）+ 群机器人推送 | `src/wecom/` | ✅ |
| 改方案单轮重生成 | `src/scheduler/runner.py::revise_for_batch` | ✅ |
| 决策日志 SQLite 持久化 | `src/persistence/DecisionStore` | ✅ |
| 建议日志 SQLite（让 webhook click 拿真实 action/savings） | `src/persistence/SuggestionStore` | ✅ |
| 月度 PDF 报告 + 摘要卡 + cron 定时 | `src/reports/` + `src/scheduler/monthly.py` | ✅ |
| 路径 B 企微回调（plaintext 骨架） | `src/webhook/` | ✅ |
| 长跑服务入口（FastAPI lifespan + 调度器） | `src/runtime/lifespan.py` | ✅ |
| 销售线索评估问卷 + ROI 一页纸 PDF | `src/sales/` + `tools/qualify_lead.py` | ✅ |
| **企微回调 AES 加解密 + 签名校验** | — | ⏳ 等客户 corp_secret |
| **ERP 对接插件**（SAP / 用友 / 金蝶 / 自研） | — | ⏳ v0.5+ |

**当前指标**：391 测试 · 100% 覆盖率 · 21+ commits · CI 全绿

---

## 🛠️ 开发者（本地不用 Docker）

```bash
# 装依赖 + pre-commit
make dev

# 跑全套检查（CI 等效）
make check

# offline 模式跑一次扫描（不需要任何 API key）
make scan CUSTOMER=customerA TODAY=2026-05-26 PROVIDER=offline
# 或直接 CLI：
uv run python -m src.cli --customer customerA --today 2026-05-26 --provider offline

# 接真实 LLM（任选其一）
export ANTHROPIC_API_KEY=sk-...
export MOONSHOT_API_KEY=sk-...    # OpenAI 协议，国内可访问
uv run python -m src.cli --customer customerA --provider moonshot --render-cards

# 启动长跑服务（自带 daily/monthly scheduler + /webhook/wecom 回调）
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

更多命令 `make help`，技术细节见 [docs/TECH_SPEC.md](docs/TECH_SPEC.md)。

---

## 📚 文档导航

| 文档 | 看什么 |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | **食品厂 IT 主管 5 分钟试用指南**（含 FAQ） |
| [docs/blog/](docs/blog/) | **博客**：行业洞察、案例拆解、ROI 测算（深度长文） |
| [docs/PRD.md](docs/PRD.md) | 产品规格、模块设计、商业模式、销售工具 |
| [docs/TECH_SPEC.md](docs/TECH_SPEC.md) | 技术架构、数据模型、接口设计 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 分层 / 依赖图 / 设计决策记录 |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 5 分钟现场 Demo 脚本（含 A/B 双场景 + FAQ 8 题） |
| [docs/RUNBOOK_DEMO.md](docs/RUNBOOK_DEMO.md) | 演前 30 分钟操作 + 三层降级方案 |
| [docs/MARKETING.md](docs/MARKETING.md) | 内容营销 SOP（团队内部，关键词 / 渠道 / 节奏） |
| [docs/TODO.md](docs/TODO.md) | 当前进度 + 验收清单 |
| [docs/demo_samples/](docs/demo_samples/) | 现成的卡片样本 + 月度 PDF 报告 |

---

## 📜 License

[AGPL-3.0-or-later](LICENSE) — 您可以自由使用、修改、分发本项目；如果以网络服务形式提供，
必须把您修改的源码公开（AGPL 网络条款）。商业版企业插件单独商业许可，请联系作者。

> **食品厂 IT 主管须知**：AGPL 不影响您自己内部使用，无论改不改源码都不需要公开。
> 只有当您把本项目作为 SaaS 对**外**售卖时，AGPL §13 才要求公开修改部分。
