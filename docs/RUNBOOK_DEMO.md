# RUNBOOK — Demo 演前 30 分钟操作手册

> 用途：把 [DEMO_SCRIPT.md](DEMO_SCRIPT.md) 的"说话"和**实际命令**绑在一起。
> 适用：现场 / 远程视频 demo · 内部彩排 · 断网兜底
> 配套：[DEMO_SCRIPT.md](DEMO_SCRIPT.md) · [demo_samples/](demo_samples/) · [PRD §8.3](PRD.md)

---

## 0. 三层 demo 方案（按风险递减）

| 层 | 命令 | 何时用 | 依赖 |
|---|---|---|---|
| **A. 全链路实战** | `ANTHROPIC_API_KEY=sk-... make scan CUSTOMER=customerA TODAY=2026-05-26` 后续接企微推送 | 网络 + API key + 企微 群 全部就位 | 全部 |
| **B. LLM 实时 + 终端预览** | `ANTHROPIC_API_KEY=sk-... uv run python -m src.cli --customer customerA --today 2026-05-26 --render-cards` | 企微未就位 / 网络不稳定 | 仅 Anthropic API |
| **C. 离线兜底** | `make demo` → 打开 `docs/demo_samples/customerA.md` | 断网 / API 故障 | 无 |

**核心原则**：现场任何卡顿 ≥ 5 秒，立刻降一层。绝不在客户面前调代码。

---

## 1. 演前 30 分钟逐项 checklist

### 1.1 环境验证（T-30 min）

```bash
# 1. 项目目录、分支干净
cd /data/我的应用开发目录/食品行业保质期\ 临期\ AI
git status   # 期望: working tree clean, on main

# 2. 全套检查全绿（CI 等效）
make check   # 期望: 144 passed · 100% coverage

# 3. 离线 demo 样本能重新生成
make demo
ls docs/demo_samples/   # 期望: customerA.md  customerB.md
```

**任何一项失败 → 立刻退到 C 层（用已签入仓库的 demo_samples）**。

### 1.2 LLM 端到端 smoke（T-20 min）

```bash
export ANTHROPIC_API_KEY=sk-...   # 用 demo 专用 key，不要把生产 key 暴露给客户
uv run python -m src.cli --customer customerA --today 2026-05-26 --render-cards | tee /tmp/smoke_A.log
uv run python -m src.cli --customer customerB --today 2026-05-26 --render-cards | tee /tmp/smoke_B.log
```

逐项核对：
- [ ] customerA 输出 6 条 alert（A-001..A-007 减去 A-004）
- [ ] customerA suggestion 数量等于 alert 数（错误数 = 0）
- [ ] customerB 输出 5 条 alert
- [ ] 卡片 markdown 全部含 `转加工`/`打折清仓`/`员工食堂` 这类 industry phrase，**不含**裸的 `transform`/`discount_clearance`
- [ ] 没有任何 Python 堆栈 trace

### 1.3 企微链路（T-15 min，若 B 层就位）

- [ ] 测试群机器人 webhook 在线，发一句 "ping" 收到
- [ ] 决策人 userid 在 `data/config/customerA.actions.json` 与企微通讯录一致
- [ ] 真机 + 大屏镜像线连好，亮度调到最大

### 1.4 兜底素材（T-10 min）

- [ ] `docs/demo_samples/customerA.md`、`customerB.md` 用 markdown 阅读器 / VSCode 打开预览，全屏可读
- [ ] 备用 2 分钟视频在桌面 / 手机 / U 盘各放一份（见 [FALLBACK_VIDEO.md](FALLBACK_VIDEO.md)）
- [ ] 卡片里的客户名、品类、年损金额、年批次数 **已替换成对方厂的真实信息**

### 1.5 现场设备清单（T-5 min）

| 项 | 数量 | 备份 |
|---|---|---|
| 演示笔记本 | 1 | 电池满，电源带上 |
| 演示手机（企微登录） | 1 | 充电宝 |
| 4G 热点（手机 / 独立 mifi） | 1 | 不依赖会议室 WiFi |
| HDMI / Type-C 镜像线 | 1 | 带转接头 |
| 印刷版 DEMO_SCRIPT（A4 双面） | 2 份 | 主讲 + 见证各一 |

---

## 2. 演中操作速查（不要在台上翻文档，把这里抄到手机便签）

| 时间点 | 该做的事 | 命令 / 动作 |
|---|---|---|
| 0:00 | 开场钩子，递手机给总监 | — |
| 0:30 | 一句话产品定义 | — |
| 1:00 | **触发首张卡片** | A 层：在跑好的脚本里点回车 / B 层：`uv run ... --render-cards` |
| 1:30 | 念卡片字段（每条停 1 秒） | 照 DEMO_SCRIPT §1:00-3:00 |
| 2:30 | 让总监点 ✅ 同意 | A 层卡片回执自动弹出 / B 层口述 + 打开 demo_samples 第 4 节工单卡片 |
| 3:00 | 触发"改方案" | A 层：在企微输入框输入 / B 层：打开 demo_samples 第 2 节 |
| 4:00 | 价值回扣（180 批次 × 60% × 5000 = ¥54 万） | 照 DEMO_SCRIPT §4:00-4:45 |
| 4:45 | 收口问句 "您觉得这个逻辑对吗？" | 停顿 2 秒等回应 |

---

## 3. 故障应急流程（Decision Tree）

```
卡片不弹出？
├── < 5 秒：保持沉默，盯屏幕（客户感知 = 思考）
└── ≥ 5 秒：立刻说 "网络问题，我把刚才视频发到您群里"
            └── 降到 C 层，打开 docs/demo_samples/customer{A,B}.md
                继续按 DEMO_SCRIPT 念，不打断节奏

LLM 报错 / 数字不对？
└── 主讲说 "我让技术同事确认一下，先把后面流程走完"
    └── 技术不在场也不要现场打开终端，按 demo_samples 静态版本继续

总监打断 → 见 DEMO_SCRIPT §FAQ Q1-Q8

总监要看代码 / 部署细节？
└── "这部分细节我让我们 CTO 单独跟您 IT 同事对一次"
    （绝不现场承诺技术细节）
```

---

## 4. 演后 5 分钟（趁热做完）

```bash
# 1. 把这次 demo 的实际命令、报错、反馈记到 log
echo "$(date -Iseconds) | customer=$NAME | feedback=$VERBATIM" >> .demo_log.txt

# 2. 立即截图 / 录屏存档（手机相册 + 桌面）

# 3. 把对方关键反对意见同步给销售 / 实施
```

**不要**：演后立刻发"感谢 X 总抽空"客套消息——24 小时内发**ROI 一页纸 + 试点合作 PDF** 才有信号。

---

## 5. 彩排核对（≥ 2 次）

### 彩排 #1 目标：自己一个人跑完 5 分钟，不超时
- [ ] 计时器 ≤ 5:30
- [ ] 念卡片字段时每条**真的停了 1 秒**（容易快）
- [ ] 价值回扣那段数字背得出来
- [ ] FAQ 8 题随机抽 3 题能直接回答

### 彩排 #2 目标：找一位非项目成员当总监
- [ ] 对方能在不看脚本时**复述产品定义**
- [ ] 对方能挑出至少 1 个反对意见 → 演练对应 FAQ
- [ ] 对方在收口时给出 "对 / 不对" 明确表态

**两次都过 → 真演时主讲信心 +50%。**

---

*维护人：（待填）* · *上次彩排：（待填）* · *上次实战：（待填）*
