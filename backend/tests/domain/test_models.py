from datetime import UTC, datetime, timedelta
from math import isclose

import pytest
from pydantic import ValidationError

from ad_rca.domain.models import MetricSnapshot, SliceKey, TimeWindow


def test_time_window_rejects_timezone_naive_values() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TimeWindow(
            start=datetime(2026, 9, 2, 10),
            end=datetime(2026, 9, 2, 11),
        )


def test_time_window_rejects_non_positive_duration() -> None:
    start = datetime(2026, 9, 2, 10, tzinfo=UTC)

    with pytest.raises(ValidationError, match="start must be before end"):
        TimeWindow(start=start, end=start - timedelta(hours=1))


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SliceKey.model_validate({"offer_id": "offer-a", "unknown_dimension": "value"})


def test_slice_key_reports_only_selected_dimensions() -> None:
    key = SliceKey(offer_id="offer-a", channel_id="channel-c")

    assert key.depth == 2
    assert key.dimensions() == (("offer_id", "offer-a"), ("channel_id", "channel-c"))


def test_metric_snapshot_calculates_derived_metrics_from_totals() -> None:
    snapshot = MetricSnapshot.from_totals(
        clicks=100,
        conversions=20,
        approved_conversions=15,
        revenue=150.0,
        payout=90.0,
    )

    assert isclose(snapshot.profit, 60.0)
    assert snapshot.margin is not None and isclose(snapshot.margin, 0.4)
    assert snapshot.cvr is not None and isclose(snapshot.cvr, 0.2)
    assert snapshot.approval_rate is not None and isclose(snapshot.approval_rate, 0.75)
    assert snapshot.epc is not None and isclose(snapshot.epc, 1.5)
    assert snapshot.cost_per_click is not None and isclose(snapshot.cost_per_click, 0.9)


def test_metric_snapshot_uses_none_for_zero_denominators() -> None:
    snapshot = MetricSnapshot.from_totals(
        clicks=0,
        conversions=0,
        approved_conversions=0,
        revenue=0.0,
        payout=0.0,
    )

    assert snapshot.profit == 0.0
    assert snapshot.margin is None
    assert snapshot.cvr is None
    assert snapshot.approval_rate is None
    assert snapshot.epc is None
    assert snapshot.cost_per_click is None
