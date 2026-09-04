from ad_rca.domain.enums import HypothesisType
from ad_rca.rca.verifiers.base import VerificationContext


def generate_candidates(context: VerificationContext) -> tuple[HypothesisType, ...]:
    candidates: list[HypothesisType] = []
    for change in context.config_changes:
        if change.field_name == "payout_per_conversion" and change.new_value > change.old_value:
            candidates.append(HypothesisType.PAYOUT_PRICE_INCREASE)
        if change.field_name == "revenue_per_conversion" and change.new_value < change.old_value:
            candidates.append(HypothesisType.REVENUE_PRICE_DECREASE)
    current_payout_rate = _rate(context.current.payout, context.current.conversions)
    baseline_payout_rate = _rate(context.baseline.payout, context.baseline.conversions)
    if _increased_materially(current_payout_rate, baseline_payout_rate):
        candidates.append(HypothesisType.PAYOUT_PRICE_INCREASE)
    current_revenue_rate = _rate(context.current.revenue, context.current.conversions)
    baseline_revenue_rate = _rate(context.baseline.revenue, context.baseline.conversions)
    if _decreased_materially(current_revenue_rate, baseline_revenue_rate):
        candidates.append(HypothesisType.REVENUE_PRICE_DECREASE)
    if any(cap.hit for cap in context.caps):
        candidates.append(HypothesisType.CAP_REACHED)
    if context.current.clicks < context.baseline.clicks * 0.8:
        candidates.append(HypothesisType.TRAFFIC_VOLUME_DROP)
    if context.decomposition.mix_effect < 0:
        candidates.append(HypothesisType.TRAFFIC_MIX_SHIFT)
    if any(event.status_code >= 400 for event in context.postbacks) or _ratio_drop(
        context.current.cvr, context.baseline.cvr
    ):
        candidates.append(HypothesisType.CONVERSION_PATH_FAILURE)
    if any(event.signal_value >= 0.2 for event in context.quality_events):
        candidates.append(HypothesisType.TRAFFIC_QUALITY_DEGRADATION)
    return tuple(dict.fromkeys(candidates))


def _ratio_drop(current: float | None, baseline: float | None) -> bool:
    return current is not None and baseline is not None and current < baseline * 0.8


def _rate(value: float, conversions: int) -> float | None:
    return value / conversions if conversions > 0 else None


def _increased_materially(current: float | None, baseline: float | None) -> bool:
    return (
        current is not None
        and baseline is not None
        and baseline > 0
        and current >= baseline * 1.2
    )


def _decreased_materially(current: float | None, baseline: float | None) -> bool:
    return (
        current is not None
        and baseline is not None
        and baseline > 0
        and current <= baseline * 0.8
    )
