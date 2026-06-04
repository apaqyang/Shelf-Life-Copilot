<!--
平台：V2EX · `分享创造` 节点
受众：泛技术开发者 / 行业 IT
钩子定位：开源 + Docker 一键 + 食品行业垂直（区别于通用 AI 工具）
字数：标题 30 字 / 正文 ~430 字
-->

# 标题（≤ 40 字符）

```
开源了个食品厂临期管理 AI 副驾，Docker 一键能跑
```

（字符数：30）

---

# 帖子正文

一家年产值 5 亿的冷冻食品厂，去年报损 150 万。

不是没有 ERP，不是没有人盯，是**总监每天早上要从 3 个微信群里翻消息，做出 3-5 个处置决策，平均花 25 分钟**。等他翻完群、做完决策、转给车间，已经过了 1-3 天。在这 1-3 天里，本来还能转加工的虾仁，就变成只能打折清仓的虾仁了。

我做了个开源工具来解决这个问题：[Shelf-Life Copilot](https://github.com/apaqyang/Shelf-Life-Copilot)。

逻辑很简单：

- 早 7:00 自动扫库存，按剩余保质期分 YELLOW / ORANGE / RED 三档
- LLM 在客户预先启用的动作集里选处置方案（转加工 / 打折清仓 / 员工食堂 / 调拨分厂），越界自动红标，不会盲跑
- 6 张企微卡片直送总监手机，一键 ✅ 同意 / ❌ 稍后 / 💬 改方案
- 同意自动派工单给车间主任，全程留决策日志
- 月底一份 PDF 报告，节省总额 + ROI + 最佳动作，老板看完决定续不续费

技术栈是 Python 3.11 / FastAPI lifespan + APScheduler / SQLite 持久化决策日志 / LLM provider 抽象（offline / KIMI / Claude 任选）。AGPL-3.0，内部使用怎么改都行；做 SaaS 对外卖才触发开源条款。

5 分钟自己跑：

```bash
git clone https://github.com/apaqyang/Shelf-Life-Copilot.git
cd Shelf-Life-Copilot
docker compose up
# 新开终端
docker compose exec app uv run python -m src.cli \
  --customer customerA --today 2026-06-04 --provider offline --render-cards
```

offline 模式不需要任何 API key，能看到 6 张企微卡片渲染样本。

3 个月 PoC mock 数据：决策延迟从 1.8 天压到 < 1 小时，月度报损金额下降 38%，PDF 口径 ROI 3.8×（销售口径 4-6×，差异是 89% 采纳率折扣，文档里写明白了）。

求 star 求拍砖，特别想听听做过 LLM action-space 约束 / 企微自建应用回调 AES 加解密的同学的建议。第一篇案例拆解博文也写好了：[150 万年损是怎么飞掉的](https://github.com/apaqyang/Shelf-Life-Copilot/blob/main/docs/blog/2026-06-04-150wan-loss-decoded.md)。
