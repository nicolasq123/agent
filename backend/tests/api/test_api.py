import json
from pathlib import Path

from fastapi.testclient import TestClient

from ad_rca.api.app import create_app
from ad_rca.application.investigation_service import build_fixture_service
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


def _client(tmp_path: Path) -> TestClient:
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-api",
    )
    return TestClient(create_app(service))


def test_full_http_investigation_and_sse_replay(tmp_path: Path) -> None:
    client = _client(tmp_path)

    incidents_response = client.get("/api/incidents")
    assert incidents_response.status_code == 200
    incidents = incidents_response.json()
    assert len(incidents) == 3
    incident_id = incidents[0]["incident_id"]

    detail = client.get(f"/api/incidents/{incident_id}")
    assert detail.status_code == 200
    assert detail.json()["incident_id"] == incident_id

    detection = client.post("/api/detections/run")
    assert detection.status_code == 200
    assert len(detection.json()["incidents"]) == 3

    created = client.post(f"/api/incidents/{incident_id}/investigations")
    assert created.status_code == 201
    assert created.json()["run_id"] == "run-api"

    report = client.get("/api/investigations/run-api/report")
    assert report.status_code == 200
    assert report.json()["incident_id"] == incident_id

    events = client.get("/api/investigations/run-api/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    frames = [frame for frame in events.text.split("\n\n") if frame]
    payloads = [
        json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        for frame in frames
    ]
    assert payloads[0]["event_type"] == "baseline_loaded"
    assert payloads[-1]["event_type"] == "report_generated"

    answer = client.post(
        "/api/investigations/run-api/questions",
        json={"question": "为什么利润下降？"},
    )
    assert answer.status_code == 200
    assert "为什么利润下降" in answer.json()["answer"]


def test_api_returns_explicit_not_found_and_validation_errors(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/incidents/missing").status_code == 404
    assert client.post("/api/incidents/missing/investigations").status_code == 404
    assert client.get("/api/investigations/missing/report").status_code == 404
    assert client.get("/api/investigations/missing/events").status_code == 404
    assert (
        client.post("/api/investigations/missing/questions", json={"question": "x"}).status_code
        == 404
    )
    assert (
        client.post("/api/investigations/run/questions", json={"question": ""}).status_code == 422
    )


def test_post_endpoints_create_only_local_artifacts(tmp_path: Path) -> None:
    client = _client(tmp_path)
    incident_id = client.get("/api/incidents").json()[0]["incident_id"]

    created = client.post(f"/api/incidents/{incident_id}/investigations").json()
    assert client.get(created["report_url"]).status_code == 200

    run_directory = tmp_path / incident_id / "run-api"
    assert {path.name for path in run_directory.iterdir()} == {
        "evidence.json",
        "events.jsonl",
        "incident.json",
        "report.json",
    }
