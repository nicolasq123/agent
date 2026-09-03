from hashlib import sha256
from typing import Protocol

from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import (
    AttributionResult,
    CapObservation,
    ConfigChange,
    Evidence,
    EvidenceCalculation,
    EvidenceSource,
    HypothesisResult,
    Incident,
    MetricSnapshot,
    PostbackEvent,
    QualityEvent,
    RoutingChange,
    SliceKey,
    StrictModel,
)
from ad_rca.rca.decomposition import EffectDecomposition


class VerificationContext(StrictModel):
    incident: Incident
    affected_slice: SliceKey
    current: MetricSnapshot
    baseline: MetricSnapshot
    attribution: AttributionResult
    decomposition: EffectDecomposition
    config_changes: tuple[ConfigChange, ...] = ()
    caps: tuple[CapObservation, ...] = ()
    postbacks: tuple[PostbackEvent, ...] = ()
    quality_events: tuple[QualityEvent, ...] = ()
    routing_changes: tuple[RoutingChange, ...] = ()


class Verifier(Protocol):
    hypothesis: HypothesisType

    def verify(self, context: VerificationContext) -> HypothesisResult: ...


def unknown_result(context: VerificationContext, hypothesis: HypothesisType) -> HypothesisResult:
    return HypothesisResult(
        hypothesis=hypothesis,
        status=HypothesisStatus.UNKNOWN,
        confidence=Confidence.INSUFFICIENT_EVIDENCE,
        affected_slice=context.affected_slice,
        explained_loss=0.0,
        explanatory_power=0.0,
    )


def make_evidence(
    *,
    hypothesis: HypothesisType,
    strength: EvidenceStrength,
    context: VerificationContext,
    dataset: str,
    record_ids: tuple[str, ...],
    statement: str,
    formula: str,
    inputs: dict[str, float],
    explained_loss: float,
) -> Evidence:
    dimensions = context.affected_slice.dimensions()
    slice_identity = tuple(f"{name}={value}" for name, value in dimensions)
    identity = "|".join((hypothesis, dataset, *record_ids, formula, *slice_identity))
    evidence_id = f"ev-{sha256(identity.encode()).hexdigest()[:16]}"
    return Evidence(
        evidence_id=evidence_id,
        hypothesis=hypothesis,
        strength=strength,
        observed_at=context.incident.window.start,
        source=EvidenceSource(system="fixture", dataset=dataset, record_ids=record_ids),
        statement=statement,
        calculation=EvidenceCalculation(
            formula=formula,
            inputs=inputs,
            explained_loss=explained_loss,
        ),
    )
