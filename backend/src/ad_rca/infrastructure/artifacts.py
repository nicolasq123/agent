import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from ad_rca.agent.models import InvestigationReport
from ad_rca.domain.models import CoreInvestigationResult, Incident
from ad_rca.workflow.events import WorkflowEvent

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write_incident(self, incident_id: str, run_id: str, incident: Incident) -> None:
        self._write_model(incident_id, run_id, "incident.json", incident)

    def write_result(self, incident_id: str, run_id: str, result: CoreInvestigationResult) -> None:
        self._write_model(incident_id, run_id, "evidence.json", result)

    def write_report(self, incident_id: str, run_id: str, report: InvestigationReport) -> None:
        self._write_model(incident_id, run_id, "report.json", report)

    def write_events(self, incident_id: str, run_id: str, events: Iterable[WorkflowEvent]) -> None:
        directory = self._directory(incident_id, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        event_path = directory / "events.jsonl"
        ordered = sorted(events, key=lambda item: item.sequence)
        with event_path.open("a", encoding="utf-8") as stream:
            for event in ordered:
                stream.write(event.model_dump_json() + "\n")

    def read_report(self, run_id: str) -> InvestigationReport:
        path = self._find_run_file(run_id, "report.json")
        return InvestigationReport.model_validate_json(path.read_bytes())

    def read_events(self, run_id: str) -> tuple[WorkflowEvent, ...]:
        path = self._find_run_file(run_id, "events.jsonl")
        events = tuple(
            WorkflowEvent.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        return tuple(sorted(events, key=lambda item: item.sequence))

    def _write_model(self, incident_id: str, run_id: str, name: str, model: BaseModel) -> None:
        directory = self._directory(incident_id, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        temporary = directory / f".{name}.tmp"
        temporary.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)

    def _directory(self, incident_id: str, run_id: str) -> Path:
        _validate_identifier(incident_id)
        _validate_identifier(run_id)
        return self._root / incident_id / run_id

    def _find_run_file(self, run_id: str, name: str) -> Path:
        _validate_identifier(run_id)
        matches = tuple(self._root.glob(f"*/{run_id}/{name}"))
        if len(matches) != 1:
            raise FileNotFoundError(f"artifact not found for run {run_id}")
        return matches[0]


def _validate_identifier(value: str) -> None:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("unsafe artifact identifier")
