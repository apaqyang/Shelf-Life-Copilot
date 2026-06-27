# QUICKSTART · 食品厂 IT 主管 5 分钟试用指南

> 不需要 Anthropic / KIMI API key，不需要企业微信管理员，不需要任何注册。
> 你只需要：一台装了 Docker 的电脑 + 5 分钟。

---

## 🚀 5 步跑通

### 1. 拉代码（30 秒）

```bash
git clone https://github.com/apaqyang/Shelf-Life-Copilot.git
cd Shelf-Life-Copilot
```

### 2. 起服务（2 分钟，首次拉镜像）

```bash
docker compose up
```

看到 `Uvicorn running on http://0.0.0.0:8000` 就成了。

> **首次启动慢是正常的**：拉 `python:3.11-slim` 基础镜像 + 装依赖大概 1-2 分钟，
> 之后启动 < 5 秒。

### 3. 跑一次"假设今天 2026-05-26 的早 7 点扫描"（30 秒）

新开一个终端：

```bash
docker compose exec app uv run python -m src.cli \
  --customer customerA --today 2026-05-26 --provider offline --render-cards
```

你会看到：
- **6 张临期预警**（虾仁、鱼糜、墨鱼等 6 个批次，剩余 -3 到 25 天）
- **6 条 AI 建议**（建议转加工，每条估算节省 ¥8,000）
- **6 张企微卡片 markdown**（直接打开 markdown 阅读器就能看到客户实际会收到的样子）

### 4. 看离线卡片样本 + 月度 PDF 报告（1 分钟）

```bash
docker compose exec app make demo      # 重新渲染示例卡片
docker compose exec app make report    # 生成月度 PDF 报告
```

打开 `docs/demo_samples/` 目录：
- `customerA.md` / `customerB.md` — 完整 5 张卡片的 markdown（预警 / 改方案 / 工单 / 回执 / 越界红标）
- `monthly_report_customerA.pdf` / `monthly_report_customerB.pdf` — 月度报告 PDF（可直接打印 / 转发给老板）

### 5. 想要你自己厂的 ROI 测算？

加微信 **apaqyang**（备注「临期」+ 公司名），做一份 5 分钟年损诊断 +
ROI 一页纸，可直接发给老板。

---

## 🔧 你看完想真用，需要做什么

### 给采购/生产总监推真实预警，需要 3 件事：

1. **真 LLM API key**（让建议比 offline 演示版有针对性）
   - Anthropic Claude（海外）：https://console.anthropic.com
   - 月之暗面 KIMI（国内）：https://platform.moonshot.cn
   - 写到 `.env` 文件，重启 `docker compose`

2. **企业微信群机器人**（让卡片真推到总监手机，**不需要管理员权限**）
   - 桌面端企微 → 任一群右键 → 群机器人 → 添加 → 复制 Webhook URL
   - `export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."`
   - 跑：`docker compose exec app make push CUSTOMER=customerA`

3. **你自己厂的批次数据**（替换 `data/batches/customerA.json` 里的 mock 数据）
   - schema 见 `src/models/batch.py`
   - 简单一点：拷一份 customerA.json，把里面 7 条 mock 批次改成你厂上周的真实数据

完成这 3 步后，你的总监就能在企微里收到真实预警。

---

## ❓ FAQ

### Q1：我厂的库存数据敏感，跑这个会不会被 LLM 拿走？

A: 取决于你的选择：
- **offline 模式（演示用）**：完全本地，不出任何数据
- **KIMI / Claude 模式**：每次 LLM 调用会发送一条**当前批次**的物料名+剩余天数+客户启用动作清单到 LLM 服务，**不发完整库存表**
- **完全私有化**（v0.5+）：会支持本地 LLM（Ollama / Qwen），不出公司网络

仓库里搜 `build_user_prompt` 看实际发送给 LLM 的 prompt 内容。

### Q2：AI 建议靠谱吗？万一让我转加工实际车间根本做不出来？

A: 三层兜底设计：
1. 每个客户启用的动作集合是 `data/config/customer_<id>.actions.json` 配置的 — 你自己决定哪些动作能选
2. LLM 越界（选了你没启用的动作）会被自动打上 `⚠️ 非标准动作 · 需人工复核` 红标
3. 总监能在企微卡片上点 `💬 改方案` 反馈"虾饺线满了能不能改打折清仓"，AI 单轮重生成新方案

你能看到完整的 LLM 决策日志（在 `data/decisions.db`），每条建议都能追溯到原 prompt + LLM 模型版本。

### Q3：跟我厂 ERP（SAP / 用友 / 金蝶）怎么对接？

A: v0.1 还没做 — 当前是从 `data/batches/<customer>.json` 读 mock 数据。
v0.5 商业版会提供按 ERP 收费的对接插件（每家 ERP 一个独立插件）。
你想现在试，可以写一个定时脚本把 ERP 导出的 Excel/CSV 转成 `customerA.json` 格式（schema 见 `src/models/batch.py`）。

### Q4：开源是 AGPL，我厂自己用要不要公开源码？

A: **不需要**。AGPL 的"必须公开"条款只在你把代码作为 SaaS **对外**售卖时触发（§13）。
你内部用、改 prompt、改卡片模板，都不需要把代码公开。

但是如果你打算把这个工具改一改卖给同行食品厂，那就要遵守 AGPL §13。
不愿意？可以加微信 **apaqyang**（备注「临期」+ 公司名）买商业许可。

### Q5：开源版 vs 商业版到底差什么？

| 功能 | 开源版（AGPL-3.0） | 商业版 |
|---|---|---|
| 临期监测 + AI 建议 | ✅ | ✅ |
| 企微群机器人推送 | ✅ | ✅ |
| 决策日志 SQLite | ✅ | ✅ |
| 月度 PDF 报告 + cron | ✅ | ✅ |
| 企微自建应用按钮**真**派单 | — | ✅ (路径 B 加解密插件) |
| ERP 对接（SAP / 用友 / 金蝶 / 自研） | — | ✅ (插件按家收费) |
| 多租户管理后台 | — | ✅ |
| 私有化部署 + 本地 LLM | — | ✅ |
| 7×24 技术支持 | — | ✅ |

### Q6：我能跑成功，但我老板要看 demo，怎么办？

A: 对着 `make demo` 输出的卡片样本 + `docs/demo_samples/` 里的月度 PDF 报告讲就行——
6 张卡片走一遍（预警 → 改方案 → 工单 → 回执）+ 一页纸 ROI 报告。
需要现成的演示脚本 / 兜底视频蓝本，加微信 **apaqyang** 找我要。

---

## 🔁 卡住了？

- 跑不起来：`docker compose logs app` 看错误
- 卡片渲染异常：`make check` 看测试有没有挂
- 还有疑问：GitHub Issues 提一个，或加微信 **apaqyang**

> **设计哲学**：你 5 分钟跑不通，是我们的问题，不是你的问题。
