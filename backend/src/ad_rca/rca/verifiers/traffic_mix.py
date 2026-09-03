from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import HypothesisResult
from ad_rca.rca.verifiers.base import VerificationContext, make_evidence, unknown_result


class TrafficMixVerifier:
    hypothesis = HypothesisType.TRAFFIC_MIX_SHIFT

    def verify(self, context: VerificationContext) -> HypothesisResult:
        if context.decomposition.mix_effect >= 0:
            return unknown_result(context, self.hypothesis)
        loss = min(abs(context.decomposition.mix_effect), context.attribution.lost_profit)
        power = loss / context.attribution.lost_profit if context.attribution.lost_profit else 0.0
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.CORROBORATING,
            context=context,
            dataset="performance",
            record_ids=(),
            statement="Traffic share moved toward lower-margin slices",
            formula="additive_mix_effect",
            inputs={"mix_effect": context.decomposition.mix_effect},
            explained_loss=loss,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=loss,
            explanatory_power=min(power, 1.0),
            evidence=(evidence,),
        )
