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
            return _measured_payout_result(context)
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
            return _measured_revenue_result(context)
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


def _measured_payout_result(context: VerificationContext) -> HypothesisResult:
    old_rate = _rate(context.baseline.payout, context.baseline.conversions)
    new_rate = _rate(context.current.payout, context.current.conversions)
    if old_rate is None or new_rate is None or old_rate <= 0 or new_rate < old_rate * 1.2:
        return unknown_result(context, HypothesisType.PAYOUT_PRICE_INCREASE)
    loss = min(
        (new_rate - old_rate) * context.current.conversions,
        context.attribution.lost_profit,
    )
    return _measured_result(
        context,
        HypothesisType.PAYOUT_PRICE_INCREASE,
        "Measured payout per conversion increased against baseline",
        "(current_payout_rate-baseline_payout_rate)*conversions",
        old_rate,
        new_rate,
        loss,
    )


def _measured_revenue_result(context: VerificationContext) -> HypothesisResult:
    old_rate = _rate(context.baseline.revenue, context.baseline.conversions)
    new_rate = _rate(context.current.revenue, context.current.conversions)
    if old_rate is None or new_rate is None or old_rate <= 0 or new_rate > old_rate * 0.8:
        return unknown_result(context, HypothesisType.REVENUE_PRICE_DECREASE)
    loss = min(
        (old_rate - new_rate) * context.current.conversions,
        context.attribution.lost_profit,
    )
    return _measured_result(
        context,
        HypothesisType.REVENUE_PRICE_DECREASE,
        "Measured revenue per conversion decreased against baseline",
        "(baseline_revenue_rate-current_revenue_rate)*conversions",
        old_rate,
        new_rate,
        loss,
    )


def _measured_result(
    context: VerificationContext,
    hypothesis: HypothesisType,
    statement: str,
    formula: str,
    baseline_rate: float,
    current_rate: float,
    loss: float,
) -> HypothesisResult:
    evidence = make_evidence(
        hypothesis=hypothesis,
        strength=EvidenceStrength.CORROBORATING,
        context=context,
        dataset="performance",
        record_ids=(),
        statement=statement,
        formula=formula,
        inputs={
            "baseline_rate": baseline_rate,
            "current_rate": current_rate,
            "conversions": float(context.current.conversions),
        },
        explained_loss=loss,
    )
    return HypothesisResult(
        hypothesis=hypothesis,
        status=HypothesisStatus.SUPPORTED,
        confidence=Confidence.LIKELY,
        affected_slice=context.affected_slice,
        explained_loss=loss,
        explanatory_power=min(_explanatory_power(loss, context.attribution.lost_profit), 1.0),
        evidence=(evidence,),
    )


def _rate(value: float, conversions: int) -> float | None:
    return value / conversions if conversions > 0 else None
