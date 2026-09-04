from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import Literal

from ad_rca.application.investigation_case import PreparedInvestigation
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.detection.detector import DetectionConfig, detect_incident
from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.enums import (
    Confidence,
    EvidenceStrength,
    HypothesisStatus,
    HypothesisType,
    RunStatus,
)
from ad_rca.domain.models import (
    CoreInvestigationResult,
    HypothesisResult,
    PerformanceRow,
    SliceKey,
    TimeWindow,
)
from ad_rca.rca.candidates import generate_candidates
from ad_rca.rca.contribution import ALLOWED_DIMENSIONS, attribute_loss
from ad_rca.rca.decomposition import decompose_profit_change
from ad_rca.rca.verifiers.base import VerificationContext, Verifier
from ad_rca.rca.verifiers.cap import CapVerifier
from ad_rca.rca.verifiers.conversion import ConversionPathVerifier
from ad_rca.rca.verifiers.pricing import PricingVerifier, RevenuePriceVerifier
from ad_rca.rca.verifiers.traffic_mix import TrafficMixVerifier
from ad_rca.rca.verifiers.traffic_quality import TrafficQualityVerifier
from ad_rca.rca.verifiers.traffic_volume import TrafficVolumeVerifier


def default_verifiers() -> Mapping[HypothesisType, Verifier]:
    verifiers: tuple[Verifier, ...] = (
        PricingVerifier(),
        RevenuePriceVerifier(),
        TrafficVolumeVerifier(),
        TrafficMixVerifier(),
        ConversionPathVerifier(),
        CapVerifier(),
        TrafficQualityVerifier(),
    )
    return {verifier.hypothesis: verifier for verifier in verifiers}


class CoreRcaService:
    def __init__(
        self,
        repository: FixtureRepository,
        verifiers: Mapping[HypothesisType, Verifier],
        detection_config: DetectionConfig | None = None,
        *,
        analysis_window: TimeWindow | None = None,
        base_scope: SliceKey | None = None,
        source_system: Literal["fixture", "mysql"] = "fixture",
    ) -> None:
        self._repository = repository
        self._verifiers = verifiers
        self._detection_config = detection_config or DetectionConfig()
        self._analysis_window = analysis_window
        self._base_scope = base_scope or SliceKey()
        self._source_system: Literal["fixture", "mysql"] = source_system

    def investigate(self, scenario_id: str) -> CoreInvestigationResult:
        prepared = self.prepare(scenario_id)
        return self.verify(prepared, prepared.candidates[:3])

    def prepare(self, scenario_id: str) -> PreparedInvestigation:
        if scenario_id != self._repository.scenario_id:
            raise ValueError(f"unknown scenario: {scenario_id}")
        all_rows = _filter_rows(self._repository.all_performance(), self._base_scope)
        if self._analysis_window is None:
            current_hours = sorted({row.event_hour for row in all_rows})[-3:]
            current = tuple(row for row in all_rows if row.event_hour in current_hours)
            history = tuple(row for row in all_rows if row.event_hour not in current_hours)
            detection_config = self._detection_config
        else:
            current = tuple(
                row
                for row in all_rows
                if self._analysis_window.start <= row.event_hour < self._analysis_window.end
            )
            history = tuple(row for row in all_rows if row.event_hour < self._analysis_window.start)
            current_hours = sorted({row.event_hour for row in current})
            expected_hours = int(
                (self._analysis_window.end - self._analysis_window.start).total_seconds() // 3600
            )
            detection_config = self._detection_config.model_copy(
                update={"window_count": expected_hours}
            )
        detection = detect_incident(
            current,
            history,
            detection_config,
            scope=self._base_scope,
        )
        if detection.incident is None:
            return PreparedInvestigation(
                status=detection.status,
                incident=None,
                residual_loss=0.0,
            )

        expected = _expected_rows(history, current_hours)
        attribution = attribute_loss(
            current,
            expected,
            tuple(ALLOWED_DIMENSIONS),
            max_depth=3,
            min_share=0.10,
        )
        decomposition = decompose_profit_change(current, expected)
        top_slice = attribution.paths[0]
        actual_slice = _filter_rows(current, top_slice.slice_key)
        expected_slice = _filter_rows(expected, top_slice.slice_key)
        evidence_window = TimeWindow(
            start=detection.incident.window.start - timedelta(minutes=30),
            end=detection.incident.window.end,
        )
        context = VerificationContext(
            incident=detection.incident,
            affected_slice=top_slice.slice_key,
            current=aggregate_metrics(actual_slice),
            baseline=aggregate_metrics(expected_slice),
            attribution=top_slice,
            decomposition=decomposition,
            config_changes=self._repository.pricing_changes(evidence_window, top_slice.slice_key),
            caps=self._repository.cap_observations(evidence_window, top_slice.slice_key),
            postbacks=self._repository.postback_events(evidence_window, top_slice.slice_key),
            quality_events=self._repository.quality_events(evidence_window, top_slice.slice_key),
            routing_changes=self._repository.routing_changes(evidence_window, top_slice.slice_key),
            source_system=self._source_system,
        )
        return PreparedInvestigation(
            status=detection.status,
            incident=detection.incident,
            attributions=attribution.paths,
            residual_loss=attribution.residual_loss,
            context=context,
            candidates=generate_candidates(context),
        )

    def verify(
        self,
        prepared: PreparedInvestigation,
        selected: Sequence[HypothesisType],
    ) -> CoreInvestigationResult:
        if prepared.incident is None:
            if selected:
                raise ValueError("cannot select candidates without an incident")
            return CoreInvestigationResult(
                status=prepared.status,
                incident=None,
                residual_loss=prepared.residual_loss,
            )
        if prepared.context is None:
            raise ValueError("prepared incident is missing verification context")
        selected_tuple = tuple(selected)
        if len(selected_tuple) > 3:
            raise ValueError("at most three candidates can be selected")
        if len(set(selected_tuple)) != len(selected_tuple):
            raise ValueError("duplicate candidate selection")
        if any(item not in prepared.candidates for item in selected_tuple):
            raise ValueError("selected candidate was not offered by deterministic analysis")

        hypotheses = tuple(
            self._verifiers[item].verify(prepared.context) for item in selected_tuple
        )
        _guard_evidence(hypotheses)
        evidence = tuple(item for result in hypotheses for item in result.evidence)
        contradictions = tuple(item for result in hypotheses for item in result.contradictions)
        status = (
            RunStatus.COMPLETED
            if any(item.status is HypothesisStatus.SUPPORTED for item in hypotheses)
            else RunStatus.INSUFFICIENT_EVIDENCE
        )
        return CoreInvestigationResult(
            status=status,
            incident=prepared.incident,
            attributions=prepared.attributions,
            hypotheses=hypotheses,
            evidence=evidence,
            contradictions=contradictions,
            residual_loss=prepared.residual_loss,
        )


def _expected_rows(
    history: Sequence[PerformanceRow], current_hours: Sequence[datetime]
) -> tuple[PerformanceRow, ...]:
    grouped: dict[tuple[str, str, str, str], list[PerformanceRow]] = defaultdict(list)
    for row in history:
        grouped[(row.advertiser_id, row.offer_id, row.channel_id, row.country)].append(row)
    rows: list[PerformanceRow] = []
    for (advertiser, offer, channel, country), values in grouped.items():
        for current_hour in current_hours:
            matching = tuple(
                row
                for row in values
                if row.event_hour.weekday() == current_hour.weekday()
                and row.event_hour.hour == current_hour.hour
            )
            if not matching:
                continue
            rows.append(
                PerformanceRow(
                    event_hour=current_hour,
                    advertiser_id=advertiser,
                    offer_id=offer,
                    channel_id=channel,
                    country=country,
                    clicks=round(median(row.clicks for row in matching)),
                    conversions=round(median(row.conversions for row in matching)),
                    approved_conversions=round(
                        median(row.approved_conversions for row in matching)
                    ),
                    revenue=median(row.revenue for row in matching),
                    payout=median(row.payout for row in matching),
                )
            )
    return tuple(rows)


def _filter_rows(rows: Sequence[PerformanceRow], slice_key: SliceKey) -> tuple[PerformanceRow, ...]:
    return tuple(
        row
        for row in rows
        if all(getattr(row, name) == value for name, value in slice_key.dimensions())
    )


def _guard_evidence(hypotheses: Sequence[HypothesisResult]) -> None:
    evidence_ids: set[str] = set()
    for result in hypotheses:
        for item in result.evidence:
            if item.evidence_id in evidence_ids:
                raise ValueError("duplicate evidence id")
            evidence_ids.add(item.evidence_id)
        if result.confidence is Confidence.CONFIRMED and not any(
            item.strength is EvidenceStrength.DIRECT for item in result.evidence
        ):
            raise ValueError("confirmed conclusions require direct evidence")
