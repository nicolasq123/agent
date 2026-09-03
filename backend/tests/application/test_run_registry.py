from pathlib import Path

import pytest

from ad_rca.application.investigation_service import build_fixture_service
from ad_rca.application.run_registry import RunRegistry
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


def test_registry_returns_registered_run(tmp_path: Path) -> None:
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-registered",
    )
    incident = service.list_incidents()[0]
    run = service.start_investigation(incident.incident_id)
    registry = RunRegistry()

    registry.add(run)

    assert registry.get("run-registered") == run


def test_registry_rejects_duplicate_run_ids(tmp_path: Path) -> None:
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-duplicate",
    )
    incident = service.list_incidents()[0]
    run = service.start_investigation(incident.incident_id)
    registry = RunRegistry()
    registry.add(run)

    with pytest.raises(ValueError, match="already exists"):
        registry.add(run)
