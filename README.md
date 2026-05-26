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
- **LLM**：Anthropic Claude（Sonnet 4.6 默认 / Opus 4.7 复杂场景 / Haiku 4.5 改方案）
- **集成**：企业微信群机器人 + 应用消息 API
- **存储**：SQLite (v0.1) → PostgreSQL (v0.5+)
- **调度**：APScheduler

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
# 1. 克隆 + 安装依赖
uv venv && uv pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env  # 填入 ANTHROPIC_API_KEY / WECOM_* 等

# 3. 启动后端
uvicorn src.main:app --reload

# 4. 触发一次扫描
curl -X POST http://localhost:8000/alerts/scan
```

详细技术规格见 [docs/TECH_SPEC.md](docs/TECH_SPEC.md)。
