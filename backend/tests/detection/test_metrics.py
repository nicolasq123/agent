from datetime import UTC, datetime
from math import isclose

from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.models import PerformanceRow


def _row(*, clicks: int, conversions: int, revenue: float, payout: float) -> PerformanceRow:
    return PerformanceRow(
        event_hour=datetime(2026, 9, 2, 10, tzinfo=UTC),
        advertiser_id="adv-1",
        offer_id="offer-a",
        channel_id="channel-c",
        country="US",
        clicks=clicks,
        conversions=conversions,
        approved_conversions=conversions,
        revenue=revenue,
        payout=payout,
    )


def test_aggregate_metrics_recomputes_ratios_from_totals() -> None:
    result = aggregate_metrics(
        (
            _row(clicks=10, conversions=5, revenue=20.0, payout=10.0),
            _row(clicks=90, conversions=5, revenue=80.0, payout=40.0),
        )
    )

    assert result.clicks == 100
    assert result.conversions == 10
    assert isclose(result.profit, 50.0)
    assert result.cvr is not None and isclose(result.cvr, 0.1)
    assert result.epc is not None and isclose(result.epc, 1.0)


def test_aggregate_metrics_returns_zero_snapshot_for_empty_input() -> None:
    result = aggregate_metrics(())

    assert result.clicks == 0
    assert result.profit == 0.0
    assert result.margin is None
