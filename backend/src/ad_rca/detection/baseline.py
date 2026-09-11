from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

import numpy as np

from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.models import BaselineResult, PerformanceRow


class InsufficientHistoryError(ValueError):
    """Raised when a same-slot baseline cannot be constructed reliably."""


def comparable_history_slots(
    current_hour: datetime,
    history_rows: Sequence[PerformanceRow],
    minimum_slots: int = 4,
) -> tuple[tuple[PerformanceRow, ...], ...]:
    """Prefer same-weekday slots, then fall back to recent same-hour slots."""
    rows_by_hour: dict[datetime, list[PerformanceRow]] = defaultdict(list)
    for row in history_rows:
        if row.event_hour.hour == current_hour.hour:
            rows_by_hour[row.event_hour].append(row)
    slots = tuple(
        tuple(rows)
        for hour, rows in sorted(rows_by_hour.items())
        if hour.weekday() == current_hour.weekday()
    )
    if len(slots) < minimum_slots:
        slots = tuple(tuple(rows) for _, rows in sorted(rows_by_hour.items()))
    return slots if len(slots) >= minimum_slots else ()


def build_profit_baseline(
    *,
    current_hour: datetime,
    current_rows: Sequence[PerformanceRow],
    history_rows: Sequence[PerformanceRow],
    deviation_floor: float = 1.0,
) -> BaselineResult:
    if current_hour.tzinfo is None:
        raise ValueError("current_hour must be timezone-aware")
    if deviation_floor <= 0:
        raise ValueError("deviation_floor must be positive")

    slots = comparable_history_slots(current_hour, history_rows)
    if not slots:
        raise InsufficientHistoryError("at least 4 matching historical slots are required")
    historical_profits = tuple(aggregate_metrics(slot).profit for slot in slots)

    median_profit = float(np.median(historical_profits))
    mad = float(np.median([abs(value - median_profit) for value in historical_profits]))
    actual_profit = aggregate_metrics(current_rows).profit
    robust_z = 0.6745 * (actual_profit - median_profit) / max(mad, deviation_floor)
    return BaselineResult(
        expected_profit=median_profit,
        median_profit=median_profit,
        mad=mad,
        robust_z=robust_z,
        sample_size=len(historical_profits),
        mad_zero=mad == 0.0,
    )
