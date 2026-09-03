from datetime import UTC, datetime, timedelta

from ad_rca.detection.detector import DetectionConfig, detect_incident
from ad_rca.domain.enums import IncidentType, RunStatus
from ad_rca.domain.models import PerformanceRow

START = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _row(event_hour: datetime, profit: float, clicks: int = 100) -> PerformanceRow:
    return PerformanceRow(
        event_hour=event_hour,
        advertiser_id="adv-1",
        offer_id="offer-a",
        channel_id="channel-c",
        country="US",
        clicks=clicks,
        conversions=20,
        approved_conversions=18,
        revenue=200.0,
        payout=200.0 - profit,
    )


def _current(profits: tuple[float, ...]) -> tuple[PerformanceRow, ...]:
    return tuple(
        _row(START + timedelta(hours=index), profit) for index, profit in enumerate(profits)
    )


def _history(baseline_profit: float = 100.0) -> tuple[PerformanceRow, ...]:
    return tuple(
        _row(START + timedelta(hours=hour) - timedelta(weeks=week), baseline_profit)
        for hour in range(3)
        for week in range(1, 9)
    )


def _config() -> DetectionConfig:
    return DetectionConfig(
        deviation_floor=1.0,
        minimum_absolute_loss=40.0,
        minimum_clicks=100,
        baseline_profit_floor=20.0,
    )


def test_detects_profit_drop_when_two_of_three_windows_trigger() -> None:
    result = detect_incident(_current((50.0, 50.0, 100.0)), _history(), _config())

    assert result.status is RunStatus.COMPLETED
    assert result.incident is not None
    assert result.incident.incident_type is IncidentType.PROFIT_DROP
    assert result.incident.triggered_windows == 2
    assert result.incident.lost_profit == 100.0


def test_ignores_single_noisy_window() -> None:
    result = detect_incident(_current((50.0, 100.0, 100.0)), _history(), _config())

    assert result.incident is None


def test_ignores_statistically_large_but_low_impact_drop() -> None:
    config = _config().model_copy(update={"minimum_absolute_loss": 20.0})

    result = detect_incident(_current((90.0, 90.0, 100.0)), _history(), config)

    assert result.incident is None


def test_near_zero_baseline_does_not_create_relative_profit_drop() -> None:
    result = detect_incident(_current((-50.0, -50.0, 0.0)), _history(0.0), _config())

    assert result.incident is not None
    assert result.incident.incident_type is IncidentType.NEGATIVE_PROFIT


def test_incomplete_current_windows_block_detection() -> None:
    result = detect_incident(_current((50.0, 50.0)), _history(), _config())

    assert result.status is RunStatus.DATA_QUALITY_BLOCKED
    assert result.incident is None


def test_absolute_loss_threshold_applies_to_the_whole_incident() -> None:
    config = _config().model_copy(update={"minimum_absolute_loss": 500.0})

    result = detect_incident(_current((-200.0, -200.0, 100.0)), _history(), config)

    assert result.incident is not None
    assert result.incident.incident_type is IncidentType.PROFIT_DROP
    assert result.incident.lost_profit == 600.0
