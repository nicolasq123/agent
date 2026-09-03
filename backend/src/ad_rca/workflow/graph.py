from __future__ import annotations

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ad_rca.agent.contracts import InvestigationPlanner, ReportComposer
from ad_rca.agent.models import InvestigationReport, PlanningRequest, ReportRequest
from ad_rca.application.core_service import CoreRcaService
from ad_rca.application.investigation_case import PreparedInvestigation
from ad_rca.domain.enums import HypothesisStatus, HypothesisType, RunStatus
from ad_rca.domain.models import CoreInvestigationResult, HypothesisResult, StrictModel
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import (
    InvalidModelOutputError,
    ModelUnavailableError,
)
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.workflow.events import EventType, WorkflowEvent
from ad_rca.workflow.state import InvestigationState

MAX_ROUNDS = 2
MAX_VERIFIERS_PER_ROUND = 3

_EVENT_ORDER: dict[str, int] = {
    "baseline_loaded": 10,
    "attribution_completed": 20,
    "hypothesis_generated": 30,
    "plan_created": 40,
    "verifier_started": 50,
    "evidence_found": 60,
    "hypothesis_rejected": 70,
    "root_cause_confirmed": 80,
    "report_generated": 90,
}


class GraphRunner(Protocol):
    def invoke(
        self,
        input: InvestigationState,
        config: dict[str, object],
    ) -> InvestigationState: ...


class WorkflowRun(StrictModel):
    run_id: str
    rounds: int
    result: CoreInvestigationResult
    report: InvestigationReport
    events: tuple[WorkflowEvent, ...]
    warnings: tuple[str, ...] = ()

    def expected_event_order(self, event_type: str) -> int:
        return _EVENT_ORDER[event_type]


class InvestigationWorkflow:
    def __init__(
        self,
        core_service: CoreRcaService,
        planner: InvestigationPlanner,
        composer: ReportComposer,
        *,
        artifact_store: ArtifactStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._core = core_service
        self._planner = planner
        self._composer = composer
        self._fallback_planner = FakePlanner()
        self._fallback_composer = TemplateReportComposer()
        self._artifacts = artifact_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._graph = self._build_graph()

    def run(self, scenario_id: str, *, run_id: str) -> WorkflowRun:
        initial: InvestigationState = {
            "scenario_id": scenario_id,
            "run_id": run_id,
            "round_number": 1,
            "rounds_completed": 0,
            "prepared": None,
            "plan": None,
            "investigated": (),
            "result": None,
            "report": None,
            "events": [],
            "warnings": [],
        }
        state = self._graph.invoke(
            initial,
            {"configurable": {"thread_id": run_id}},
        )
        result = state["result"]
        report = state["report"]
        if result is None or report is None:
            raise RuntimeError("workflow ended without a result and report")
        events = tuple(
            sorted(state["events"], key=lambda event: (event.sequence, event.event_type))
        )
        if result.incident is None:
            raise ValueError("workflow completed without an incident")
        self._artifacts.write_incident(result.incident.incident_id, run_id, result.incident)
        self._artifacts.write_result(result.incident.incident_id, run_id, result)
        self._artifacts.write_report(result.incident.incident_id, run_id, report)
        self._artifacts.write_events(result.incident.incident_id, run_id, events)
        return WorkflowRun(
            run_id=run_id,
            rounds=state["rounds_completed"],
            result=result,
            report=report,
            events=events,
            warnings=tuple(state["warnings"]),
        )

    def _build_graph(self) -> GraphRunner:
        builder = StateGraph(InvestigationState)
        builder.add_node("prepare", self._prepare)
        builder.add_node("plan", self._plan)
        builder.add_node("verify", self._verify)
        builder.add_node("compose", self._compose)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "plan")
        builder.add_edge("plan", "verify")
        builder.add_conditional_edges(
            "verify",
            self._after_verify,
            {"continue": "plan", "compose": "compose"},
        )
        builder.add_edge("compose", END)
        return cast(GraphRunner, builder.compile(checkpointer=InMemorySaver()))

    def _prepare(self, state: InvestigationState) -> dict[str, object]:
        prepared = self._core.prepare(state["scenario_id"])
        if prepared.incident is None:
            raise ValueError("no incident was detected for investigation")
        return {
            "prepared": prepared,
            "events": [
                self._event(state, 10, "baseline_loaded", {"status": prepared.status.value}),
                self._event(
                    state,
                    20,
                    "attribution_completed",
                    {"paths": len(prepared.attributions)},
                ),
                self._event(
                    state,
                    30,
                    "hypothesis_generated",
                    {"candidates": [item.value for item in prepared.candidates]},
                ),
            ],
        }

    def _plan(self, state: InvestigationState) -> dict[str, object]:
        prepared = state["prepared"]
        if prepared is None:
            raise RuntimeError("workflow plan node is missing prepared state")
        if prepared.incident is None:
            raise ValueError("prepared investigation has no incident")
        request = PlanningRequest(
            incident=prepared.incident,
            candidates=prepared.candidates,
            attributions=prepared.attributions,
            round_number=state["round_number"],
            investigated=state["investigated"],
        )
        warnings: list[str] = []
        try:
            plan = self._planner.plan(request)
            _validate_plan_selection(plan.hypotheses, request)
        except ModelUnavailableError:
            warnings.append("LLM_UNAVAILABLE")
            plan = self._fallback_planner.plan(request)
        except (InvalidModelOutputError, ValueError):
            warnings.append("INVALID_LLM_OUTPUT")
            plan = self._fallback_planner.plan(request)
        return {
            "plan": plan,
            "warnings": warnings,
            "events": [
                self._event(
                    state,
                    35 + state["round_number"] * 5,
                    "plan_created",
                    {
                        "round": state["round_number"],
                        "hypotheses": [item.value for item in plan.hypotheses],
                    },
                )
            ],
        }

    def _verify(self, state: InvestigationState) -> dict[str, object]:
        prepared = state["prepared"]
        plan = state["plan"]
        if prepared is None or plan is None:
            raise RuntimeError("workflow verify node is missing prepared plan")
        selected: tuple[HypothesisType, ...] = plan.hypotheses[:MAX_VERIFIERS_PER_ROUND]
        with ThreadPoolExecutor(max_workers=len(selected)) as executor:
            futures = tuple(
                executor.submit(self._verify_candidate, prepared, candidate)
                for candidate in selected
            )
            partial_results = tuple(future.result() for future in futures)
        new_hypotheses = tuple(result.hypotheses[0] for result in partial_results)
        previous = state.get("result")
        merged = _merge_results(prepared, previous, new_hypotheses)
        events: list[WorkflowEvent] = []
        for index, hypothesis in enumerate(new_hypotheses):
            base = 45 + state["round_number"] * 15 + index * 2
            events.append(
                self._event(
                    state,
                    base,
                    "verifier_started",
                    {"hypothesis": hypothesis.hypothesis.value},
                )
            )
            if hypothesis.evidence:
                events.append(
                    self._event(
                        state,
                        base + 1,
                        "evidence_found",
                        {
                            "hypothesis": hypothesis.hypothesis.value,
                            "evidence_ids": [item.evidence_id for item in hypothesis.evidence],
                        },
                    )
                )
            if hypothesis.status is HypothesisStatus.REJECTED:
                events.append(
                    self._event(
                        state,
                        base + 1,
                        "hypothesis_rejected",
                        {"hypothesis": hypothesis.hypothesis.value},
                    )
                )
            if hypothesis.status is HypothesisStatus.SUPPORTED:
                events.append(
                    self._event(
                        state,
                        80,
                        "root_cause_confirmed",
                        {"hypothesis": hypothesis.hypothesis.value},
                    )
                )
        return {
            "result": merged,
            "investigated": (*state["investigated"], *selected),
            "round_number": state["round_number"] + 1,
            "rounds_completed": state["rounds_completed"] + 1,
            "events": events,
        }

    def _after_verify(self, state: InvestigationState) -> Literal["continue", "compose"]:
        result = state["result"]
        prepared = state["prepared"]
        if result is None or prepared is None:
            raise RuntimeError("workflow routing is missing investigation results")
        remaining = tuple(item for item in prepared.candidates if item not in state["investigated"])
        supported = any(item.status is HypothesisStatus.SUPPORTED for item in result.hypotheses)
        if not supported and state["rounds_completed"] < MAX_ROUNDS and remaining:
            return "continue"
        return "compose"

    def _compose(self, state: InvestigationState) -> dict[str, object]:
        result = state["result"]
        if result is None:
            raise RuntimeError("workflow compose node is missing a result")
        request = ReportRequest(run_id=state["run_id"], result=result)
        warnings: list[str] = []
        try:
            report = self._composer.compose(request)
            _validate_report_evidence(report, result)
        except ModelUnavailableError:
            warnings.append("LLM_UNAVAILABLE")
            report = self._fallback_composer.compose(request)
        except (InvalidModelOutputError, ValueError):
            warnings.append("INVALID_LLM_OUTPUT")
            report = self._fallback_composer.compose(request)
        return {
            "report": report,
            "warnings": warnings,
            "events": [
                self._event(
                    state,
                    90,
                    "report_generated",
                    {"generated_without_llm": report.generated_without_llm},
                )
            ],
        }

    def _verify_candidate(
        self, prepared: PreparedInvestigation, candidate: HypothesisType
    ) -> CoreInvestigationResult:
        return self._core.verify(prepared, (candidate,))

    def _event(
        self,
        state: InvestigationState,
        sequence: int,
        event_type: EventType,
        payload: dict[str, object],
    ) -> WorkflowEvent:
        return WorkflowEvent(
            run_id=state["run_id"],
            sequence=sequence,
            event_type=event_type,
            occurred_at=self._clock(),
            payload=payload,
        )


def _validate_plan_selection(selected: Sequence[HypothesisType], request: PlanningRequest) -> None:
    if len(selected) > MAX_VERIFIERS_PER_ROUND or len(set(selected)) != len(selected):
        raise ValueError("invalid verifier selection")
    if any(item not in request.candidates or item in request.investigated for item in selected):
        raise ValueError("planner selected a disallowed hypothesis")


def _merge_results(
    prepared: PreparedInvestigation,
    previous: CoreInvestigationResult | None,
    hypotheses: tuple[HypothesisResult, ...],
) -> CoreInvestigationResult:
    all_hypotheses = (*(() if previous is None else previous.hypotheses), *hypotheses)
    evidence = tuple(item for result in all_hypotheses for item in result.evidence)
    contradictions = tuple(item for result in all_hypotheses for item in result.contradictions)
    status = (
        RunStatus.COMPLETED
        if any(item.status is HypothesisStatus.SUPPORTED for item in all_hypotheses)
        else RunStatus.INSUFFICIENT_EVIDENCE
    )
    return CoreInvestigationResult(
        status=status,
        incident=prepared.incident,
        attributions=prepared.attributions,
        hypotheses=all_hypotheses,
        evidence=evidence,
        contradictions=contradictions,
        residual_loss=prepared.residual_loss,
    )


def _validate_report_evidence(report: InvestigationReport, result: CoreInvestigationResult) -> None:
    allowed = {item.evidence_id for item in (*result.evidence, *result.contradictions)}
    if any(
        evidence_id not in allowed
        for conclusion in report.conclusions
        for evidence_id in conclusion.evidence_ids
    ):
        raise ValueError("report contains unknown evidence IDs")
