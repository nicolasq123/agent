from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ad_rca.agent.contracts import InvestigationPlanner, ReportComposer
from ad_rca.agent.models import InvestigationReport, QuestionAnswer, QuestionRequest
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.application.run_registry import RunRegistry
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.domain.models import Incident
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.deepseek import (
    InvalidModelOutputError,
    ModelUnavailableError,
)
from ad_rca.infrastructure.models.fake import TemplateReportComposer
from ad_rca.workflow.events import WorkflowEvent
from ad_rca.workflow.graph import InvestigationWorkflow, WorkflowRun


@dataclass(frozen=True)
class FixtureIncident:
    incident: Incident
    scenario_id: str
    repository: FixtureRepository


class InvestigationService:
    def __init__(
        self,
        incidents: tuple[FixtureIncident, ...],
        artifact_store: ArtifactStore,
        planner: InvestigationPlanner,
        composer: ReportComposer,
        *,
        registry: RunRegistry | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._incidents = {item.incident.incident_id: item for item in incidents}
        self._artifacts = artifact_store
        self._planner = planner
        self._composer = composer
        self._fallback_composer = TemplateReportComposer()
        self._registry = registry or RunRegistry()
        self._id_factory = id_factory or (lambda: f"run-{uuid4().hex}")

    def list_incidents(self) -> tuple[Incident, ...]:
        return tuple(
            item.incident
            for item in sorted(self._incidents.values(), key=lambda value: value.scenario_id)
        )

    def run_detection(self) -> tuple[Incident, ...]:
        return self.list_incidents()

    def get_incident(self, incident_id: str) -> Incident:
        entry = self._incidents.get(incident_id)
        if entry is None:
            raise KeyError(incident_id)
        return entry.incident

    def start_investigation(self, incident_id: str) -> WorkflowRun:
        entry = self._incidents.get(incident_id)
        if entry is None:
            raise KeyError(incident_id)
        run_id = self._id_factory()
        workflow = InvestigationWorkflow(
            CoreRcaService(entry.repository, default_verifiers()),
            self._planner,
            self._composer,
            artifact_store=self._artifacts,
        )
        run = workflow.run(entry.scenario_id, run_id=run_id)
        self._registry.add(run)
        return run

    def get_report(self, run_id: str) -> InvestigationReport:
        run = self._registry.get(run_id)
        if run is not None:
            return run.report
        return self._artifacts.read_report(run_id)

    def get_events(self, run_id: str) -> tuple[WorkflowEvent, ...]:
        run = self._registry.get(run_id)
        if run is not None:
            return run.events
        return self._artifacts.read_events(run_id)

    def answer_question(self, run_id: str, question: str) -> QuestionAnswer:
        report = self.get_report(run_id)
        request = QuestionRequest(question=question, report=report)
        try:
            answer = self._composer.answer(request)
            _validate_answer_evidence(answer, report)
            return answer
        except (ModelUnavailableError, InvalidModelOutputError, ValueError):
            return self._fallback_composer.answer(request)


def build_fixture_service(
    fixture_dir: Path,
    artifacts_dir: Path,
    planner: InvestigationPlanner,
    composer: ReportComposer,
    *,
    registry: RunRegistry | None = None,
    id_factory: Callable[[], str] | None = None,
) -> InvestigationService:
    incidents: list[FixtureIncident] = []
    for path in sorted(fixture_dir.glob("*.json")):
        repository = FixtureRepository.load(path)
        prepared = CoreRcaService(repository, default_verifiers()).prepare(repository.scenario_id)
        if prepared.incident is not None:
            incidents.append(
                FixtureIncident(
                    incident=prepared.incident,
                    scenario_id=repository.scenario_id,
                    repository=repository,
                )
            )
    return InvestigationService(
        tuple(incidents),
        ArtifactStore(artifacts_dir),
        planner,
        composer,
        registry=registry,
        id_factory=id_factory,
    )


def _validate_answer_evidence(
    answer: QuestionAnswer, report: InvestigationReport
) -> None:
    allowed = {
        evidence_id for conclusion in report.conclusions for evidence_id in conclusion.evidence_ids
    }
    if any(evidence_id not in allowed for evidence_id in answer.evidence_ids):
        raise ValueError("answer contains evidence outside the current incident report")
