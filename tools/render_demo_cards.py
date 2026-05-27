"""Offline demo card renderer — produces deterministic markdown for rehearsal / fallback.

Why this is a tool, not a CLI flag:
- It bakes in DEMO_SCRIPT.md's exact phrasing for the suggestion text (so the
  cards on stage match what the presenter is reading).
- It does not call Claude. It does not need an API key. It does not touch WeCom.
- Output is committed to docs/demo_samples/ — print it out, open it on a backup
  laptop, screenshot it for a fallback video.

Run with:
    uv run python tools/render_demo_cards.py
    # or: make demo
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Allow running as a script from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.alerts import scan_batch
from src.models import (
    ActionType,
    Alert,
    Batch,
    CustomerConfig,
    Suggestion,
)
from src.repository import load_batches, load_customer_config
from src.wecom import (
    render_card_for_alert,
    render_out_of_scope_card,
    render_receipt_card,
    render_work_order_card,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "demo_samples"
DEMO_TODAY = date(2026, 5, 26)


@dataclass(frozen=True)
class DemoScenario:
    """One customer's demo storyboard — feeds into a deterministic markdown."""

    customer_id: str
    headline_batch_id: str  # which batch the presenter narrates
    primary_suggestion: Suggestion
    revised_suggestion: Suggestion  # after "改方案" feedback
    out_of_scope_suggestion: Suggestion  # presenter pretends to ask for a banned action
    foreman_userid: str
    actual_completion_qty: float


# ---------------------------------------------------------------------------
# Customer A — frozen seafood plant (年损 150 万)
# ---------------------------------------------------------------------------

_CUSTOMER_A = DemoScenario(
    customer_id="customerA",
    headline_batch_id="A-001",
    primary_suggestion=Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.TRANSFORM,
        savings_estimate=8500.0,
        rationale="历史同期同类原料在 15-20 天剩余时转加工，报损率下降约 40%。",
        confidence=0.85,
        is_standard=True,
        llm_model="claude-sonnet-4-6",
    ),
    revised_suggestion=Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.DISCOUNT_CLEARANCE,
        savings_estimate=6200.0,
        rationale="清仓渠道吸收率 75%、单价折让约 30%，避免占用虾饺线产能。",
        confidence=0.78,
        is_standard=True,
        llm_model="claude-haiku-4-5",
        user_feedback="虾饺线满了，能不能改成打折清仓",
    ),
    out_of_scope_suggestion=Suggestion(
        batch_id="A-001",
        customer_id="customerA",
        action=ActionType.EMPLOYEE_CANTEEN,  # disabled for customerA
        savings_estimate=1500.0,
        rationale="转员工食堂 / 关联企业内部消化，单价折让较大但可即时出货。",
        confidence=0.55,
        is_standard=False,
        llm_model="claude-haiku-4-5",
        user_feedback="送给关联食堂内部消化掉",
    ),
    foreman_userid="wecom_userid_workshop_zhang",
    actual_completion_qty=830.0,
)

# ---------------------------------------------------------------------------
# Customer B — ready-to-eat meal plant (年损 86 万)
# ---------------------------------------------------------------------------

_CUSTOMER_B = DemoScenario(
    customer_id="customerB",
    headline_batch_id="B-001",
    primary_suggestion=Suggestion(
        batch_id="B-001",
        customer_id="customerB",
        action=ActionType.EMPLOYEE_CANTEEN,
        savings_estimate=2400.0,
        rationale="同类批次剩余 < 7 天时员工食堂消化成功率 92%，单批可全量出清。",
        confidence=0.88,
        is_standard=True,
        llm_model="claude-sonnet-4-6",
    ),
    revised_suggestion=Suggestion(
        batch_id="B-001",
        customer_id="customerB",
        action=ActionType.DISCOUNT_CLEARANCE,
        savings_estimate=1800.0,
        rationale="B2B 餐饮配送渠道吸收率 70%、可在 48h 内出货。",
        confidence=0.74,
        is_standard=True,
        llm_model="claude-haiku-4-5",
        user_feedback="食堂这周菜单已锁定，改打折清仓",
    ),
    out_of_scope_suggestion=Suggestion(
        batch_id="B-001",
        customer_id="customerB",
        action=ActionType.TRANSFER_WAREHOUSE,  # disabled for customerB
        savings_estimate=900.0,
        rationale="临时调拨至需求更急的分厂，需冷链与跨厂结算配合。",
        confidence=0.50,
        is_standard=False,
        llm_model="claude-haiku-4-5",
        user_feedback="能不能临时调拨给分厂",
    ),
    foreman_userid="wecom_userid_canteen_li",
    actual_completion_qty=200.0,
)


def _find(batches: list[Batch], batch_id: str) -> Batch:
    for b in batches:
        if b.batch_id == batch_id:
            return b
    raise KeyError(f"batch {batch_id} not found in mock data")


def _require_alert(batch: Batch, config: CustomerConfig) -> Alert:
    alert = scan_batch(batch, config.alert_thresholds, today=DEMO_TODAY)
    if alert is None:
        raise RuntimeError(
            f"batch {batch.batch_id} is healthy on {DEMO_TODAY}; pick a different headline"
        )
    return alert


def render_customer(scenario: DemoScenario) -> str:
    """Render the 4 demo cards for one customer into one markdown document."""
    config = load_customer_config(scenario.customer_id)
    batches = load_batches(scenario.customer_id)
    batch = _find(batches, scenario.headline_batch_id)
    alert = _require_alert(batch, config)

    primary_card = render_card_for_alert(batch, alert, scenario.primary_suggestion, config)
    revised_card = render_card_for_alert(batch, alert, scenario.revised_suggestion, config)
    out_of_scope_card = render_out_of_scope_card(
        batch, alert, scenario.out_of_scope_suggestion, config
    )
    work_order_card = render_work_order_card(
        batch,
        scenario.primary_suggestion,
        config,
        foreman_userids=[scenario.foreman_userid],
        due_date=date(DEMO_TODAY.year, DEMO_TODAY.month, DEMO_TODAY.day + 2),
    )
    receipt_card = render_receipt_card(
        batch, scenario.primary_suggestion, actual_qty=scenario.actual_completion_qty
    )

    sections: list[str] = [
        f"# Demo 样本 — {scenario.customer_id} (假设今天 = {DEMO_TODAY.isoformat()})",
        "",
        "> 离线渲染，无 LLM、无企微推送。彩排照念即可；现场断网时这份就是兜底材料。",
        "> 重新生成：`make demo`",
        "",
        "---",
        "",
        f"## 1. 预警卡片（headline batch = {scenario.headline_batch_id}）",
        "",
        primary_card.markdown,
        "",
        "**主讲台词**：参见 [DEMO_SCRIPT.md](../DEMO_SCRIPT.md) §1:00-3:00。",
        "",
        "---",
        "",
        '## 2. "改方案" 单轮重生成（标准动作）',
        f"_用户反馈：{scenario.revised_suggestion.user_feedback}_",
        "",
        revised_card.markdown,
        "",
        "---",
        "",
        '## 3. "改方案" 越界场景（红标兜底）',
        f"_用户反馈：{scenario.out_of_scope_suggestion.user_feedback}_",
        "",
        out_of_scope_card.markdown,
        "",
        "> 主讲应对台词：『超出标准动作集，我们后台运营会人工复核一次再下工单，不会盲跑。』",
        "",
        "---",
        "",
        "## 4. 同意后的工单卡片（@车间主任）",
        "",
        work_order_card.markdown,
        "",
        "---",
        "",
        "## 5. 工单完成回执",
        "",
        receipt_card.markdown,
        "",
    ]
    return "\n".join(sections)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in (_CUSTOMER_A, _CUSTOMER_B):
        out = OUTPUT_DIR / f"{scenario.customer_id}.md"
        out.write_text(render_customer(scenario), encoding="utf-8")
        print(f"wrote {out.relative_to(OUTPUT_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
