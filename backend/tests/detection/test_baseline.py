from datetime import UTC, datetime, timedelta
from math import isclose

import pytest

from ad_rca.detection.baseline import InsufficientHistoryError, build_profit_baseline
from ad_rca.domain.models import PerformanceRow

CURRENT_HOUR = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _profit_row(event_hour: datetime, profit: float) -> PerformanceRow:
    return PerformanceRow(
        event_hour=event_hour,
        advertiser_id="adv-1",
        offer_id="offer-a",
        channel_id="channel-c",
        country="US",
        clicks=100,
        conversions=20,
        approved_conversions=20,
        revenue=200.0,
        payout=200.0 - profit,
    )


def test_baseline_uses_same_weekday_hour_and_resists_outlier() -> None:
    profits = (100.0, 98.0, 102.0, 101.0, 99.0, 100.0, 97.0, 1000.0)
    history = tuple(
        _profit_row(CURRENT_HOUR - timedelta(weeks=index + 1), profit)
        for index, profit in enumerate(profits)
    ) + (_profit_row(CURRENT_HOUR - timedelta(days=1), -500.0),)

    result = build_profit_baseline(
        current_hour=CURRENT_HOUR,
        current_rows=(_profit_row(CURRENT_HOUR, 50.0),),
        history_rows=history,
        deviation_floor=1.0,
    )

    assert isclose(result.expected_profit, 100.0)
    assert result.sample_size == 8
    assert result.robust_z < -3.0


def test_baseline_uses_deviation_floor_when_mad_is_zero() -> None:
    history = tuple(
        _profit_row(CURRENT_HOUR - timedelta(weeks=index + 1), 100.0) for index in range(8)
    )

    result = build_profit_baseline(
        current_hour=CURRENT_HOUR,
        current_rows=(_profit_row(CURRENT_HOUR, 50.0),),
        history_rows=history,
        deviation_floor=10.0,
    )

    assert result.mad_zero is True
    assert isclose(result.robust_z, -3.3725)


def test_baseline_rejects_fewer_than_four_matching_slots() -> None:
    history = tuple(
        _profit_row(CURRENT_HOUR - timedelta(weeks=index + 1), 100.0) for index in range(3)
    )

    with pytest.raises(InsufficientHistoryError, match="at least 4"):
        build_profit_baseline(
            current_hour=CURRENT_HOUR,
            current_rows=(_profit_row(CURRENT_HOUR, 50.0),),
            history_rows=history,
        )
