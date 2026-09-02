from collections import defaultdict
from collections.abc import Sequence

from ad_rca.domain.models import PerformanceRow, StrictModel


class EffectDecomposition(StrictModel):
    total_change: float
    volume_effect: float
    mix_effect: float
    efficiency_effect: float
    residual: float


def decompose_profit_change(
    actual: Sequence[PerformanceRow], expected: Sequence[PerformanceRow]
) -> EffectDecomposition:
    actual_values = _clicks_and_profit(actual)
    expected_values = _clicks_and_profit(expected)
    leaves = set(actual_values) | set(expected_values)
    actual_clicks = sum(value[0] for value in actual_values.values())
    expected_clicks = sum(value[0] for value in expected_values.values())
    actual_profit = sum(value[1] for value in actual_values.values())
    expected_profit = sum(value[1] for value in expected_values.values())
    total_change = actual_profit - expected_profit

    if expected_clicks == 0:
        return EffectDecomposition(
            total_change=total_change,
            volume_effect=0.0,
            mix_effect=0.0,
            efficiency_effect=0.0,
            residual=total_change,
        )

    baseline_average = expected_profit / expected_clicks
    volume_effect = (actual_clicks - expected_clicks) * baseline_average
    mix_effect = 0.0
    efficiency_effect = 0.0
    for leaf in leaves:
        observed_clicks, observed_profit = actual_values.get(leaf, (0, 0.0))
        baseline_clicks, baseline_profit = expected_values.get(leaf, (0, 0.0))
        baseline_ppc = baseline_profit / baseline_clicks if baseline_clicks else 0.0
        observed_ppc = observed_profit / observed_clicks if observed_clicks else baseline_ppc
        observed_share = observed_clicks / actual_clicks if actual_clicks else 0.0
        baseline_share = baseline_clicks / expected_clicks
        mix_effect += actual_clicks * (observed_share - baseline_share) * baseline_ppc
        efficiency_effect += observed_clicks * (observed_ppc - baseline_ppc)

    residual = total_change - volume_effect - mix_effect - efficiency_effect
    return EffectDecomposition(
        total_change=total_change,
        volume_effect=volume_effect,
        mix_effect=mix_effect,
        efficiency_effect=efficiency_effect,
        residual=residual,
    )


def _clicks_and_profit(
    rows: Sequence[PerformanceRow],
) -> dict[tuple[str, str, str, str], tuple[int, float]]:
    clicks: dict[tuple[str, str, str, str], int] = defaultdict(int)
    profits: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for row in rows:
        leaf = (row.advertiser_id, row.offer_id, row.channel_id, row.country)
        clicks[leaf] += row.clicks
        profits[leaf] += row.revenue - row.payout
    return {leaf: (clicks[leaf], profits[leaf]) for leaf in set(clicks) | set(profits)}
