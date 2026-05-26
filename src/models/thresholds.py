"""Alert thresholds — day-count cutoffs for severity classification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertThresholds:
    """Day-count thresholds. Convention: days_left <= threshold → that severity.

    Invariant: red < orange < yellow (red is the most urgent, smallest day count).
    """

    yellow: int = 30
    orange: int = 15
    red: int = 7

    def __post_init__(self) -> None:
        if not (self.red < self.orange < self.yellow):
            raise ValueError(
                "Thresholds must satisfy red < orange < yellow; "
                f"got red={self.red}, orange={self.orange}, yellow={self.yellow}"
            )
