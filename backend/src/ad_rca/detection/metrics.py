from collections.abc import Sequence
from typing import cast

import polars as pl

from ad_rca.domain.models import MetricSnapshot, PerformanceRow


def aggregate_metrics(rows: Sequence[PerformanceRow]) -> MetricSnapshot:
    if not rows:
        return MetricSnapshot.from_totals(
            clicks=0,
            conversions=0,
            approved_conversions=0,
            revenue=0.0,
            payout=0.0,
        )

    frame = pl.DataFrame(
        {
            "clicks": [row.clicks for row in rows],
            "conversions": [row.conversions for row in rows],
            "approved_conversions": [row.approved_conversions for row in rows],
            "revenue": [row.revenue for row in rows],
            "payout": [row.payout for row in rows],
        }
    )
    raw_totals = frame.select(
        pl.col("clicks").sum(),
        pl.col("conversions").sum(),
        pl.col("approved_conversions").sum(),
        pl.col("revenue").sum(),
        pl.col("payout").sum(),
    ).row(0)
    clicks, conversions, approved, revenue, payout = cast(
        tuple[int, int, int, float, float], raw_totals
    )
    return MetricSnapshot.from_totals(
        clicks=clicks,
        conversions=conversions,
        approved_conversions=approved,
        revenue=revenue,
        payout=payout,
    )
