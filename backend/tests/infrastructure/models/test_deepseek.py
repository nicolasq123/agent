import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from ad_rca.agent.models import PlanningRequest, ReportRequest
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.infrastructure.models.deepseek import (
    DeepSeekPlanner,
    DeepSeekReportComposer,
    OpenAIJsonClient,
)


class RecordingJsonClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.requests.append((system, user))
        return self.responses.pop(0)


def test_openai_compatible_client_sends_expected_deepseek_http_contract() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["authorization"] = request.headers["authorization"]
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"status":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAIJsonClient(
        api_key=SecretStr("test-secret"),
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout_seconds=10,
        http_client=http_client,
    )

    response = client.complete_json("system", "user")

    assert response == '{"status":"ok"}'
    assert observed["path"] == "/chat/completions"
    assert observed["authorization"] == "Bearer test-secret"
    assert observed["payload"] == {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "model": "deepseek-v4-flash",
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }


def _prepared_and_result():
    repository = FixtureRepository.load(Path("../fixtures/demo/pricing_error.json"))
    service = CoreRcaService(repository, default_verifiers())
    prepared = service.prepare(repository.scenario_id)
    result = service.verify(prepared, prepared.candidates[:3])
    return prepared, result


def test_deepseek_planner_accepts_only_offered_hypotheses_and_sends_aggregates() -> None:
    prepared, _ = _prepared_and_result()
    assert prepared.incident is not None
    client = RecordingJsonClient(
        ['{"hypotheses":["payout_price_increase"],"rationale":"direct signal"}']
    )

    plan = DeepSeekPlanner(client).plan(
        PlanningRequest(
            incident=prepared.incident,
            candidates=prepared.candidates,
            attributions=prepared.attributions,
        )
    )

    assert plan.hypotheses == (prepared.candidates[0],)
    payload: Mapping[str, Any] = json.loads(client.requests[0][1])
    assert set(payload) == {"incident", "candidates", "attributions", "round_number"}
    serialized = client.requests[0][1].lower()
    assert "api_key" not in serialized
    assert "select " not in serialized
    assert "performance" not in serialized
    assert "response schema" in client.requests[0][0].lower()
    assert "hypotheses" in client.requests[0][0]


def test_deepseek_planner_repairs_invalid_json_once() -> None:
    prepared, _ = _prepared_and_result()
    assert prepared.incident is not None
    client = RecordingJsonClient(
        [
            "not-json",
            '{"hypotheses":["payout_price_increase"],"rationale":"repaired"}',
        ]
    )

    plan = DeepSeekPlanner(client).plan(
        PlanningRequest(
            incident=prepared.incident,
            candidates=prepared.candidates,
            attributions=prepared.attributions,
        )
    )

    assert plan.rationale == "repaired"
    assert len(client.requests) == 2


def test_deepseek_report_rejects_invented_evidence_then_repairs() -> None:
    _, result = _prepared_and_result()
    assert result.incident is not None
    valid_evidence_id = result.evidence[0].evidence_id
    invalid: dict[str, Any] = {
        "run_id": "run-1",
        "incident_id": result.incident.incident_id,
        "summary": "invalid",
        "conclusions": [
            {
                "hypothesis": "payout_price_increase",
                "confidence": "confirmed",
                "statement": "invented",
                "evidence_ids": ["ev-invented"],
                "explained_loss": 900,
            }
        ],
    }
    valid: dict[str, Any] = {
        **invalid,
        "summary": "validated",
        "conclusions": [{**invalid["conclusions"][0], "evidence_ids": [valid_evidence_id]}],
    }
    client = RecordingJsonClient([json.dumps(invalid), json.dumps(valid)])

    report = DeepSeekReportComposer(client).compose(ReportRequest(run_id="run-1", result=result))

    assert report.summary == "validated"
    assert report.generated_without_llm is False
    assert len(client.requests) == 2
