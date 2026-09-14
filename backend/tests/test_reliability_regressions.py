from datetime import UTC, datetime, timedelta
from math import isclose
from pathlib import Path

from ad_rca.application.core_service import (
    CoreRcaService,
    _expected_rows,  # pyright: ignore[reportPrivateUsage]
    default_verifiers,
)
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.detection.baseline import build_profit_baseline
from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.models import PerformanceRow, ScenarioBundle, ScenarioMetadata, TimeWindow
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.infrastructure.models.intent import RuleIntentParser
from ad_rca.workflow.graph import InvestigationWorkflow

START = datetime(2026, 9, 10, tzinfo=UTC)


def row(hour: datetime, revenue: float, payout: float) -> PerformanceRow:
    return PerformanceRow(
        event_hour=hour,
        advertiser_id="1",
        offer_id="1",
        channel_id="1",
        country="US",
        clicks=1000,
        conversions=100,
        approved_conversions=0,
        revenue=revenue,
        payout=payout,
    )


def test_plain_revenue_request_is_not_rca() -> None:
    intent = RuleIntentParser(now=lambda: START + timedelta(days=1)).parse("分析昨天的收入")
    assert intent.kind.value == "summary"


def test_detection_and_attribution_baseline_agree() -> None:
    history = tuple(
        row(START - timedelta(weeks=i), r, p)
        for i, (r, p) in enumerate(((0, 0), (100, 0), (100, 100), (1000, 1000)), 1)
    )
    baseline = build_profit_baseline(
        current_hour=START,
        current_rows=(row(START, 100, 100),),
        history_rows=history,
    )
    assert isclose(
        aggregate_metrics(_expected_rows(history, (START,))).profit, baseline.expected_profit
    )


def test_improving_negative_profit_has_no_empty_path_crash(tmp_path: Path) -> None:
    history = tuple(
        row(START + timedelta(hours=h) - timedelta(weeks=w), 100, 1100)
        for h in range(3)
        for w in range(1, 5)
    )
    current = tuple(row(START + timedelta(hours=h), 100, 600) for h in range(3))
    repository = FixtureRepository(
        ScenarioBundle(
            metadata=ScenarioMetadata(scenario_id="negative", name="negative", timezone="UTC"),
            performance=history + current,
        )
    )
    result = CoreRcaService(
        repository,
        default_verifiers(),
        analysis_window=TimeWindow(start=START, end=START + timedelta(hours=3)),
    ).investigate("negative")
    assert result.incident is not None
    assert not result.hypotheses
    core = CoreRcaService(
        repository,
        default_verifiers(),
        analysis_window=TimeWindow(start=START, end=START + timedelta(hours=3)),
    )
    run = InvestigationWorkflow(
        core, FakePlanner(), TemplateReportComposer(), artifact_store=ArtifactStore(tmp_path)
    ).run("negative", run_id="negative")
    assert run.rounds == 0
    assert not run.report.conclusions
