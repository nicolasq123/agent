from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import ConfigChange, PostbackEvent
from ad_rca.rca.verifiers.cap import CapVerifier
from ad_rca.rca.verifiers.conversion import ConversionPathVerifier
from ad_rca.rca.verifiers.pricing import PricingVerifier, RevenuePriceVerifier
from ad_rca.rca.verifiers.traffic_mix import TrafficMixVerifier
from ad_rca.rca.verifiers.traffic_quality import TrafficQualityVerifier
from ad_rca.rca.verifiers.traffic_volume import TrafficVolumeVerifier
from tests.rca.test_candidates import NOW, context_fixture


def test_pricing_verifier_confirms_recomputed_direct_loss() -> None:
    result = PricingVerifier().verify(context_fixture())

    assert result.hypothesis is HypothesisType.PAYOUT_PRICE_INCREASE
    assert result.status is HypothesisStatus.SUPPORTED
    assert result.confidence is Confidence.CONFIRMED
    assert result.evidence[0].strength is EvidenceStrength.DIRECT
    assert result.explained_loss == 600.0


def test_pricing_verifier_marks_measured_rate_increase_as_likely() -> None:
    context = context_fixture().model_copy(update={"config_changes": ()})

    result = PricingVerifier().verify(context)

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.confidence is Confidence.LIKELY
    assert result.evidence[0].strength is EvidenceStrength.CORROBORATING
    assert result.evidence[0].source.dataset == "performance"


def test_revenue_verifier_marks_measured_rate_decrease_as_likely() -> None:
    base = context_fixture()
    context = base.model_copy(
        update={
            "config_changes": (),
            "current": base.current.model_copy(update={"revenue": 400.0, "payout": 200.0}),
        }
    )

    result = RevenuePriceVerifier().verify(context)

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.confidence is Confidence.LIKELY
    assert result.evidence[0].source.dataset == "performance"


def test_evidence_uses_context_source_system() -> None:
    context = context_fixture().model_copy(update={"source_system": "mysql"})

    result = PricingVerifier().verify(context)

    assert result.evidence[0].source.system == "mysql"


def test_cap_verifier_requires_a_matching_hit() -> None:
    context = context_fixture().model_copy(update={"caps": ()})

    result = CapVerifier().verify(context)

    assert result.status is HypothesisStatus.UNKNOWN
    assert result.confidence is Confidence.INSUFFICIENT_EVIDENCE


def test_mix_verifier_uses_decomposed_loss() -> None:
    result = TrafficMixVerifier().verify(context_fixture())

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.confidence is Confidence.LIKELY
    assert result.explained_loss == 300.0


def test_quality_verifier_cannot_confirm_without_adjudication() -> None:
    result = TrafficQualityVerifier().verify(context_fixture())

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.confidence is Confidence.LIKELY


def test_revenue_price_verifier_recomputes_lost_income() -> None:
    change = ConfigChange(
        record_id="change-revenue",
        event_time=NOW,
        entity_type="offer",
        entity_id="offer-a",
        field_name="revenue_per_conversion",
        old_value=10.0,
        new_value=4.0,
    )
    context = context_fixture().model_copy(update={"config_changes": (change,)})

    result = RevenuePriceVerifier().verify(context)

    assert result.hypothesis is HypothesisType.REVENUE_PRICE_DECREASE
    assert result.explained_loss == 600.0


def test_conversion_verifier_uses_direct_postback_failure() -> None:
    failure = PostbackEvent(
        record_id="postback-failure",
        event_time=NOW,
        advertiser_id="adv-1",
        offer_id="offer-a",
        status_code=500,
        latency_ms=5000,
        error_type="upstream_error",
    )
    context = context_fixture().model_copy(update={"postbacks": (failure,)})

    result = ConversionPathVerifier().verify(context)

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.evidence[0].strength is EvidenceStrength.DIRECT


def test_traffic_volume_verifier_explains_negative_volume_effect() -> None:
    context = context_fixture().model_copy(
        update={
            "current": context_fixture().current.model_copy(update={"clicks": 500}),
            "decomposition": context_fixture().decomposition.model_copy(
                update={"volume_effect": -240.0}
            ),
        }
    )

    result = TrafficVolumeVerifier().verify(context)

    assert result.status is HypothesisStatus.SUPPORTED
    assert result.explained_loss == 240.0
