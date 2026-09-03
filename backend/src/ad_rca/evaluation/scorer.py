from pydantic import Field

from ad_rca.domain.enums import Confidence, HypothesisType, IncidentType
from ad_rca.domain.models import CoreInvestigationResult, SliceKey, StrictModel


class GroundTruth(StrictModel):
    scenario_id: str
    incident_type: IncidentType
    expected_slice: SliceKey
    root_cause: HypothesisType
    maximum_confidence: Confidence
    minimum_explanatory_power: float = Field(ge=0, le=1)


class ScenarioScore(StrictModel):
    passed: bool
    incident_match: bool
    slice_match: bool
    root_cause_top1: bool
    root_cause_top3: bool
    confidence_valid: bool
    explanatory_power_valid: bool
    evidence_coverage: float = Field(ge=0, le=1)


def score_result(result: CoreInvestigationResult, truth: GroundTruth) -> ScenarioScore:
    incident_match = (
        result.incident is not None and result.incident.incident_type is truth.incident_type
    )
    slice_match = any(
        _contains(item.slice_key, truth.expected_slice) for item in result.attributions
    )
    root_causes = tuple(item.hypothesis for item in result.hypotheses)
    root_cause_top1 = bool(root_causes) and root_causes[0] is truth.root_cause
    root_cause_top3 = truth.root_cause in root_causes[:3]
    matching = next(
        (item for item in result.hypotheses if item.hypothesis is truth.root_cause), None
    )
    confidence_order = {
        Confidence.INSUFFICIENT_EVIDENCE: 0,
        Confidence.LIKELY: 1,
        Confidence.CONFIRMED: 2,
    }
    confidence_valid = (
        matching is not None
        and confidence_order[matching.confidence] <= confidence_order[truth.maximum_confidence]
    )
    explanatory_power_valid = (
        matching is not None and matching.explanatory_power >= truth.minimum_explanatory_power
    )
    cited = {item.evidence_id for hypothesis in result.hypotheses for item in hypothesis.evidence}
    available = {item.evidence_id for item in result.evidence}
    evidence_coverage = len(cited & available) / len(cited) if cited else 0.0
    passed = all(
        (
            incident_match,
            slice_match,
            root_cause_top1,
            root_cause_top3,
            confidence_valid,
            explanatory_power_valid,
            evidence_coverage == 1.0,
        )
    )
    return ScenarioScore(
        passed=passed,
        incident_match=incident_match,
        slice_match=slice_match,
        root_cause_top1=root_cause_top1,
        root_cause_top3=root_cause_top3,
        confidence_valid=confidence_valid,
        explanatory_power_valid=explanatory_power_valid,
        evidence_coverage=evidence_coverage,
    )


def _contains(actual: SliceKey, expected: SliceKey) -> bool:
    actual_values = dict(actual.dimensions())
    return all(actual_values.get(name) == value for name, value in expected.dimensions())
