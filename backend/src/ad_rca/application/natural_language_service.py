from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from ad_rca.agent.contracts import IntentParser, InvestigationPlanner, ReportComposer
from ad_rca.agent.intent import AnalysisIntent
from ad_rca.agent.models import InvestigationReport, QuestionAnswer, QuestionRequest
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.application.investigation_service import validate_answer_evidence
from ad_rca.data.mysql_snapshot import LoadedAnalysisSnapshot
from ad_rca.domain.models import CoreInvestigationResult, SliceKey
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import InvalidModelOutputError, ModelUnavailableError
from ad_rca.infrastructure.models.fake import TemplateReportComposer
from ad_rca.workflow.graph import InvestigationWorkflow, WorkflowRun


class SnapshotLoader(Protocol):
    async def load(self, intent: AnalysisIntent) -> LoadedAnalysisSnapshot: ...

    async def check(self) -> None: ...


@dataclass(frozen=True)
class NaturalLanguageAnalysis:
    intent: AnalysisIntent
    selected_scope: SliceKey
    run: WorkflowRun


class NaturalLanguageAnalysisService:
    def __init__(
        self,
        *,
        parser: IntentParser,
        loader: SnapshotLoader,
        planner: InvestigationPlanner,
        composer: ReportComposer,
        artifact_store: ArtifactStore,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._parser = parser
        self._loader = loader
        self._planner = planner
        self._composer = composer
        self._fallback_composer = TemplateReportComposer()
        self._artifacts = artifact_store
        self._id_factory = id_factory or (lambda: f"run-{uuid4().hex}")

    async def check_database(self) -> None:
        await self._loader.check()

    async def ask(self, question: str) -> NaturalLanguageAnalysis:
        intent = self._parser.parse(question)
        snapshot = await self._loader.load(intent)
        core = CoreRcaService(
            snapshot.repository,
            default_verifiers(),
            analysis_window=intent.window,
            base_scope=snapshot.selected_scope,
            source_system="mysql",
        )
        run_id = self._id_factory()
        prepared = core.prepare(snapshot.repository.scenario_id)
        if prepared.incident is None:
            result = CoreInvestigationResult(
                status=prepared.status,
                incident=None,
                residual_loss=0,
            )
            report = InvestigationReport(
                run_id=run_id,
                incident_id="no-incident",
                status=result.status,
                summary="请求时间范围内未检测到利润异常。",
                generated_without_llm=True,
            )
            run = WorkflowRun(
                run_id=run_id,
                rounds=0,
                result=result,
                report=report,
                events=(),
            )
        else:
            workflow = InvestigationWorkflow(
                core,
                self._planner,
                self._composer,
                artifact_store=self._artifacts,
            )
            run = workflow.run(snapshot.repository.scenario_id, run_id=run_id)
        return NaturalLanguageAnalysis(
            intent=intent,
            selected_scope=snapshot.selected_scope,
            run=run,
        )

    def answer(
        self, analysis: NaturalLanguageAnalysis, question: str
    ) -> QuestionAnswer:
        request = QuestionRequest(question=question, report=analysis.run.report)
        try:
            answer = self._composer.answer(request)
            validate_answer_evidence(answer, analysis.run.report)
            return answer
        except (ModelUnavailableError, InvalidModelOutputError, ValueError):
            return self._fallback_composer.answer(request)
