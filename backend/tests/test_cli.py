import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.agent.models import QuestionAnswer
from ad_rca.application.investigation_service import build_fixture_service
from ad_rca.application.natural_language_service import (
    AnalysisDataQualityError,
    NaturalLanguageAnalysis,
)
from ad_rca.application.scope_discovery import (
    InsufficientComparableHistoryError,
    NoCurrentDataError,
)
from ad_rca.cli import main, safe_error_message
from ad_rca.infrastructure.database.mysql import QueryApprovalRejected
from ad_rca.infrastructure.database.query_budget import QueryBudgetExceeded
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer

ROOT = Path(__file__).parents[2]


class FakeNaturalService:
    def __init__(self, analysis: NaturalLanguageAnalysis) -> None:
        self.analysis = analysis
        self.asked: list[str] = []
        self.answered: list[str] = []
        self.checked = False

    async def ask(
        self,
        question: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> NaturalLanguageAnalysis:
        self.asked.append(question)
        if progress is not None:
            progress("测试进度")
        return self.analysis

    def answer(self, analysis: NaturalLanguageAnalysis, question: str) -> QuestionAnswer:
        assert analysis is self.analysis
        self.answered.append(question)
        return QuestionAnswer(answer="补充回答", evidence_ids=())

    async def check_database(self) -> None:
        self.checked = True


class FailingNaturalService(FakeNaturalService):
    async def ask(
        self,
        question: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> NaturalLanguageAnalysis:
        raise TimeoutError("database-secret at db20")


def _natural_service(tmp_path: Path) -> FakeNaturalService:
    fixture_service = build_fixture_service(
        ROOT / "fixtures/demo",
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-cli-natural",
    )
    incident = fixture_service.list_incidents()[0]
    run = fixture_service.start_investigation(incident.incident_id)
    intent = AnalysisIntent(
        question="分析昨天利润",
        window=incident.window,
        scope=incident.scope,
        timezone="UTC",
    )
    return FakeNaturalService(
        NaturalLanguageAnalysis(intent=intent, selected_scope=incident.scope, run=run)
    )


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


def test_ask_prints_markdown_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _natural_service(tmp_path)

    code = main(
        ["ask", "分析昨天 offer 12345 为什么利润下降"],
        natural_service_factory=lambda settings: service,
    )

    output = capsys.readouterr()
    assert code == 0
    assert "利润损失" in output.out
    assert "Evidence" in output.out
    assert service.asked == ["分析昨天 offer 12345 为什么利润下降"]


def test_ask_json_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _natural_service(tmp_path)

    code = main(
        ["ask", "分析昨天利润", "--json"],
        natural_service_factory=lambda settings: service,
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["run"]["report"]


def test_chat_reuses_current_analysis_and_handles_local_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _natural_service(tmp_path)
    lines: Iterator[str] = iter(("分析昨天利润", "还有哪些证据？", "/new", "/exit"))

    code = main(
        ["chat"],
        natural_service_factory=lambda settings: service,
        line_reader=lambda prompt: next(lines),
    )

    assert code == 0
    assert service.asked == ["分析昨天利润"]
    assert service.answered == ["还有哪些证据？"]
    output = capsys.readouterr().out
    assert "[分析] 测试进度" in output
    assert "补充回答" in output


def test_db_check_prints_no_connection_secrets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _natural_service(tmp_path)
    secret = "database-secret"

    code = main(
        ["db-check"],
        natural_service_factory=lambda settings: service,
    )

    output = capsys.readouterr()
    assert code == 0
    assert service.checked is True
    assert "DB20 au_stat: ok" in output.out
    assert "DB40 ymgw: ok" in output.out
    assert secret not in output.out + output.err


def test_ask_sanitizes_database_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FailingNaturalService(_natural_service(tmp_path).analysis)

    code = main(
        ["ask", "分析昨天利润"],
        natural_service_factory=lambda settings: service,
    )

    output = capsys.readouterr()
    assert code == 2
    assert "[DB_TIMEOUT]" in output.err
    assert "database-secret" not in output.err


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NoCurrentDataError(), "[DATA_NO_CURRENT]"),
        (InsufficientComparableHistoryError(), "[DATA_HISTORY_INSUFFICIENT]"),
        (AnalysisDataQualityError(), "[DATA_QUALITY_BLOCKED]"),
        (QueryApprovalRejected(), "[QUERY_REJECTED]"),
        (QueryBudgetExceeded(), "[QUERY_BUDGET_EXCEEDED]"),
        (TimeoutError(), "[DB_TIMEOUT]"),
        (
            OperationalError("SELECT 1", {}, Exception(1045, "database-secret")),
            "[DB_AUTH_FAILED]",
        ),
        (
            OperationalError("SELECT 1", {}, Exception(1146, "database-secret")),
            "[DB_TABLE_MISSING]",
        ),
    ],
)
def test_safe_errors_have_distinct_codes_without_database_details(
    error: Exception, code: str
) -> None:
    message = safe_error_message(error)

    assert message.startswith(code)
    assert "database-secret" not in message


def test_chat_stays_open_after_query_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = FailingNaturalService(_natural_service(tmp_path).analysis)
    lines = iter(("分析昨天利润", "/exit"))
    code = main(
        ["chat"],
        natural_service_factory=lambda settings: service,
        line_reader=lambda prompt: next(lines),
    )
    assert code == 0
    assert "DB_TIMEOUT" in capsys.readouterr().err


def test_db_profile_outputs_diagnostics_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.data.test_mysql_snapshot import RecordingReader

    reader = RecordingReader({"stat_profile": ({"source_rows": 100, "non_hour_rows": 0},)})

    def create(url: str, *args: object, **kwargs: object) -> RecordingReader:
        return reader

    monkeypatch.setenv("MYSQL_STAT_URL", "mysql+asyncmy://readonly:hidden@localhost/db")
    monkeypatch.setattr("ad_rca.infrastructure.database.backends.create_mysql_executor", create)
    assert main(["db-profile"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["profile"][0]["source_rows"] == 100
    assert "hidden" not in output.out + output.err
    assert reader.calls[0][0] == "stat_profile"
