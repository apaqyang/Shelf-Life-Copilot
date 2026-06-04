<!--
平台：GitHub Releases
事件：v0.2 内容营销启动 · 首篇博文发布
字数：~180 字
-->

# v0.2 · 内容营销启动 · 首篇案例博文发布

随着 v0.1 工程交付完成（391 测试 / 100% 覆盖 / CI 全绿），我们启动内容营销冷启动。本次 release 主要内容是**首篇行业案例博文**，工程层面只是文档增量，不影响 v0.1 部署的现网行为。

## 本次更新

- 📝 **首篇案例博文**：[150 万年损是怎么飞掉的——一家冷冻食品厂的临期管理实录](https://github.com/apaqyang/Shelf-Life-Copilot/blob/main/docs/blog/2026-06-04-150wan-loss-decoded.md)（约 2500 字，含 4 类损失拆解 + 3 个月 PoC 对比数据表 + 商业模式说明）
- 📦 **7 平台推广素材包**：`docs/blog/promotion/` 目录，含 V2EX / 即刻 / 公众号 / 行业杂志 / 微信群 / Release Notes 6 种平台的差异化文案版本
- 📚 **博客索引页**：`docs/blog/README.md`，后续文章入口
- 🛠️ **工程无破坏性变更**：v0.2 与 v0.1 二进制兼容，不需要重启服务

## 试用入口（仍是 5 分钟）

```bash
git clone https://github.com/apaqyang/Shelf-Life-Copilot.git
cd Shelf-Life-Copilot
docker compose up
docker compose exec app uv run python -m src.cli \
  --customer customerA --today 2026-06-04 --provider offline --render-cards
```

offline 模式不需要任何 API key。看到 6 张企微卡片即跑通。

## 下一步路线图

- v0.3：第二篇博文（"AGPL 食品厂能用吗" FAQ 深度版）
- v0.4：英文版 README + HackerNews Show HN 候选
- v0.5：ERP 对接插件骨架（SAP / 用友 / 金蝶任选其一作为首发）

如果博文对你有帮助，欢迎 star 仓库 / 留言案例 / 推荐给厂里 IT 同事。
