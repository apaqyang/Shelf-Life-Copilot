# Shelf-Life Copilot

> 食品行业临期 / 保质期管理 AI 副驾
> 每天早上 7 点，把"哪个批次快过期 + 该怎么处置 + 能省多少钱"通过企微卡片主动推送给采购/生产/供应链总监，一键决策、自动派单。

[![CI](https://github.com/apaqyang/Shelf-Life-Copilot/actions/workflows/ci.yaml/badge.svg)](https://github.com/apaqyang/Shelf-Life-Copilot/actions/workflows/ci.yaml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![Code style](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/badge/license-Proprietary-red)](#)

---

## 当前阶段

**v0.1 Mock Demo** — 2 周交付窗口（起点待定，目标 ~2026-06-09）

## 文档导航

| 文档 | 用途 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 产品规格、模块设计、4 大决策记录、销售工具 |
| [docs/TODO.md](docs/TODO.md) | Week 1-2 任务清单 + 验收标准 |
| [docs/TECH_SPEC.md](docs/TECH_SPEC.md) | 技术架构、数据模型、接口设计 |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 5 分钟现场 Demo 脚本（含 A/B 双场景 + FAQ 8 题） |
| [docs/RUNBOOK_DEMO.md](docs/RUNBOOK_DEMO.md) | 演前 30 分钟操作 + 三层降级方案 |
| [docs/FALLBACK_VIDEO.md](docs/FALLBACK_VIDEO.md) | 2 分钟兜底视频分镜脚本 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块分层 / 依赖图 / 设计决策记录 |
| [docs/demo_samples/](docs/demo_samples/) | 现成的卡片 markdown 样本 + 月度 PDF 报告 |

## 项目结构

```
.
├── .claude/         # Claude Code 自定义命令 / hooks / agents / 规则
│   ├── commands/
│   ├── hooks/
│   ├── agents/
│   └── rules/
├── docs/            # 项目文档
├── src/             # 源代码（Python FastAPI）
├── tests/           # pytest 测试
└── README.md
```

## 技术栈

- **Runtime**：Python 3.11+ / FastAPI
- **LLM**（provider 抽象，可热切换）：
  - Anthropic Claude — Sonnet 4.6 默认 / Opus 4.7 复杂场景 / Haiku 4.5 改方案
  - Moonshot KIMI — moonshot-v1-32k 默认（OpenAI 协议兼容，国内可访问）
- **集成**：企业微信群机器人 + 应用消息 API
- **存储**：SQLite (v0.1) → PostgreSQL (v0.5+)
- **调度**：APScheduler
- **报告**：reportlab + STSong-Light CID 中文（月度 PDF）

## 首批锚定客户

| 编号 | 行业 | 年损 | 决策人 | Demo 优先级 |
|---|---|---|---|---|
| **客户 A** | 冷冻食品（虾仁 / 鱼糜） | 150 万 / 年 | 供应链总监 | P0 |
| **客户 B** | 预制菜（盒饭 / 馅料） | 86 万 / 年 | 采购总监 | P0 |

## 商业模式

- **试点（v0.5）**：3 个月完全免费，换数据 + 客户背书
- **商业版（v1.0）**：固定年费按客户年损分档
  - < 100 万 → 8 万/年
  - 100-300 万 → 15 万/年
  - \> 300 万 → 议价

## Quick Start（开发者）

```bash
# 1. 装依赖 + pre-commit
make dev

# 2. 配置任一 LLM provider（按需）
cp .env.example .env
# 写入 ANTHROPIC_API_KEY 或 MOONSHOT_API_KEY 任一即可

# 3. 离线 dry-run（无 API key 也能跑）
make scan CUSTOMER=customerA TODAY=2026-05-26 DRY=1

# 4. 实际 LLM 调用（任选其一）
ANTHROPIC_API_KEY=sk-... uv run python -m src.cli --customer customerA --render-cards
MOONSHOT_API_KEY=sk-... uv run python -m src.cli --customer customerA --provider moonshot --render-cards

# 5. 生成销售弹药（无 LLM）
make demo           # 离线渲染 demo 卡片到 docs/demo_samples/
make report         # 生成月度 PDF 报告

# 6. PRD §9.1 真实 LLM 合规率验证
MOONSHOT_API_KEY=sk-... make validate-llm PROVIDER=moonshot
```

详细技术规格见 [docs/TECH_SPEC.md](docs/TECH_SPEC.md)，运行时操作见 [docs/RUNBOOK_DEMO.md](docs/RUNBOOK_DEMO.md)。
