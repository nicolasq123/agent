from datetime import UTC, datetime, timedelta

import pytest

from ad_rca.detection.quality import DataQualityStatus, assess_data_quality
from ad_rca.domain.models import PerformanceRow

START = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _row(hour_offset: int, clicks: int = 100) -> PerformanceRow:
    return PerformanceRow(
        event_hour=START + timedelta(hours=hour_offset),
        advertiser_id="adv-1",
        offer_id="offer-a",
        channel_id="channel-c",
        country="US",
        clicks=clicks,
        conversions=10,
        approved_conversions=9,
        revenue=90.0,
        payout=50.0,
    )


def test_quality_rejects_incomplete_windows_before_sample_size() -> None:
    result = assess_data_quality((_row(0, clicks=1),), expected_hours=2, minimum_clicks=100)

    assert result.status is DataQualityStatus.INCOMPLETE
    assert result.completeness == 0.5
    assert "completeness_below_95_percent" in result.reasons


def test_quality_rejects_insufficient_click_sample() -> None:
    result = assess_data_quality((_row(0, clicks=10),), expected_hours=1, minimum_clicks=100)

    assert result.status is DataQualityStatus.INSUFFICIENT_SAMPLE
    assert result.completeness == 1.0


def test_quality_accepts_complete_sufficient_data() -> None:
    result = assess_data_quality((_row(0), _row(1)), expected_hours=2, minimum_clicks=100)

    assert result.status is DataQualityStatus.PASS
    assert result.reasons == ()


def test_quality_rejects_non_positive_expected_hours() -> None:
    with pytest.raises(ValueError, match="expected_hours must be positive"):
        assess_data_quality((_row(0),), expected_hours=0, minimum_clicks=100)
