# TODO — Shelf-Life Copilot

> 范围：v0.1 Mock Demo（2 周）
> 起点：2026-05-26
> 配套：[PRD.md](PRD.md) §8 / [TECH_SPEC.md](TECH_SPEC.md) / [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 进度概览（更新于 2026-05-31）

- ✅ **工程基础设施**：pyproject / ruff / mypy strict / pytest / GitHub Actions CI / pre-commit
- ✅ **数据层**：models + repository + Mock 数据（A:7 批次 / B:6 批次）
- ✅ **监测引擎**：`src/alerts/`（per-customer 阈值）
- ✅ **LLM 建议生成器**：`src/suggestion/`（Claude tool_use 强制 JSON）
- ✅ **编排层 + CLI**：`src/scheduler/` + `src/cli.py`（端到端 dry-run 验证通过；改方案入口已暴露）
- ✅ **企微卡片渲染层**：`src/wecom/`（4 套模板 · DryRunWecomClient · `--render-cards`）
- ✅ **改方案单轮重生成**：`ScanRunner.revise_for_batch` + CLI `--revise-batch / --feedback`（越界自动红标）
- ✅ **企微真实推送 · 路径 A（群机器人 webhook）**：`WebhookWecomClient` + CLI `--push-webhook` + `make push`（自测路径，群主权限即可，2026-05-31 真群验证 6 条 errcode=0）
- ✅ **Demo 离线兜底**：`make demo` + RUNBOOK + 兜底视频分镜
- ✅ **月度 PDF 报告生成器**：`src/reports/` + `make report`（销售弹药，PRD §5.5）
- ✅ **决策日志 SQLite 持久化**：`src/persistence/DecisionStore` + CLI `--record-decision` + `make report SOURCE=sqlite`（v0.5 持久层就位，端到端闭环已 smoke-test）
- ✅ **路径 B 服务端骨架**：`src/webhook/` FastAPI POST `/webhook/wecom` 处理 click 事件（approve/snooze/revise）→ DecisionStore；GET 回显 echostr。明文模式，AES + 签名待客户 PoC 启动时加。
- ✅ **月度报告自动定时**：`MonthlyReportScheduler` APScheduler cron 每月 1 号 08:00 Asia/Shanghai；`render_monthly_summary_card` 摘要卡；`make monthly [PUSH=1]` 手动触发；端到端 smoke 通过（决策 → SQLite → PDF + 卡片 → 企微群）
- ✅ **长跑服务入口**：`src/runtime/` Settings (pydantic-settings) + FastAPI lifespan 把 DailyScheduler + MonthlyReportScheduler 挂在 uvicorn 启动上；`uv run uvicorn src.main:app` 一行起服务；缺 LLM key 时 daily 自动跳过 + warn
- ✅ **SuggestionStore + 决策真值闭环**：`src/persistence/SuggestionStore` 持久化每次 LLM 输出；ScanRunner 自动 save；webhook click 查 `latest_for_batch` 用真实 action/savings_estimate 填 Decision（替换之前 TRANSFORM/0.0 占位）；CLI scan/revise 也接入。月度报告数据真实性闭环。
- ✅ **销售线索评估工具（PRD §12.1）**：`src/sales/` Pydantic 模型 + `assess_lead()` 业务规则（分档 / 优先级 / 推荐动作 / ROI / 销售话术 全部 PRD 原文）+ `tools/qualify_lead.py` 交互式 CLI + `make qualify`。客户 A smoke：⭐⭐⭐ · 15 万年费 · ROI 2.4x。
- ✅ **ROI 一页纸 PDF**：`src/sales/render_lead_pdf` 单页 A4（4 大 KPI / 试点说服段 / 动作 / 销售联系名片）+ CLI `--contact-name/phone/email` + `--no-pdf` 开关。客户 A 端到端：JSON 留档 + PDF 同时出。
- ⏳ **路径 B 加解密 + 签名校验**：需客户 corp_secret，PoC 启动时单独 PR
- ⏳ **路径 B 文字反馈 → LLM 自动重生成**：需会话状态管理，v0.2 范围
- ⏳ **Demo 内部彩排 ≥ 2 次 + 兜底视频录制**（需多人）

**当前指标**：384 测试 passed · 覆盖率 100% · 19+ commits · CI 全绿
**仓库**：https://github.com/apaqyang/Shelf-Life-Copilot

---

## Week 1 — 基础设施 + 推送链路

### 后端骨架
- [x] 初始化 FastAPI 项目结构 → `src/main.py` + 子包（models / alerts / suggestion / repository / scheduler / cli）
- [x] 配置 uv + pyproject.toml + ruff（弃用 black，ruff 一统 lint+format）+ mypy strict + pytest + coverage
- [x] 写 `.env.example`（ANTHROPIC_API_KEY / WECOM_* / APP_ENV）
- [x] 接入 Anthropic SDK，跑通最简调用 → `SuggestionEngine`（async，tool_use 强制 JSON）
- [x] 接入企微 API，**跑通最简文本推送**到测试群 → 群机器人 webhook 路径（`WebhookWecomClient` + CLI `--push-webhook` + `make push`）

### 数据层
- [x] 设计 Mock JSON schema → `src/models/{batch,alert,customer,suggestion,thresholds,action}.py`
- [x] 填入客户 A 7 个 mock 批次（覆盖健康/YELLOW/ORANGE/RED/已过期）→ `data/batches/customerA.json`
- [x] 填入客户 B 6 个 mock 批次（用收紧阈值 14/7/3）→ `data/batches/customerB.json`
- [x] 设计并写入 `customer_A.actions.json` / `customer_B.actions.json`（含 avg_savings_per_batch）

### 监测引擎
- [x] 实现剩余保质期计算 → `src/alerts/monitor.py::calculate_days_left`
- [x] 实现三档预警阈值（per-customer 配置）→ `classify_severity`
- [x] 接入 APScheduler，每日 07:00 触发 → `src/scheduler/scheduler.py::DailyScheduler`

### LLM Prompt 工程
- [x] 起草核心建议 Prompt → `src/suggestion/prompt.py`（含改方案分支）
- [x] Schema 校验 + 越界标签 → 全集 enum + Python 端 `is_standard` 判断（PRD §5.3 越界兜底生效）
- [x] **LLM Provider 抽象** → AnthropicProvider + MoonshotProvider（OpenAI 协议）
- [x] **5+ 真实场景合规率验证脚本** → `tools/validate_llm.py`
- [x] **真实 LLM 验证（KIMI / moonshot-v1-32k）通过** → 15/15 成功 · in-scope 合规 100% · 越界打标 2/2 · p95 4.1s

---

## Week 2 — 卡片渲染 + 双场景演练 + Demo 彩排

### 卡片渲染层
- [x] 实现 4 套企微卡片模板（预警 / 工单 / 回执 / 越界红标）→ `src/wecom/cards.py`
- [x] `WecomClient` Protocol + `DryRunWecomClient`（按钮信息 metadata 化，真实推送 v0.5 接入）
- [x] `ScanRunner` 自动渲染卡片，`ScanResult.cards` 含成品
- [x] CLI `--render-cards` 离线预览 markdown
- [ ] 实现 `✅ 同意` 按钮回调 → 自动生成工单卡片（依赖真实企微推送）
- [ ] 实现 `❌ 稍后` 按钮 → 4 小时后再推（依赖真实企微推送）
- [x] 实现 `💬 改方案` 文字反馈 → 单轮重生成 → `ScanRunner.revise_for_batch` + CLI `--revise-batch / --feedback`（越界自动走红标卡）

### 双场景验收
- [ ] 客户 A：3 张卡片跑通（虾仁 / 鱼糜 / 越界改方案）
- [ ] 客户 B：3 张卡片跑通（盒饭馅料 / 调理品 / 越界改方案）
- [ ] 工单回执流程跑通（车间主任 "已完成" 回执）
- [x] 改方案单轮重生成跑通，含越界场景红标（CLI + ScanRunner + KIMI 验证脚本三重覆盖）

### Demo 现场准备
- [x] 内部 Demo 演讲稿成稿 → [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
- [x] 演前 30 分钟操作 runbook → [RUNBOOK_DEMO.md](RUNBOOK_DEMO.md)
- [x] 离线兜底卡片样本 → `make demo` → `docs/demo_samples/customer{A,B}.md`
- [x] 兜底视频分镜脚本 → [FALLBACK_VIDEO.md](FALLBACK_VIDEO.md)（待真人录制）
- [ ] Demo 演讲稿内部彩排 ≥ 2 次（需主讲 + 见证者）
- [ ] **Demo 失败兜底视频**实际录制（2 分钟，按分镜脚本）
- [x] FAQ 8 题熟记 → DEMO_SCRIPT §FAQ
- [ ] 现场角色分工确定（主讲 / 技术 / 见证）
- [x] 现场设备清单 → RUNBOOK_DEMO §1.5

---

## 额外完成（不在原 TODO 但实际做了）

**CI/CD 基础设施**：
- [x] git init + GitHub 远程 `apaqyang/Shelf-Life-Copilot`
- [x] GitHub Actions CI（lint + test 3.11/3.12 矩阵 + coverage artifact）
- [x] README badges（CI / Python / ruff / License）
- [x] pre-commit 配置（ruff + mypy + trailing-whitespace / merge-conflict / detect-private-key 等）
- [x] Makefile：`install / dev / test / lint / fmt / check / run / scan / clean`

**CLI 入口**：
- [x] `python -m src.cli --customer X [--today YYYY-MM-DD] [--dry-run] [--render-cards]`
- [x] `make scan CUSTOMER=customerA TODAY=2026-05-26 DRY=1`

**架构文档**：
- [x] `README.md` 项目入口与导航
- [x] `docs/ARCHITECTURE.md` 分层 / 依赖图 / sequence diagram / 设计决策

**销售工具**：
- [x] [PRD.md §12.1](PRD.md) 年损快速诊断问卷（8 题）+ v1.0 报价分档

---

## 验收标准（全部 ✅ 才算 Demo 就绪）

详见 [PRD.md §8.3](PRD.md)：

- [ ] 能向企微群推送 1 条临期预警卡片
- [ ] 卡片中"建议动作"由 LLM 实时生成（非硬编码）
- [ ] 点击 `✅ 同意` 后可见工单回执
- [ ] 客户 A、客户 B 两套场景的卡片样式 / 文案均跑通
- [ ] 内部模拟总监场景跑完整 5 分钟无冷场
- [ ] 至少 1 位非项目成员（如朋友 / 老婆 / 同行）能在不看脚本时听懂

---

## 阻塞 & 风险（每日同步）

- [ ] **企微管理员 API 权限申请进度** — 决定 Week 2 卡片层能否开工
- [ ] **Anthropic API 配额** — 接好后即可跑"5+ 真实场景"验证
- [ ] **客户 A、B 真实可用动作清单** — 销售按 [PRD §12.1](PRD.md) 问卷调研后回填到 `data/config/`
- [ ] **Demo 时间约定** — 线下 / 视频会议

---

## 后置任务（v0.5+，留位不展开）

- [ ] 对接客户真实 ERP / WMS（SAP / 用友 / 金蝶 / 自研）
- [x] 月度 PDF 报告**生成器**已完成（mock 数据驱动）→ `src/reports/` + `make report`
- [x] 月度 PDF 报告**自动定时** → `MonthlyReportScheduler`（每月 1 号 08:00 Asia/Shanghai · cron 业务/调度分层）+ `make monthly [PUSH=1]` 手动触发 + 摘要卡推送企微
- [x] 决策日志持久化（SQLite）→ `src/persistence/DecisionStore` + CLI `--record-decision`；v0.5+ 迁 PostgreSQL 只换 store 实现
- [ ] 多租户配置后台
- [ ] 私有化部署方案
- [ ] 跨批次联合优化（v1.5）
- [ ] 日志结构化（JSON logging + correlation id）
- [ ] Prompt caching（评估 5-min TTL 命中率）
