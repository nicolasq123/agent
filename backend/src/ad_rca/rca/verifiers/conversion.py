from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import HypothesisResult
from ad_rca.rca.verifiers.base import VerificationContext, make_evidence, unknown_result


class ConversionPathVerifier:
    hypothesis = HypothesisType.CONVERSION_PATH_FAILURE

    def verify(self, context: VerificationContext) -> HypothesisResult:
        failures = tuple(event for event in context.postbacks if event.status_code >= 400)
        cvr_drop = (
            context.current.cvr is not None
            and context.baseline.cvr is not None
            and context.current.cvr < context.baseline.cvr * 0.8
        )
        if not failures and not cvr_drop:
            return unknown_result(context, self.hypothesis)
        loss = min(abs(context.decomposition.efficiency_effect), context.attribution.lost_profit)
        power = loss / context.attribution.lost_profit if context.attribution.lost_profit else 0.0
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.DIRECT if failures else EvidenceStrength.CORROBORATING,
            context=context,
            dataset="postbacks",
            record_ids=tuple(event.record_id for event in failures),
            statement="Conversion delivery degraded during the incident",
            formula="conversion_efficiency_loss",
            inputs={"failed_postbacks": float(len(failures))},
            explained_loss=loss,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.CONFIRMED if failures and power >= 0.8 else Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=loss,
            explanatory_power=min(power, 1.0),
            evidence=(evidence,),
        )
