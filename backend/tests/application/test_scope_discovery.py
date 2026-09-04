from datetime import UTC, datetime, timedelta

import pytest

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.application.scope_discovery import (
    NoAnalyzableDataError,
    discover_scope,
)
from ad_rca.domain.models import PerformanceRow, SliceKey, TimeWindow

START = datetime(2026, 9, 3, 10, tzinfo=UTC)


def _intent() -> AnalysisIntent:
    return AnalysisIntent(
        question="昨天利润为什么下降",
        window=TimeWindow(start=START, end=START + timedelta(hours=1)),
        timezone="UTC",
    )


def _series(dimension: str, value: str, loss: float) -> tuple[PerformanceRow, ...]:
    def row(event_hour: datetime, profit: float) -> PerformanceRow:
        dimensions = {
            "advertiser_id": "__all__",
            "offer_id": "__all__",
            "channel_id": "__all__",
            "country": "__all__",
        }
        dimensions[dimension] = value
        return PerformanceRow(
            event_hour=event_hour,
            advertiser_id=dimensions["advertiser_id"],
            offer_id=dimensions["offer_id"],
            channel_id=dimensions["channel_id"],
            country=dimensions["country"],
            clicks=100,
            conversions=10,
            approved_conversions=0,
            revenue=1000,
            payout=100,
        )

    history = tuple(row(START - timedelta(weeks=week), 0) for week in range(1, 5))
    current = row(START, 0).model_copy(update={"payout": 100 + loss})
    return history + (current,)


def test_discovery_selects_the_largest_loss_dimension() -> None:
    result = discover_scope(
        intent=_intent(),
        rows_by_dimension={
            "offer_id": _series("offer_id", "12345", loss=900),
            "channel_id": _series("channel_id", "678", loss=300),
            "advertiser_id": (),
            "country": (),
        },
    )

    assert result.selected_scope == SliceKey(offer_id="12345")
    assert result.lost_profit == 900
    assert result.source_dimension == "offer_id"


def test_discovery_uses_stable_dimension_tie_breaking() -> None:
    result = discover_scope(
        intent=_intent(),
        rows_by_dimension={
            "offer_id": _series("offer_id", "1", loss=500),
            "advertiser_id": _series("advertiser_id", "2", loss=500),
            "channel_id": (),
            "country": (),
        },
    )

    assert result.selected_scope == SliceKey(advertiser_id="2")


def test_discovery_rejects_candidates_without_four_history_slots() -> None:
    rows = _series("offer_id", "12345", loss=900)

    with pytest.raises(NoAnalyzableDataError):
        discover_scope(
            intent=_intent(),
            rows_by_dimension={"offer_id": rows[-4:]},
        )
