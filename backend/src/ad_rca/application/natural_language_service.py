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
from ad_rca.detection.metrics import aggregate_metrics
from ad_rca.domain.enums import RunStatus
from ad_rca.domain.models import CoreInvestigationResult, SliceKey
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import InvalidModelOutputError, ModelUnavailableError
from ad_rca.infrastructure.models.fake import TemplateReportComposer
from ad_rca.workflow.events import WorkflowEvent
from ad_rca.workflow.graph import InvestigationWorkflow, WorkflowRun


class SnapshotLoader(Protocol):
    async def load(self, intent: AnalysisIntent) -> LoadedAnalysisSnapshot: ...

    async def check(self) -> None: ...


@dataclass(frozen=True)
class NaturalLanguageAnalysis:
    intent: AnalysisIntent
    selected_scope: SliceKey
    run: WorkflowRun


class AnalysisDataQualityError(RuntimeError):
    pass


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

    async def ask(
        self,
        question: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> NaturalLanguageAnalysis:
        _notify(progress, "正在解析问题和时间范围")
        intent = self._parser.parse(question)
        _notify(progress, "正在读取 MySQL 当前数据和历史基线")
        snapshot = await self._loader.load(intent)
        _notify(progress, "正在检测异常并计算利润损失")
        core = CoreRcaService(
            snapshot.repository,
            default_verifiers(),
            analysis_window=intent.window,
            base_scope=snapshot.selected_scope,
            source_system="mysql",
        )
        run_id = self._id_factory()
        prepared = core.prepare(snapshot.repository.scenario_id)
        if prepared.status is RunStatus.DATA_QUALITY_BLOCKED:
            if prepared.errors:
                current = snapshot.repository.performance(intent.window, snapshot.selected_scope)
                metrics = aggregate_metrics(current)
                margin = f"{metrics.margin:.2%}" if metrics.margin is not None else "无法计算"
                result = CoreInvestigationResult(
                    status=prepared.status,
                    incident=None,
                    residual_loss=0,
                )
                report = InvestigationReport(
                    run_id=run_id,
                    incident_id="history-unavailable",
                    status=prepared.status,
                    summary=(
                        f"本期收入 {metrics.revenue:.2f}，支出 {metrics.payout:.2f}，"
                        f"利润 {metrics.profit:.2f}，利润率 {margin}。"
                        "数据库未返回分析窗口之前的可比历史数据，无法判断利润升降或归因。"
                    ),
                    generated_without_llm=True,
                    warnings=("HISTORY_BASELINE_UNAVAILABLE",),
                )
                run = WorkflowRun(
                    run_id=run_id,
                    rounds=0,
                    result=result,
                    report=report,
                    events=(),
                    warnings=("HISTORY_BASELINE_UNAVAILABLE",),
                )
                _notify(progress, "分析完成：已汇总当前利润，历史基线不可用")
                return NaturalLanguageAnalysis(
                    intent=intent,
                    selected_scope=snapshot.selected_scope,
                    run=run,
                )
            raise AnalysisDataQualityError(
                "analysis was blocked by incomplete data or insufficient samples"
            )
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
            _notify(progress, "分析完成：未检测到利润异常")
        else:
            workflow = InvestigationWorkflow(
                core,
                self._planner,
                self._composer,
                artifact_store=self._artifacts,
            )
            event_sink = None
            if progress is not None:
                incident_id = prepared.incident.incident_id

                def publish(event: WorkflowEvent) -> None:
                    self._artifacts.append_event(incident_id, run_id, event)
                    message = _progress_message(event)
                    if message is not None:
                        progress(message)

                event_sink = publish
            run = workflow.run(
                snapshot.repository.scenario_id,
                run_id=run_id,
                event_sink=event_sink,
            )
        return NaturalLanguageAnalysis(
            intent=intent,
            selected_scope=snapshot.selected_scope,
            run=run,
        )

    def answer(self, analysis: NaturalLanguageAnalysis, question: str) -> QuestionAnswer:
        request = QuestionRequest(question=question, report=analysis.run.report)
        try:
            answer = self._composer.answer(request)
            validate_answer_evidence(answer, analysis.run.report)
            return answer
        except (ModelUnavailableError, InvalidModelOutputError, ValueError):
            return self._fallback_composer.answer(request)


def _notify(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _progress_message(event: WorkflowEvent) -> str | None:
    if event.event_type == "attribution_completed":
        return f"损失归因完成：{event.payload.get('paths', 0)} 个路径"
    if event.event_type == "hypothesis_generated":
        return "已生成根因候选"
    if event.event_type == "plan_created":
        return "正在验证根因候选"
    if event.event_type == "root_cause_confirmed":
        return f"已找到支持证据：{event.payload.get('hypothesis', 'unknown')}"
    if event.event_type == "report_generated":
        return "证据验证完成，报告已生成"
    return None
