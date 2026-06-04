# MARKETING · 内容营销 SOP

> 借鉴 NocoBase 模式：把销售 funnel 从"销售上门 demo"前移到"自助搜索 + 自助试用"。
> 这份文档是**你和销售自己看的操作手册**，不发布给客户。

---

## 🎯 目标 funnel

```
食品行业从业者搜关键词
    ↓ （SEO / 内容）
落到本仓库 GitHub README
    ↓ （README 5 分钟试用 CTA）
docker compose up 自己跑通
    ↓ （体验到价值）
make qualify 自己出 ROI PDF
    ↓ （产生付费意向）
联系销售谈商业版 PoC
```

每一步漏斗都要 measurable：
- 搜索 → GitHub 进入：GitHub Insights Traffic
- README → docker compose up：靠 PR 留言 / Issue / 私信问起
- qualify 跑通 → 联系：销售台账人工统计

---

## 🔑 关键词清单（按搜索意图分组）

按食品行业从业者**真实搜索习惯**整理。优先攻 A 组（高意图、长尾、竞争少）。

### A. 高意图长尾关键词（首选）

| 关键词 | 月搜索量估算 | 搜索者画像 |
|---|---|---|
| 临期管理 | 200-500 | 食品厂供应链 / 采购 |
| 食品报损率 | 100-300 | 总监 / CFO |
| 冷冻原料损耗 | 50-100 | 冷冻食品厂 |
| 食品库存 AI | 100-200 | IT / 数字化转型负责人 |
| 企微临期提醒 | 30-80 | 企微管理员 |
| 食品行业 AI 落地 | 200-400 | CIO / 战略部 |
| 食品厂 ERP 临期 | 50-150 | IT / 实施工程师 |
| 月度报损报告模板 | 30-80 | 财务 / 总监 |

### B. 行业通用词（需要长内容才能竞争得过）

| 关键词 | 月搜索量估算 | 竞争激烈度 |
|---|---|---|
| 食品供应链管理 | 1000+ | 高 |
| 库存优化 | 500+ | 高 |
| 制造业 AI | 800+ | 高 |
| SaaS 临期 | 100-200 | 中 |

### C. 长尾问句类（适合写在 QUICKSTART FAQ）

- "食品厂 ERP 报表为什么搞不定临期"
- "冷冻食品报损率多少正常"
- "企业微信怎么对接 AI"
- "PoC 试点 SOW 模板 食品"
- "AGPL 开源软件食品厂能用吗"

---

## 📢 渠道推广清单

按"成本 vs 触达精度"排序。所有渠道都不需要预算，只需要时间。

### 🥇 Tier 1：高精度 / 低成本（必做）

| 渠道 | 怎么推 | 节奏 |
|---|---|---|
| **GitHub README + Topics** | About 描述塞 3 个核心关键词；Topics 选：`food-industry`, `expiry-management`, `wecom`, `ai`, `mes`, `inventory`, `loss-prevention` | 一次性配置 |
| **食品工业杂志 / 中国食品工业** | 投稿《150 万年损是怎么飞掉的》改写版（删 GitHub 链接，留邮箱 / 微信号） | 每季度 1 篇 |
| **微信公众号"食品 + 数字化"垂直号** | 留言互动 / 引用文章 / 投稿 | 每月 2-3 次 |
| **食品行业垂直微信群**（找朋友拉进） | 群里发博文链接 + 简短摘要；不要硬推 | 每篇博文发布时 |

### 🥈 Tier 2：泛技术开发者（顺手做）

| 渠道 | 怎么推 | 节奏 |
|---|---|---|
| **V2EX `创意`/`程序员`/`分享创造`** | 发"我做了一个食品厂临期管理开源 AI 副驾"，强调开源 + Docker 一键 | 仓库 star 破 100 时发首贴 |
| **即刻** | 个人时间线发"3 个月，14 人团队，AGPL 开源" | 每月 1-2 条 |
| **少数派 / 掘金** | 技术深度文：架构设计 / LLM provider 抽象 / FastAPI lifespan 调度 | 季度 1 篇 |
| **GitHub Trending** | 不主动 push，靠真实 stars。一旦上 trending，复制 V2EX 截图分发 | 被动 |

### 🥉 Tier 3：等仓库有真实客户后再做

| 渠道 | 怎么推 |
|---|---|
| **行业大会 / 展会**（FHC、Sial、糖酒会） | 邀请客户站台，不自费搭展 |
| **YouTube / B 站演示视频** | 用 [FALLBACK_VIDEO.md](FALLBACK_VIDEO.md) 分镜脚本录制 |
| **HackerNews `Show HN`** | 英文版 README + 英文博文 + 完整 docker quickstart |

---

## ⚙️ GitHub 仓库配置（手动操作清单）

仓库根目录改不了的部分，登 GitHub 网页操作：

### 1. About 描述（仓库右上角 ⚙️ Edit repository details）

```
食品行业临期 / 保质期管理 AI 副驾 · 企微卡片直送总监一键决策 · AGPL-3.0 开源
```

确保含 4 个关键词：**食品 / 临期 / 企微 / 开源**。

### 2. Website URL

填仓库自己的：`https://github.com/apaqyang/Shelf-Life-Copilot/blob/main/README.md`
（之后有自建博客域名再换）

### 3. Topics（点击 About 旁的 ⚙️ Topics）

按优先级填 10 个（GitHub 限制 20 个）：

```
food-industry
expiry-management
inventory-management
loss-prevention
wecom
fastapi
llm
ai-agent
open-core
agpl
```

### 4. 仓库 Pin（个人首页 GitHub.com/apaqyang 右上）

把 `Shelf-Life-Copilot` Pin 到个人首页 6 个 Pinned 仓库的第一位。

### 5. README 顶部 Badge（已加）

| Badge | 用途 |
|---|---|
| `license-AGPL--3.0-blue` | 标明开源协议 |
| `python-3.11/3.12-blue` | 技术栈 |
| `coverage-100%` | 工程质量 |
| `tests-400+` | 工程量 |

---

## 📅 内容节奏建议

**前 3 个月（冷启动期）**：
- 每月 1-2 篇深度博文（A 类 + C 类各 1 篇）
- GitHub Topics 全配置 + README 顶部优化
- 每月在 1-2 个 Tier 1 渠道发分发版本

**3-6 个月（看反应期）**：
- 看 GitHub Insights Traffic 找出 inbound 来源
- 哪个关键词带流量大，写 follow-up 文章深耕
- 累积到 5-8 篇博文形成"内容库"，新访客有的读

**6 个月后（决策期）**：
- 如果 inbound > 100 unique visitors / 月：升级到 MkDocs Material + 自有域名 + Algolia 搜索
- 如果 inbound < 30：内容没起来，砍掉博客，重新评估市场选择

---

## 🚫 不该做的

- ❌ **付费搜索引擎广告**（百度 / Google Ads）— 食品行业 IT 主管不点广告，纯烧钱
- ❌ **B2B 数据库买名单冷邮件** — 总监防爆通讯录的程度比你想象高
- ❌ **写"功能列表"软文** — 客户看了就走，写故事 + 数据 + 诚实
- ❌ **隐藏开源协议** — AGPL 是卖点不是 liability，明说就行
- ❌ **承诺 PoC 第一个月就出 ROI** — 食品厂数据沉淀慢，给客户预期 3 个月

---

*回到 → [博客主页](blog/README.md)*  ·  *项目主 README → [/README.md](../README.md)*
