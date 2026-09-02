from datetime import UTC, datetime
from math import isclose

from ad_rca.domain.models import PerformanceRow
from ad_rca.rca.decomposition import decompose_profit_change

HOUR = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _row(offer: str, clicks: int, profit_per_click: float) -> PerformanceRow:
    profit = clicks * profit_per_click
    return PerformanceRow(
        event_hour=HOUR,
        advertiser_id="adv-1",
        offer_id=offer,
        channel_id="channel-c",
        country="US",
        clicks=clicks,
        conversions=min(clicks, 20),
        approved_conversions=min(clicks, 18),
        revenue=1000.0,
        payout=1000.0 - profit,
    )


def test_decomposes_pure_volume_change() -> None:
    expected = (_row("high", 100, 1.0), _row("low", 100, 1.0))
    actual = (_row("high", 50, 1.0), _row("low", 50, 1.0))

    result = decompose_profit_change(actual, expected)

    assert isclose(result.total_change, -100.0)
    assert isclose(result.volume_effect, -100.0)
    assert isclose(result.mix_effect, 0.0)
    assert isclose(result.efficiency_effect, 0.0)


def test_decomposes_pure_mix_change() -> None:
    expected = (_row("high", 100, 2.0), _row("low", 100, 0.0))
    actual = (_row("high", 50, 2.0), _row("low", 150, 0.0))

    result = decompose_profit_change(actual, expected)

    assert isclose(result.total_change, -100.0)
    assert isclose(result.volume_effect, 0.0)
    assert isclose(result.mix_effect, -100.0)
    assert isclose(result.efficiency_effect, 0.0)


def test_decomposes_pure_efficiency_change_and_reconciles() -> None:
    expected = (_row("high", 100, 2.0), _row("low", 100, 0.0))
    actual = (_row("high", 100, 1.0), _row("low", 100, 0.0))

    result = decompose_profit_change(actual, expected)

    assert isclose(result.total_change, -100.0)
    assert isclose(result.efficiency_effect, -100.0)
    assert isclose(
        result.volume_effect + result.mix_effect + result.efficiency_effect + result.residual,
        result.total_change,
    )
