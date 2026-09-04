from datetime import UTC, datetime, timedelta

from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.enums import Confidence, HypothesisType, RunStatus
from ad_rca.domain.models import (
    ConfigChange,
    PerformanceRow,
    ScenarioBundle,
    ScenarioMetadata,
    SliceKey,
    TimeWindow,
)

START = datetime(2026, 9, 2, 10, tzinfo=UTC)


def _row(event_hour: datetime, profit: float) -> PerformanceRow:
    return PerformanceRow(
        event_hour=event_hour,
        advertiser_id="adv-1",
        offer_id="offer-a",
        channel_id="channel-c",
        country="US",
        clicks=1000,
        conversions=100,
        approved_conversions=90,
        revenue=1000.0,
        payout=1000.0 - profit,
    )


def _repository(current_profit: float) -> FixtureRepository:
    history = tuple(
        _row(START + timedelta(hours=hour) - timedelta(weeks=week), 400.0)
        for hour in range(3)
        for week in range(1, 9)
    )
    current = tuple(_row(START + timedelta(hours=hour), current_profit) for hour in range(3))
    change = ConfigChange(
        record_id="change-1",
        event_time=START - timedelta(minutes=15),
        entity_type="offer",
        entity_id="offer-a",
        field_name="payout_per_conversion",
        old_value=6.0,
        new_value=9.0,
    )
    bundle = ScenarioBundle(
        metadata=ScenarioMetadata(scenario_id="pricing", name="Pricing error", timezone="UTC"),
        performance=history + current,
        config_changes=(change,),
    )
    return FixtureRepository(bundle)


def test_core_service_confirms_pricing_incident_with_cited_evidence() -> None:
    service = CoreRcaService(_repository(100.0), default_verifiers())

    result = service.investigate("pricing")

    assert result.status is RunStatus.COMPLETED
    assert result.incident is not None
    assert result.hypotheses[0].hypothesis is HypothesisType.PAYOUT_PRICE_INCREASE
    assert result.hypotheses[0].confidence is Confidence.CONFIRMED
    assert result.hypotheses[0].evidence
    assert {item.evidence_id for item in result.evidence} == {
        item.evidence_id for hypothesis in result.hypotheses for item in hypothesis.evidence
    }


def test_core_service_returns_completed_without_false_incident() -> None:
    service = CoreRcaService(_repository(400.0), default_verifiers())

    result = service.investigate("pricing")

    assert result.status is RunStatus.COMPLETED
    assert result.incident is None
    assert result.hypotheses == ()


def test_core_service_uses_explicit_window_and_scope() -> None:
    window = TimeWindow(start=START, end=START + timedelta(hours=2))
    scope = SliceKey(offer_id="offer-a")
    service = CoreRcaService(
        _repository(100.0),
        default_verifiers(),
        analysis_window=window,
        base_scope=scope,
    )

    prepared = service.prepare("pricing")

    assert prepared.incident is not None
    assert prepared.incident.window == window
    assert prepared.incident.scope == scope


def test_core_service_keeps_last_three_hour_default() -> None:
    prepared = CoreRcaService(_repository(100.0), default_verifiers()).prepare("pricing")

    assert prepared.incident is not None
    assert prepared.incident.window == TimeWindow(start=START, end=START + timedelta(hours=3))
