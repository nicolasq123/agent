from datetime import UTC, datetime
from math import isclose

from ad_rca.domain.models import PerformanceRow, SliceKey
from ad_rca.rca.contribution import attribute_loss

HOUR = datetime(2026, 9, 2, 10, tzinfo=UTC)
DIMENSIONS = ("advertiser_id", "offer_id", "channel_id", "country")


def _row(
    advertiser: str,
    offer: str,
    channel: str,
    country: str,
    profit: float,
) -> PerformanceRow:
    return PerformanceRow(
        event_hour=HOUR,
        advertiser_id=advertiser,
        offer_id=offer,
        channel_id=channel,
        country=country,
        clicks=100,
        conversions=20,
        approved_conversions=18,
        revenue=1000.0,
        payout=1000.0 - profit,
    )


def test_attributes_loss_to_most_specific_non_overlapping_paths() -> None:
    expected = (
        _row("adv-1", "offer-a", "channel-c", "US", 620.0),
        _row("adv-1", "offer-b", "channel-d", "CA", 210.0),
        _row("adv-2", "offer-c", "channel-e", "GB", 170.0),
    )
    actual = (
        _row("adv-1", "offer-a", "channel-c", "US", 0.0),
        _row("adv-1", "offer-b", "channel-d", "CA", 0.0),
        _row("adv-2", "offer-c", "channel-e", "GB", 0.0),
    )

    summary = attribute_loss(actual, expected, DIMENSIONS, max_depth=3, min_share=0.10)

    assert summary.paths[0].slice_key == SliceKey(
        offer_id="offer-a", channel_id="channel-c", country="US"
    )
    assert isclose(summary.paths[0].share, 0.62)
    assert isclose(sum(path.lost_profit for path in summary.paths), 1000.0)
    assert isclose(summary.residual_loss, 0.0)


def test_attribution_prunes_small_contributors_into_residual() -> None:
    expected = (
        _row("adv-1", "offer-a", "channel-a", "US", 95.0),
        _row("adv-2", "offer-b", "channel-b", "CA", 5.0),
    )
    actual = (
        _row("adv-1", "offer-a", "channel-a", "US", 0.0),
        _row("adv-2", "offer-b", "channel-b", "CA", 0.0),
    )

    summary = attribute_loss(actual, expected, DIMENSIONS, max_depth=3, min_share=0.10)

    assert len(summary.paths) == 1
    assert isclose(summary.paths[0].lost_profit, 95.0)
    assert isclose(summary.residual_loss, 5.0)
