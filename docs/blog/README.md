# Shelf-Life Copilot 博客

> 食品行业临期管理 / 报损治理 / AI 落地的深度内容。
> 受众：供应链 / 采购 / 生产总监、食品厂 IT 主管、CFO。

---

## 📰 文章列表

| 日期 | 标题 | 主题 |
|---|---|---|
| 2026-06-04 | [150 万年损是怎么飞掉的：一家冷冻食品厂的临期管理实录](2026-06-04-150wan-loss-decoded.md) | 案例拆解 · ROI 测算 |

> *按时间倒序排列。每月 1-2 篇为节奏。*

---

## ✍️ 写作 SOP（团队成员看这里）

### 选题清单

按搜索意图分三类，优先选客户**已经在搜**的关键词组合：

**A. 痛点诊断类**（吸引刚开始意识到痛点的客户）
- 《报损率到底应该多少才算正常？食品行业 5 类细分》
- 《年损 200 万的中型食品厂，问题真的出在仓库吗？》
- 《冷冻原料 vs 预制菜 vs 烘焙：临期管理痛点对比》

**B. 解决方案类**（吸引正在比较工具的客户）
- 《为什么 ERP 临期报表搞不定真实损失：4 个结构性原因》
- 《临期管理 SaaS vs 自建工具 vs 开源 AI：决策树》
- 《企业微信 + AI 如何把决策延迟从 3 天压到 1 秒》

**C. 案例拆解类**（吸引正在评估 ROI 的客户）
- 《150 万年损是怎么飞掉的：冷冻食品厂实录》⭐ 已发
- 《预制菜厂 86 万年损的 3 个月 PoC 数据》
- 《一份月度 PDF 报告救活了我跟老板的复盘会》

每月节奏建议：A 类 1 篇（拓宽） + C 类 0-1 篇（深度）。B 类作为承接，挂在 README 文档导航里。

### 文件命名

```
docs/blog/YYYY-MM-DD-<英文 slug>.md
```

例：`docs/blog/2026-07-15-erp-cant-do-it.md`

### Frontmatter 模板

GitHub 不解析 frontmatter，但搜索引擎会读 HTML 注释里的 meta。所有文章顶部加：

```markdown
<!--
title: 文章标题（≤ 30 中文字 / 60 字符）
description: 摘要（120-160 字符，搜索结果显示用）
keywords: 关键词 1, 关键词 2, 关键词 3
author: Shelf-Life Copilot Team
published: YYYY-MM-DD
-->

# 文章标题

> **TL;DR**：1-2 句核心结论 + 一个 "想跳过细节直接试用 → [链接](../QUICKSTART.md)" CTA

**关键词**：关键词 1 · 关键词 2 · 关键词 3
```

### SEO Checklist

每篇发布前过一遍：

- [ ] 标题里有 1 个核心关键词
- [ ] 前 200 字内出现 2-3 次关键词（自然，别堆砌）
- [ ] 含至少 1 个数据表 / 1 张架构图（ASCII / mermaid）
- [ ] 内链：链到 [QUICKSTART](../QUICKSTART.md) + [PRD](../PRD.md) + 1-2 篇其他博文
- [ ] 末尾 CTA："5 分钟自己跑一下" + `docker compose up`
- [ ] 全文 1500-3000 字。少于 1500 没深度，多于 3000 没人读完

### 写作风格

- **故事化**：开头一个客户场景，不是"功能列表"
- **有数字**：每个论点至少配 1 个具体金额 / 百分比 / 时间
- **有对话**：让总监 / IT 主管 / 车间主任真的"说话"
- **诚实**：写"谁不该用"段，比写"为什么应该用"更建立信任
- **诚实**：销售口径（4-6×）和 PDF 口径（2.4×）的差异要写明，参见首篇博文第 5 节

### 发布流程

```bash
# 1. 写文章
$EDITOR docs/blog/2026-07-15-<slug>.md

# 2. 在 docs/blog/README.md 文章列表加一行

# 3. README.md 顶部 "📚 文档导航" 章节加博客链接（如果是当月旗舰）

# 4. commit + push
git add docs/blog/
git commit -m "docs(blog): 《文章标题》"
git push

# 5. 分发：
#    - GitHub Release notes 简短引用
#    - V2EX / 即刻 / 食品行业垂直公众号 / 朋友圈 — 见 docs/MARKETING.md
```

---

## 📊 内容效果跟踪（手动维护）

每月初看一次 GitHub repo Insights → Traffic：

| 月份 | Unique visitors | Star 增量 | 博客最 popular |
|---|---|---|---|
| 2026-06 | TBD | TBD | 150 万年损实录 |

如果某篇博文 inbound > 50 unique visitors / 月，把它**置顶**到 README。

如果连续 3 个月 inbound < 20 / 月，说明关键词没选对 — 换 selection。

---

*完整营销渠道 + 关键词清单 → [docs/MARKETING.md](../MARKETING.md)*
