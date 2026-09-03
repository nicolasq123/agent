from pathlib import Path

from fastapi.testclient import TestClient

from ad_rca.api.app import create_app
from ad_rca.application.investigation_service import build_fixture_service
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


def test_all_demo_scenarios_complete_via_http_and_replay_without_model(
    tmp_path: Path,
) -> None:
    sequence = iter(("run-cap", "run-pricing", "run-quality"))
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: next(sequence),
    )
    client = TestClient(create_app(service))
    incidents = client.get("/api/incidents").json()

    for incident in incidents:
        created = client.post(f"/api/incidents/{incident['incident_id']}/investigations").json()
        report = client.get(created["report_url"])
        events = client.get(created["events_url"])

        assert report.status_code == 200
        assert report.json()["generated_without_llm"] is True
        assert events.status_code == 200
        assert "event: report_generated" in events.text
