from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ad_rca.domain.enums import (
    Confidence,
    EvidenceStrength,
    HypothesisStatus,
    HypothesisType,
    IncidentType,
    RunStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TimeWindow(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time window must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class SliceKey(StrictModel):
    advertiser_id: str | None = None
    offer_id: str | None = None
    channel_id: str | None = None
    country: str | None = None

    def dimensions(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("advertiser_id", self.advertiser_id),
            ("offer_id", self.offer_id),
            ("channel_id", self.channel_id),
            ("country", self.country),
        )
        return tuple((name, value) for name, value in values if value is not None)

    @property
    def depth(self) -> int:
        return len(self.dimensions())


class PerformanceRow(StrictModel):
    event_hour: datetime
    advertiser_id: str
    offer_id: str
    channel_id: str
    country: str
    os: str | None = None
    carrier: str | None = None
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    approved_conversions: int = Field(ge=0)
    revenue: float
    payout: float

    @model_validator(mode="after")
    def validate_counts_and_time(self) -> Self:
        if self.event_hour.tzinfo is None:
            raise ValueError("event_hour must be timezone-aware")
        if self.approved_conversions > self.conversions:
            raise ValueError("approved_conversions cannot exceed conversions")
        return self


class MetricSnapshot(StrictModel):
    clicks: int = Field(ge=0)
    conversions: int = Field(ge=0)
    approved_conversions: int = Field(ge=0)
    revenue: float
    payout: float
    profit: float
    margin: float | None
    cvr: float | None
    approval_rate: float | None
    epc: float | None
    cost_per_click: float | None

    @classmethod
    def from_totals(
        cls,
        *,
        clicks: int,
        conversions: int,
        approved_conversions: int,
        revenue: float,
        payout: float,
    ) -> Self:
        profit = revenue - payout
        return cls(
            clicks=clicks,
            conversions=conversions,
            approved_conversions=approved_conversions,
            revenue=revenue,
            payout=payout,
            profit=profit,
            margin=profit / revenue if revenue else None,
            cvr=conversions / clicks if clicks else None,
            approval_rate=approved_conversions / conversions if conversions else None,
            epc=revenue / clicks if clicks else None,
            cost_per_click=payout / clicks if clicks else None,
        )


class BaselineResult(StrictModel):
    expected_profit: float
    median_profit: float
    mad: float = Field(ge=0)
    robust_z: float
    sample_size: int = Field(ge=0)
    mad_zero: bool


class Incident(StrictModel):
    incident_id: str
    incident_type: IncidentType
    scope: SliceKey
    window: TimeWindow
    actual_profit: float
    expected_profit: float
    lost_profit: float = Field(ge=0)
    drop_ratio: float | None
    robust_z: float
    triggered_windows: int = Field(ge=1)
    data_completeness: float = Field(ge=0, le=1)


class AttributionResult(StrictModel):
    slice_key: SliceKey
    actual_profit: float
    expected_profit: float
    lost_profit: float = Field(ge=0)
    share: float = Field(ge=0)


class EvidenceSource(StrictModel):
    system: str
    dataset: str
    record_ids: tuple[str, ...] = ()


class EvidenceCalculation(StrictModel):
    formula: str
    inputs: dict[str, float] = Field(default_factory=dict)
    explained_loss: float = Field(ge=0)


class Evidence(StrictModel):
    evidence_id: str
    hypothesis: HypothesisType
    strength: EvidenceStrength
    observed_at: datetime
    source: EvidenceSource
    statement: str
    calculation: EvidenceCalculation


class HypothesisResult(StrictModel):
    hypothesis: HypothesisType
    status: HypothesisStatus
    confidence: Confidence
    affected_slice: SliceKey
    explained_loss: float = Field(ge=0)
    explanatory_power: float = Field(ge=0, le=1)
    evidence: tuple[Evidence, ...] = ()
    contradictions: tuple[Evidence, ...] = ()


class CoreInvestigationResult(StrictModel):
    status: RunStatus
    incident: Incident | None
    attributions: tuple[AttributionResult, ...] = ()
    hypotheses: tuple[HypothesisResult, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    contradictions: tuple[Evidence, ...] = ()
    residual_loss: float = Field(ge=0)
