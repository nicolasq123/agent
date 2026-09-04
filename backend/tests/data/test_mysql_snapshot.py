from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.data.mysql_snapshot import MySqlSnapshotLoader
from ad_rca.domain.models import SliceKey, TimeWindow

START = datetime(2026, 9, 3, 10, tzinfo=UTC)


class RecordingReader:
    def __init__(self, responses: Mapping[str, tuple[Mapping[str, object], ...]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.checked = False

    async def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        self.calls.append((name, parameters))
        return self.responses.get(name, ())

    async def check(self) -> None:
        self.checked = True


def _intent(scope: SliceKey | None = None) -> AnalysisIntent:
    return AnalysisIntent(
        question="分析昨天利润下降",
        window=TimeWindow(start=START, end=START + timedelta(hours=1)),
        scope=scope or SliceKey(),
        timezone="UTC",
    )


def _performance_row(event_hour: datetime) -> Mapping[str, object]:
    return {
        "event_hour": event_hour.replace(tzinfo=None),
        "advertiser_id": 9,
        "offer_id": 12345,
        "channel_id": 678,
        "country": "US",
        "clk_os": 2,
        "carrier": 1,
        "clicks": 100,
        "invalid_clicks": 2,
        "conversions": 10,
        "settled_conversions": 8,
        "revenue": 1000,
        "payout": 100,
    }


def _series_rows(value: object, loss: float) -> tuple[Mapping[str, object], ...]:
    history = tuple(
        {
            "event_hour": (START - timedelta(weeks=week)).replace(tzinfo=None),
            "dimension_value": value,
            "clicks": 100,
            "conversions": 10,
            "revenue": 1000,
            "payout": 100,
        }
        for week in range(1, 5)
    )
    return history + (
        {
            "event_hour": START.replace(tzinfo=None),
            "dimension_value": value,
            "clicks": 100,
            "conversions": 10,
            "revenue": 1000,
            "payout": 100 + loss,
        },
    )


@pytest.mark.anyio
async def test_loader_uses_user_scope_without_discovery() -> None:
    stat = RecordingReader({"performance_scoped": (_performance_row(START),)})
    config = RecordingReader({})
    loader = MySqlSnapshotLoader(stat, config, stat_timezone="UTC")

    snapshot = await loader.load(_intent(SliceKey(offer_id="12345")))

    assert [name for name, _ in stat.calls] == ["performance_scoped"]
    assert snapshot.selected_scope == SliceKey(offer_id="12345")
    performance = snapshot.repository.all_performance()
    assert performance[0].event_hour == START
    assert performance[0].settled_conversions == 8
    assert performance[0].approved_conversions == 0
    assert [name for name, _ in config.calls] == [
        "settlement",
        "margin",
        "cap_observations",
        "routing_changes",
    ]


@pytest.mark.anyio
async def test_loader_discovers_scope_with_bounded_fixed_queries() -> None:
    candidate_names = {
        "scope_candidates_by_advertiser": 9,
        "scope_candidates_by_offer": 12345,
        "scope_candidates_by_channel": 678,
        "scope_candidates_by_country": "US",
    }
    responses: dict[str, tuple[Mapping[str, object], ...]] = {
        name: ({"dimension_value": value},) for name, value in candidate_names.items()
    }
    responses.update(
        {
            "performance_by_advertiser": _series_rows(9, 100),
            "performance_by_offer": _series_rows(12345, 900),
            "performance_by_channel": _series_rows(678, 300),
            "performance_by_country": _series_rows("US", 200),
            "performance_scoped": (_performance_row(START),),
        }
    )
    stat = RecordingReader(responses)
    config = RecordingReader({})
    loader = MySqlSnapshotLoader(stat, config, stat_timezone="UTC")

    snapshot = await loader.load(_intent())

    assert snapshot.selected_scope == SliceKey(offer_id="12345")
    assert len(stat.calls) == 9
    assert len(config.calls) == 4
    assert len(stat.calls) + len(config.calls) == 13
    offer_parameters = dict(stat.calls)["performance_by_offer"]
    assert offer_parameters["value_1"] == 12345
    assert tuple(offer_parameters[f"value_{index}"] for index in range(2, 7)) == (
        -1,
        -1,
        -1,
        -1,
        -1,
    )


@pytest.mark.anyio
async def test_loader_check_checks_both_sources() -> None:
    stat = RecordingReader({})
    config = RecordingReader({})
    loader = MySqlSnapshotLoader(stat, config, stat_timezone="UTC")

    await loader.check()

    assert stat.checked is True
    assert config.checked is True


@pytest.mark.anyio
async def test_loader_accepts_mysql_decimal_aggregates() -> None:
    row = dict(_performance_row(START))
    row["clicks"] = Decimal("100")
    row["conversions"] = Decimal("10")
    row["settled_conversions"] = Decimal("8")
    row["revenue"] = Decimal("1000.25")
    stat = RecordingReader({"performance_scoped": (row,)})
    loader = MySqlSnapshotLoader(stat, RecordingReader({}), stat_timezone="UTC")

    snapshot = await loader.load(_intent(SliceKey(country="US")))

    mapped = snapshot.repository.all_performance()[0]
    assert mapped.clicks == 100
    assert mapped.revenue == 1000.25
