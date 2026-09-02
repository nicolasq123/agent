from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from ad_rca.domain.models import PerformanceRow, StrictModel


class DataQualityStatus(StrEnum):
    PASS = "pass"
    INCOMPLETE = "incomplete"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


class DataQualityResult(StrictModel):
    status: DataQualityStatus
    completeness: float = Field(ge=0, le=1)
    total_clicks: int = Field(ge=0)
    reasons: tuple[str, ...] = ()


def assess_data_quality(
    rows: Sequence[PerformanceRow], *, expected_hours: int, minimum_clicks: int
) -> DataQualityResult:
    if expected_hours <= 0:
        raise ValueError("expected_hours must be positive")
    if minimum_clicks < 0:
        raise ValueError("minimum_clicks cannot be negative")

    observed_hours = len({row.event_hour for row in rows})
    completeness = min(observed_hours / expected_hours, 1.0)
    total_clicks = sum(row.clicks for row in rows)
    if completeness < 0.95:
        return DataQualityResult(
            status=DataQualityStatus.INCOMPLETE,
            completeness=completeness,
            total_clicks=total_clicks,
            reasons=("completeness_below_95_percent",),
        )
    if total_clicks < minimum_clicks:
        return DataQualityResult(
            status=DataQualityStatus.INSUFFICIENT_SAMPLE,
            completeness=completeness,
            total_clicks=total_clicks,
            reasons=("clicks_below_minimum",),
        )
    return DataQualityResult(
        status=DataQualityStatus.PASS,
        completeness=completeness,
        total_clicks=total_clicks,
    )
