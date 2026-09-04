import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ad_rca.application.natural_language_service import NaturalLanguageAnalysisService
from ad_rca.cli import main
from ad_rca.data.mysql_snapshot import MySqlSnapshotLoader
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.database.mysql import ReadonlyMySqlExecutor
from ad_rca.infrastructure.database.mysql_catalog import config_query_specs, stat_query_specs
from ad_rca.infrastructure.database.query_budget import QueryBudget
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.infrastructure.models.intent import RuleIntentParser

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 4, 12, tzinfo=TZ)
START = datetime(2026, 9, 3, tzinfo=TZ)
SECRET = "must-not-appear-in-output"


class RecordingClient:
    def __init__(self, *, discovery: bool = False) -> None:
        self.discovery = discovery
        self.calls: list[tuple[str, Mapping[str, object], float]] = []

    async def fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object],
        timeout_seconds: float,
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, parameters, timeout_seconds))
        if "FROM au_stat.stat" not in query:
            return ()
        if "AS dimension_value" not in query:
            return _scoped_performance()
        dimension, value = _query_dimension(query)
        if "event_hour" not in query:
            return ({"dimension_value": value},)
        losses = {"advertiser_id": 50, "offer_id": 300, "channel_id": 150, "country": 100}
        return _discovery_series(value, losses[dimension] if self.discovery else 300)


def _query_dimension(query: str) -> tuple[str, object]:
    if "ader_id AS dimension_value" in query:
        return "advertiser_id", 9
    if "oid_ AS dimension_value" in query:
        return "offer_id", 12345
    if "aid AS dimension_value" in query:
        return "channel_id", 678
    return "country", "US"


def _hours() -> tuple[datetime, ...]:
    return tuple(
        START + timedelta(hours=hour) - timedelta(weeks=week)
        for week in range(1, 9)
        for hour in range(24)
    ) + tuple(START + timedelta(hours=hour) for hour in range(24))


def _scoped_performance() -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for event_hour in _hours():
        current = event_hour >= START
        rows.append(
            {
                "event_hour": event_hour.replace(tzinfo=None),
                "advertiser_id": 9,
                "offer_id": 12345,
                "channel_id": 678,
                "country": "US",
                "clk_os": 2,
                "carrier": 1,
                "clicks": 1000,
                "invalid_clicks": 5,
                "conversions": 100,
                "settled_conversions": 90,
                "revenue": 1000,
                "payout": 900 if current else 600,
            }
        )
    return tuple(rows)


def _discovery_series(value: object, hourly_loss: float) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "event_hour": event_hour.replace(tzinfo=None),
            "dimension_value": value,
            "clicks": 1000,
            "conversions": 100,
            "revenue": 1000,
            "payout": 600 + hourly_loss if event_hour >= START else 600,
        }
        for event_hour in _hours()
    )


def _service(
    tmp_path: Path, *, discovery: bool = False
) -> tuple[NaturalLanguageAnalysisService, RecordingClient, RecordingClient]:
    stat_client = RecordingClient(discovery=discovery)
    config_client = RecordingClient()
    budget = QueryBudget(max_queries=20)
    loader = MySqlSnapshotLoader(
        ReadonlyMySqlExecutor(stat_client, stat_query_specs(), budget, auto_query_mode=1),
        ReadonlyMySqlExecutor(config_client, config_query_specs(), budget, auto_query_mode=1),
        stat_timezone="Asia/Shanghai",
        query_budget=budget,
    )
    service = NaturalLanguageAnalysisService(
        parser=RuleIntentParser(timezone="Asia/Shanghai", now=lambda: NOW),
        loader=loader,
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
        id_factory=lambda: "run-acceptance",
    )
    return service, stat_client, config_client


def test_one_sentence_runs_the_readonly_mysql_rca_workflow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service, stat_client, config_client = _service(tmp_path)

    code = main(
        ["ask", "分析昨天 offer 12345 为什么利润下降", "--json"],
        natural_service_factory=lambda settings: service,
    )

    payload = json.loads(capsys.readouterr().out)
    calls = stat_client.calls + config_client.calls
    assert code == 0
    assert payload["intent"]["scope"]["offer_id"] == "12345"
    assert payload["run"]["report"]["conclusions"]
    assert payload["run"]["result"]["evidence"]
    assert all(call[0].lstrip().upper().startswith("SELECT") for call in calls)
    assert len(calls) <= 20
    assert SECRET not in json.dumps(payload)


def test_unscoped_question_discovers_the_largest_loss_offer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service, stat_client, config_client = _service(tmp_path, discovery=True)

    code = main(
        ["ask", "分析昨天整体利润为什么下降", "--json"],
        natural_service_factory=lambda settings: service,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["selected_scope"] == {
        "advertiser_id": None,
        "offer_id": "12345",
        "channel_id": None,
        "country": None,
    }
    assert len(stat_client.calls) + len(config_client.calls) == 13


def test_chat_follow_up_cites_the_current_investigation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service, _, _ = _service(tmp_path)
    lines = iter(("分析昨天 offer 12345 为什么利润下降", "还有哪些证据？", "/exit"))

    code = main(
        ["chat"],
        natural_service_factory=lambda settings: service,
        line_reader=lambda prompt: next(lines),
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "Evidence IDs" in output
    assert "当前回答基于已完成调查报告" in output
