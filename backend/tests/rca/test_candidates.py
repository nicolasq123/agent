from datetime import UTC, datetime

from ad_rca.domain.enums import HypothesisType, IncidentType
from ad_rca.domain.models import (
    AttributionResult,
    CapObservation,
    ConfigChange,
    Incident,
    MetricSnapshot,
    QualityEvent,
    SliceKey,
    TimeWindow,
)
from ad_rca.rca.candidates import generate_candidates
from ad_rca.rca.decomposition import EffectDecomposition
from ad_rca.rca.verifiers.base import VerificationContext

NOW = datetime(2026, 9, 2, 10, tzinfo=UTC)
SLICE = SliceKey(offer_id="offer-a", channel_id="channel-c", country="US")


def context_fixture() -> VerificationContext:
    incident = Incident(
        incident_id="inc-1",
        incident_type=IncidentType.PROFIT_DROP,
        scope=SliceKey(),
        window=TimeWindow(start=NOW, end=NOW.replace(hour=11)),
        actual_profit=200.0,
        expected_profit=1000.0,
        lost_profit=800.0,
        drop_ratio=0.8,
        robust_z=-5.0,
        triggered_windows=2,
        data_completeness=1.0,
    )
    return VerificationContext(
        incident=incident,
        affected_slice=SLICE,
        current=MetricSnapshot.from_totals(
            clicks=1000, conversions=100, approved_conversions=60, revenue=1000.0, payout=800.0
        ),
        baseline=MetricSnapshot.from_totals(
            clicks=1000, conversions=100, approved_conversions=90, revenue=1000.0, payout=200.0
        ),
        attribution=AttributionResult(
            slice_key=SLICE,
            actual_profit=200.0,
            expected_profit=800.0,
            lost_profit=600.0,
            share=0.75,
        ),
        decomposition=EffectDecomposition(
            total_change=-600.0,
            volume_effect=0.0,
            mix_effect=-300.0,
            efficiency_effect=-300.0,
            residual=0.0,
        ),
        config_changes=(
            ConfigChange(
                record_id="change-1",
                event_time=NOW,
                entity_type="offer",
                entity_id="offer-a",
                field_name="payout_per_conversion",
                old_value=2.0,
                new_value=8.0,
            ),
        ),
        caps=(
            CapObservation(
                record_id="cap-1", event_time=NOW, offer_id="offer-a", limit=100, used=100, hit=True
            ),
        ),
        quality_events=(
            QualityEvent(
                record_id="quality-1",
                event_time=NOW,
                channel_id="channel-c",
                signal_type="short_ctit_rate",
                signal_value=0.3,
                adjudicated=False,
            ),
        ),
    )


def test_candidate_generation_is_stable_and_deduplicated() -> None:
    result = generate_candidates(context_fixture())

    assert result == (
        HypothesisType.PAYOUT_PRICE_INCREASE,
        HypothesisType.CAP_REACHED,
        HypothesisType.TRAFFIC_MIX_SHIFT,
        HypothesisType.TRAFFIC_QUALITY_DEGRADATION,
    )
