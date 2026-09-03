from ad_rca.domain.enums import Confidence, EvidenceStrength, HypothesisStatus, HypothesisType
from ad_rca.domain.models import HypothesisResult
from ad_rca.rca.verifiers.base import VerificationContext, make_evidence, unknown_result


class PricingVerifier:
    hypothesis = HypothesisType.PAYOUT_PRICE_INCREASE

    def verify(self, context: VerificationContext) -> HypothesisResult:
        changes = tuple(
            change
            for change in context.config_changes
            if change.field_name == "payout_per_conversion"
            and change.new_value > change.old_value
            and (
                context.affected_slice.offer_id is None
                or change.entity_id == context.affected_slice.offer_id
            )
        )
        if not changes:
            return unknown_result(context, self.hypothesis)
        change = changes[-1]
        recomputed = min(
            (change.new_value - change.old_value) * context.current.conversions,
            context.attribution.lost_profit,
        )
        power = _explanatory_power(recomputed, context.attribution.lost_profit)
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.DIRECT,
            context=context,
            dataset="config_changes",
            record_ids=tuple(item.record_id for item in changes),
            statement="Payout per conversion increased before the incident",
            formula="(new_payout-old_payout)*conversions",
            inputs={
                "old_payout": change.old_value,
                "new_payout": change.new_value,
                "conversions": float(context.current.conversions),
            },
            explained_loss=recomputed,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.CONFIRMED if power >= 0.8 else Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=recomputed,
            explanatory_power=min(power, 1.0),
            evidence=(evidence,),
        )


class RevenuePriceVerifier:
    hypothesis = HypothesisType.REVENUE_PRICE_DECREASE

    def verify(self, context: VerificationContext) -> HypothesisResult:
        changes = tuple(
            change
            for change in context.config_changes
            if change.field_name == "revenue_per_conversion"
            and change.new_value < change.old_value
            and (
                context.affected_slice.offer_id is None
                or change.entity_id == context.affected_slice.offer_id
            )
        )
        if not changes:
            return unknown_result(context, self.hypothesis)
        change = changes[-1]
        recomputed = min(
            (change.old_value - change.new_value) * context.current.conversions,
            context.attribution.lost_profit,
        )
        power = _explanatory_power(recomputed, context.attribution.lost_profit)
        evidence = make_evidence(
            hypothesis=self.hypothesis,
            strength=EvidenceStrength.DIRECT,
            context=context,
            dataset="config_changes",
            record_ids=tuple(item.record_id for item in changes),
            statement="Revenue per conversion decreased before the incident",
            formula="(old_revenue-new_revenue)*conversions",
            inputs={
                "old_revenue": change.old_value,
                "new_revenue": change.new_value,
                "conversions": float(context.current.conversions),
            },
            explained_loss=recomputed,
        )
        return HypothesisResult(
            hypothesis=self.hypothesis,
            status=HypothesisStatus.SUPPORTED,
            confidence=Confidence.CONFIRMED if power >= 0.8 else Confidence.LIKELY,
            affected_slice=context.affected_slice,
            explained_loss=recomputed,
            explanatory_power=min(power, 1.0),
            evidence=(evidence,),
        )


def _explanatory_power(explained_loss: float, attributed_loss: float) -> float:
    return explained_loss / attributed_loss if attributed_loss else 0.0
