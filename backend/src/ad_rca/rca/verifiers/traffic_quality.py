from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import HypothesisResult
from ad_rca.rca.verifiers.base import VerificationContext, make_evidence, unknown_result


class TrafficQualityVerifier:
    hypothesis = HypothesisType.TRAFFIC_QUALITY_DEGRADATION

    def verify(self, context: VerificationContext) -> HypothesisResult:
        signals = tuple(event for event in context.quality_events if event.signal_value >= 0.2)
        if not signals:
            return unknown_result(context, self.hypothesis)
        loss = min(abs(context.decomposition.efficiency_effect), context.attribution.lost_profit)
        power = loss / context.attribution.lost_profit if context.attribution.lost_profit else 0.0
        direct = any(event.adjudicated for event in signals)
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.DIRECT if direct else EvidenceStrength.CORROBORATING,
            context=context,
            dataset="quality_events",
            record_ids=tuple(event.record_id for event in signals),
            statement="Traffic-quality indicators exceeded their allowed thresholds",
            formula="quality_correlated_efficiency_loss",
            inputs={event.signal_type: event.signal_value for event in signals},
            explained_loss=loss,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.CONFIRMED if direct else Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=loss,
            explanatory_power=min(power, 1.0),
            evidence=(evidence,),
        )
