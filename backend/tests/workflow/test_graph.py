from pathlib import Path

from ad_rca.agent.models import (
    InvestigationPlan,
    InvestigationReport,
    PlanningRequest,
    ReportConclusion,
    ReportRequest,
)
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.enums import Confidence, HypothesisType
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import ModelUnavailableError
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.workflow.graph import InvestigationWorkflow


def _service(name: str = "pricing_error") -> CoreRcaService:
    repository = FixtureRepository.load(Path(f"../fixtures/demo/{name}.json"))
    return CoreRcaService(repository, default_verifiers())


def test_graph_runs_bounded_investigation_and_persists_replayable_events(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    workflow = InvestigationWorkflow(
        _service(), FakePlanner(), TemplateReportComposer(), artifact_store=store
    )

    run = workflow.run("pricing_error", run_id="run-pricing")

    assert run.report is not None
    assert run.report.generated_without_llm is True
    assert run.rounds <= 2
    event_types = [event.event_type for event in run.events]
    assert event_types == sorted(event_types, key=run.expected_event_order)
    assert "baseline_loaded" in event_types
    assert "attribution_completed" in event_types
    assert "hypothesis_generated" in event_types
    assert "verifier_started" in event_types
    assert "evidence_found" in event_types
    assert "root_cause_confirmed" in event_types
    assert event_types[-1] == "report_generated"
    assert store.read_report("run-pricing") == run.report
    assert store.read_events("run-pricing") == run.events


class UnavailablePlanner:
    def plan(self, request: PlanningRequest) -> InvestigationPlan:
        raise ModelUnavailableError("offline")


def test_graph_degrades_to_deterministic_planner_when_model_is_unavailable(
    tmp_path: Path,
) -> None:
    workflow = InvestigationWorkflow(
        _service(),
        UnavailablePlanner(),
        TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )

    run = workflow.run("pricing_error", run_id="run-fallback")

    assert run.report is not None
    assert run.report.generated_without_llm is True
    assert "LLM_UNAVAILABLE" in run.warnings
    assert run.result.hypotheses


class SequentialPlanner:
    def plan(self, request: PlanningRequest) -> InvestigationPlan:
        hypothesis = (
            HypothesisType.TRAFFIC_VOLUME_DROP
            if request.round_number == 1
            else HypothesisType.TRAFFIC_MIX_SHIFT
        )
        return InvestigationPlan(hypotheses=(hypothesis,), rationale="bounded round")


def test_graph_stops_after_second_round_when_first_round_is_inconclusive(
    tmp_path: Path,
) -> None:
    workflow = InvestigationWorkflow(
        _service("cap_mix_shift"),
        SequentialPlanner(),
        TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )

    run = workflow.run("cap_mix_shift", run_id="run-two-rounds")

    assert run.rounds == 2
    assert [item.hypothesis for item in run.result.hypotheses] == [
        HypothesisType.TRAFFIC_VOLUME_DROP,
        HypothesisType.TRAFFIC_MIX_SHIFT,
    ]


class InventingComposer(TemplateReportComposer):
    def compose(self, request: ReportRequest) -> InvestigationReport:
        assert request.result.incident is not None
        return InvestigationReport(
            run_id=request.run_id,
            incident_id=request.result.incident.incident_id,
            summary="invented",
            conclusions=(
                ReportConclusion(
                    hypothesis=HypothesisType.PAYOUT_PRICE_INCREASE,
                    confidence=Confidence.CONFIRMED,
                    statement="invented",
                    evidence_ids=("ev-invented",),
                    explained_loss=900,
                ),
            ),
        )


def test_graph_replaces_report_that_invents_evidence(tmp_path: Path) -> None:
    workflow = InvestigationWorkflow(
        _service(),
        FakePlanner(),
        InventingComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )

    run = workflow.run("pricing_error", run_id="run-invalid-report")

    assert run.report.generated_without_llm is True
    assert "INVALID_LLM_OUTPUT" in run.warnings
    assert run.report.conclusions[0].evidence_ids != ("ev-invented",)
