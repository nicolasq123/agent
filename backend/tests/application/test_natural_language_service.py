from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.agent.models import (
    InvestigationPlan,
    PlanningRequest,
    QuestionAnswer,
    QuestionRequest,
)
from ad_rca.api.dependencies import build_natural_language_service
from ad_rca.application.natural_language_service import NaturalLanguageAnalysisService
from ad_rca.application.scope_discovery import NoAnalyzableDataError
from ad_rca.config import Settings
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.data.mysql_snapshot import LoadedAnalysisSnapshot
from ad_rca.domain.enums import RunStatus
from ad_rca.domain.models import (
    PerformanceRow,
    ScenarioBundle,
    ScenarioMetadata,
    SliceKey,
    TimeWindow,
)
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import ModelUnavailableError
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer

START = datetime(2026, 9, 3, 10, tzinfo=UTC)


class FixedIntentParser:
    def __init__(self, intent: AnalysisIntent) -> None:
        self.intent = intent
        self.questions: list[str] = []

    def parse(self, question: str) -> AnalysisIntent:
        self.questions.append(question)
        return self.intent


class FakeSnapshotLoader:
    def __init__(
        self,
        snapshot: LoadedAnalysisSnapshot | None = None,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.error = error
        self.checked = False

    async def load(self, intent: AnalysisIntent) -> LoadedAnalysisSnapshot:
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return self.snapshot

    async def check(self) -> None:
        self.checked = True
        if self.error is not None:
            raise self.error


class EmptyQueryReader:
    async def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        return ()

    async def check(self) -> None:
        return None


def _intent() -> AnalysisIntent:
    return AnalysisIntent(
        question="分析昨天 offer 12345 为什么利润下降",
        window=TimeWindow(start=START, end=START + timedelta(hours=3)),
        scope=SliceKey(offer_id="12345"),
        timezone="UTC",
    )


def _snapshot(*, current_profit: float = 100) -> LoadedAnalysisSnapshot:
    def row(event_hour: datetime, profit: float) -> PerformanceRow:
        return PerformanceRow(
            event_hour=event_hour,
            advertiser_id="9",
            offer_id="12345",
            channel_id="678",
            country="US",
            clicks=1000,
            conversions=100,
            approved_conversions=0,
            revenue=1000,
            payout=1000 - profit,
        )

    history = tuple(
        row(START + timedelta(hours=hour) - timedelta(weeks=week), 400)
        for hour in range(3)
        for week in range(1, 9)
    )
    current = tuple(row(START + timedelta(hours=hour), current_profit) for hour in range(3))
    repository = FixtureRepository(
        ScenarioBundle(
            metadata=ScenarioMetadata(
                scenario_id="mysql-analysis",
                name="MySQL",
                timezone="UTC",
            ),
            performance=history + current,
        )
    )
    return LoadedAnalysisSnapshot(
        intent=_intent(),
        selected_scope=SliceKey(offer_id="12345"),
        repository=repository,
    )


@pytest.mark.anyio
async def test_question_runs_real_workflow_over_loaded_snapshot(tmp_path: Path) -> None:
    parser = FixedIntentParser(_intent())
    service = NaturalLanguageAnalysisService(
        parser=parser,
        loader=FakeSnapshotLoader(_snapshot()),
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-natural-language",
    )

    analysis = await service.ask("分析昨天 offer 12345 为什么利润下降")

    assert analysis.run.result.status is RunStatus.COMPLETED
    assert analysis.run.report.conclusions
    assert analysis.intent.scope.offer_id == "12345"
    assert analysis.selected_scope == SliceKey(offer_id="12345")
    assert parser.questions == ["分析昨天 offer 12345 为什么利润下降"]


@pytest.mark.anyio
async def test_no_incident_returns_an_explicit_report(tmp_path: Path) -> None:
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(_intent()),
        loader=FakeSnapshotLoader(_snapshot(current_profit=400)),
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-no-incident",
    )

    analysis = await service.ask("昨天利润正常吗")

    assert analysis.run.result.incident is None
    assert analysis.run.report.conclusions == ()
    assert "未检测到" in analysis.run.report.summary


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [NoAnalyzableDataError("no data"), RuntimeError("database unavailable")],
)
async def test_loader_failures_are_not_turned_into_invented_reports(
    tmp_path: Path, error: Exception
) -> None:
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(_intent()),
        loader=FakeSnapshotLoader(error=error),
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )

    with pytest.raises(type(error), match=str(error)):
        await service.ask("分析昨天利润")


@pytest.mark.anyio
async def test_database_check_delegates_to_snapshot_loader(tmp_path: Path) -> None:
    loader = FakeSnapshotLoader(_snapshot())
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(_intent()),
        loader=loader,
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )

    await service.check_database()

    assert loader.checked is True


class InvalidAnswerComposer(TemplateReportComposer):
    def answer(self, request: QuestionRequest) -> QuestionAnswer:
        return QuestionAnswer(answer="invented", evidence_ids=("unknown-evidence",))


class UnavailablePlanner(FakePlanner):
    def plan(self, request: PlanningRequest) -> InvestigationPlan:
        raise ModelUnavailableError("offline")


@pytest.mark.anyio
async def test_follow_up_may_cite_only_the_current_report(tmp_path: Path) -> None:
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(_intent()),
        loader=FakeSnapshotLoader(_snapshot()),
        planner=FakePlanner(),
        composer=InvalidAnswerComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-answer",
    )
    analysis = await service.ask("分析昨天利润")

    answer = service.answer(analysis, "还有哪些证据？")

    allowed = {
        evidence_id
        for conclusion in analysis.run.report.conclusions
        for evidence_id in conclusion.evidence_ids
    }
    assert set(answer.evidence_ids).issubset(allowed)
    assert answer.generated_without_llm is True


@pytest.mark.anyio
async def test_model_failure_uses_deterministic_workflow_fallback(tmp_path: Path) -> None:
    service = NaturalLanguageAnalysisService(
        parser=FixedIntentParser(_intent()),
        loader=FakeSnapshotLoader(_snapshot()),
        planner=UnavailablePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-fallback",
    )

    analysis = await service.ask("分析昨天利润")

    assert analysis.run.report.conclusions
    assert "LLM_UNAVAILABLE" in analysis.run.warnings
    assert analysis.run.report.generated_without_llm is True


def test_dependency_builder_requires_readonly_database_mode(tmp_path: Path) -> None:
    settings = Settings(
        data_mode="fixture",
        model_mode="fake",
        artifacts_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="readonly_db"):
        build_natural_language_service(settings)


def test_dependency_builder_shares_one_query_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[tuple[str, object]] = []

    def fake_create(
        url: str,
        specs: object,
        budget: object,
        *,
        auto_query_mode: int,
    ) -> EmptyQueryReader:
        assert auto_query_mode == 0
        created.append((url, budget))
        return EmptyQueryReader()

    monkeypatch.setattr("ad_rca.api.dependencies.create_mysql_executor", fake_create)
    settings = Settings(
        data_mode="readonly_db",
        model_mode="fake",
        mysql_stat_url=SecretStr("mysql+asyncmy://db20/au_stat"),
        mysql_config_url=SecretStr("mysql+asyncmy://db40/ymgw"),
        auto_query_mode=0,
        artifacts_dir=tmp_path,
    )

    service = build_natural_language_service(settings)

    assert isinstance(service, NaturalLanguageAnalysisService)
    assert [url for url, _ in created] == [
        "mysql+asyncmy://db20/au_stat",
        "mysql+asyncmy://db40/ymgw",
    ]
    assert created[0][1] is created[1][1]
