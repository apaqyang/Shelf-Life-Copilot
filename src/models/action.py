"""Action types — the closed set of safe disposal actions for near-expiry batches."""

from __future__ import annotations

from enum import StrEnum


class ActionType(StrEnum):
    """Safe-action vocabulary. Enabled subset is per-customer (see CustomerConfig)."""

    TRANSFORM = "transform"  # 转加工为下游产品
    DISCOUNT_CLEARANCE = "discount_clearance"  # 打折清仓
    EMPLOYEE_CANTEEN = "employee_canteen"  # 转员工食堂 / 关联企业消化
    TRANSFER_WAREHOUSE = "transfer_warehouse"  # 调拨至需求更急的分厂
    REPORT_LOSS = "report_loss"  # 报损（最后兜底）
