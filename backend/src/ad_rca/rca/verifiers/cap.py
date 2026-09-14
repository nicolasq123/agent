from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import HypothesisResult
from ad_rca.rca.verifiers.base import VerificationContext, make_evidence, unknown_result


class CapVerifier:
    hypothesis = HypothesisType.CAP_REACHED

    def verify(self, context: VerificationContext) -> HypothesisResult:
        hits = tuple(
            cap
            for cap in context.caps
            if cap.hit
            and (
                context.affected_slice.offer_id is None
                or cap.offer_id == context.affected_slice.offer_id
            )
        )
        if not hits:
            return unknown_result(context, self.hypothesis)
        loss = 0.0
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.DIRECT,
            context=context,
            dataset="caps",
            record_ids=tuple(hit.record_id for hit in hits),
            statement="Offer reached its configured cap during the incident",
            formula="cap_hit_observed_loss_not_quantified",
            inputs={"used": float(hits[-1].used), "limit": float(hits[-1].limit)},
            explained_loss=loss,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=loss,
            explanatory_power=0.0,
            evidence=(evidence,),
        )
