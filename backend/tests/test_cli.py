import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from ad_rca.cli import main

ROOT = Path(__file__).parents[2]


def test_cli_emits_evidence_backed_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["investigate", str(ROOT / "fixtures/demo/pricing_error.json"), "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["hypotheses"][0]["hypothesis"] == "payout_price_increase"
    assert payload["hypotheses"][0]["confidence"] == "confirmed"
    assert payload["evidence"]


def test_cli_reports_invalid_path_without_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["investigate", "/missing/scenario.json", "--format", "json"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "scenario file not found" in captured.err
    assert "Traceback" not in captured.err


def test_agent_cli_runs_langgraph_with_fake_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "agent",
            str(ROOT / "fixtures/demo/pricing_error.json"),
            "--model",
            "fake",
            "--artifacts-dir",
            str(tmp_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["report"]["generated_without_llm"] is True
    assert payload["events"][-1]["event_type"] == "report_generated"


class HealthyModelClient:
    def complete_json(self, system: str, user: str) -> str:
        return '{"status":"ok"}'


def test_model_check_never_prints_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "should-never-be-printed"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    exit_code = main(
        ["model-check"],
        model_client_factory=lambda settings: HealthyModelClient(),
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(output.out) == {"model": "deepseek-v4-flash", "status": "ok"}
    assert secret not in output.out
    assert secret not in output.err


def test_serve_command_builds_fixture_api_without_starting_real_server(
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def runner(app: FastAPI, host: str, port: int) -> None:
        observed.update(app=app, host=host, port=port)

    exit_code = main(
        [
            "serve",
            "--fixture-dir",
            str(ROOT / "fixtures/demo"),
            "--artifacts-dir",
            str(tmp_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
        ],
        server_runner=runner,
    )

    assert exit_code == 0
    assert isinstance(observed["app"], FastAPI)
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8123
