from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from pydantic import Field

from ad_rca.detection.baseline import InsufficientHistoryError, build_profit_baseline
from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.detection.quality import DataQualityResult, DataQualityStatus, assess_data_quality
from ad_rca.domain.enums import IncidentType, RunStatus
from ad_rca.domain.models import (
    BaselineResult,
    Incident,
    PerformanceRow,
    SliceKey,
    StrictModel,
    TimeWindow,
)


class DetectionConfig(StrictModel):
    robust_z_threshold: float = -3.0
    relative_drop_threshold: float = Field(default=0.20, ge=0, le=1)
    minimum_absolute_loss: float = Field(default=500.0, gt=0)
    required_hits: int = Field(default=2, ge=1)
    window_count: int = Field(default=3, ge=1)
    minimum_clicks: int = Field(default=100, ge=0)
    baseline_profit_floor: float = Field(default=100.0, ge=0)
    deviation_floor: float = Field(default=1.0, gt=0)


class DetectionResult(StrictModel):
    status: RunStatus
    incident: Incident | None
    baselines: tuple[BaselineResult, ...] = ()
    quality: DataQualityResult
    errors: tuple[str, ...] = ()


def detect_incident(
    current_rows: Sequence[PerformanceRow],
    history_rows: Sequence[PerformanceRow],
    config: DetectionConfig,
    *,
    scope: SliceKey | None = None,
) -> DetectionResult:
    grouped = _group_by_hour(current_rows)
    quality = assess_data_quality(
        current_rows,
        expected_hours=config.window_count,
        minimum_clicks=config.minimum_clicks,
    )
    if quality.status is not DataQualityStatus.PASS:
        return DetectionResult(
            status=RunStatus.DATA_QUALITY_BLOCKED,
            incident=None,
            quality=quality,
        )

    selected_hours = sorted(grouped)[-config.window_count :]
    baselines: list[BaselineResult] = []
    profit_drop_hits = 0
    negative_profit_hits = 0
    try:
        for event_hour in selected_hours:
            rows = grouped[event_hour]
            baseline = build_profit_baseline(
                current_hour=event_hour,
                current_rows=rows,
                history_rows=history_rows,
                deviation_floor=config.deviation_floor,
            )
            baselines.append(baseline)
            actual_profit = aggregate_metrics(rows).profit
            lost_profit = baseline.expected_profit - actual_profit
            drop_ratio = (
                lost_profit / abs(baseline.expected_profit)
                if abs(baseline.expected_profit) >= config.baseline_profit_floor
                else None
            )
            if (
                drop_ratio is not None
                and baseline.robust_z <= config.robust_z_threshold
                and drop_ratio >= config.relative_drop_threshold
            ):
                profit_drop_hits += 1
            if actual_profit < 0:
                negative_profit_hits += 1
    except InsufficientHistoryError as error:
        return DetectionResult(
            status=RunStatus.DATA_QUALITY_BLOCKED,
            incident=None,
            baselines=tuple(baselines),
            quality=quality,
            errors=(str(error),),
        )

    actual_profit = aggregate_metrics(current_rows).profit
    expected_profit = sum(item.expected_profit for item in baselines)
    lost_profit = max(expected_profit - actual_profit, 0.0)

    incident_type: IncidentType | None = None
    triggered_windows = 0
    if profit_drop_hits >= config.required_hits and lost_profit >= config.minimum_absolute_loss:
        incident_type = IncidentType.PROFIT_DROP
        triggered_windows = profit_drop_hits
    elif (
        negative_profit_hits >= config.required_hits
        and actual_profit <= -config.minimum_absolute_loss
    ):
        incident_type = IncidentType.NEGATIVE_PROFIT
        triggered_windows = negative_profit_hits

    if incident_type is None:
        return DetectionResult(
            status=RunStatus.COMPLETED,
            incident=None,
            baselines=tuple(baselines),
            quality=quality,
        )

    drop_ratio = lost_profit / abs(expected_profit) if expected_profit else None
    window = TimeWindow(start=selected_hours[0], end=selected_hours[-1] + timedelta(hours=1))
    incident_id = _incident_id(incident_type, window, current_rows)
    incident = Incident(
        incident_id=incident_id,
        incident_type=incident_type,
        scope=scope if scope is not None else SliceKey(),
        window=window,
        actual_profit=actual_profit,
        expected_profit=expected_profit,
        lost_profit=lost_profit,
        drop_ratio=drop_ratio,
        robust_z=min(item.robust_z for item in baselines),
        triggered_windows=triggered_windows,
        data_completeness=quality.completeness,
    )
    return DetectionResult(
        status=RunStatus.COMPLETED,
        incident=incident,
        baselines=tuple(baselines),
        quality=quality,
    )


def _group_by_hour(
    rows: Sequence[PerformanceRow],
) -> dict[datetime, tuple[PerformanceRow, ...]]:
    grouped: dict[datetime, list[PerformanceRow]] = defaultdict(list)
    for row in rows:
        grouped[row.event_hour].append(row)
    return {event_hour: tuple(hour_rows) for event_hour, hour_rows in grouped.items()}


def _incident_id(
    incident_type: IncidentType,
    window: TimeWindow,
    current_rows: Sequence[PerformanceRow],
) -> str:
    row_fingerprints = sorted(
        ":".join(
            (
                row.event_hour.isoformat(),
                row.advertiser_id,
                row.offer_id,
                row.channel_id,
                row.country,
                str(row.clicks),
                str(row.conversions),
                str(row.approved_conversions),
                f"{row.revenue:.8f}",
                f"{row.payout:.8f}",
            )
        )
        for row in current_rows
    )
    source = ":".join(
        (
            incident_type,
            window.start.isoformat(),
            window.end.isoformat(),
            *row_fingerprints,
        )
    )
    return f"inc-{sha256(source.encode()).hexdigest()[:12]}"
