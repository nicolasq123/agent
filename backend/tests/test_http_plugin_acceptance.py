import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from ad_rca.api.dependencies import build_natural_language_service
from ad_rca.config import Settings
from ad_rca.infrastructure.database.backends import create_query_executor
from ad_rca.infrastructure.database.http_query import HttpQueryClient
from ad_rca.infrastructure.database.mysql_catalog import stat_query_specs


@pytest.mark.anyio
async def test_http_plugin_handles_both_sources_summary_and_profile_without_mysql(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    databases: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        databases.append(body["db"])
        assert request.headers["authorization"] == "Bearer token"
        if "AS ok" in body["sql"]:
            return httpx.Response(200, json={"rows": [{"ok": 1}]})
        if "non_hour_rows" in body["sql"]:
            return httpx.Response(200, json={"rows": [{"source_rows": 100}]})
        assert "2026-09-10" in body["sql"]
        assert "2026-09-11" in body["sql"]
        return httpx.Response(
            200,
            json={
                "rows": [
                    {
                        "source_rows": 100,
                        "revenue_rows": 100,
                        "payout_rows": 100,
                        "revenue": "10000000000000000.03",
                        "payout": "10000000000000000.01",
                        "first_dt": "2026-09-10 00:00:00",
                        "last_dt": "2026-09-10 23:00:00",
                    }
                ]
            },
        )

    def create(url: str, token: SecretStr, database: str) -> HttpQueryClient:
        return HttpQueryClient(url, token, database, transport=httpx.MockTransport(handle))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP plugin must never create a MySQL connection")

    monkeypatch.setattr("ad_rca.infrastructure.database.backends.HttpQueryClient", create)
    monkeypatch.setattr("ad_rca.infrastructure.database.backends.create_mysql_executor", forbidden)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_mode="readonly_db",
        model_mode="fake",
        query_backend="http",
        cli_timezone="UTC",
        http_query_url="http://test/v1/query",
        http_query_token=SecretStr("token"),
        auto_query_mode=1,
        artifacts_dir=tmp_path,
    )
    service = build_natural_language_service(settings)
    await service.check_database()
    analysis = await service.ask("分析2026-09-10的收入")
    assert "利润 0.02" in analysis.run.report.summary
    reader = create_query_executor(settings, "stat", stat_query_specs())
    await reader.query("stat_profile", {"window_start": "2026-09-10", "window_end": "2026-09-11"})
    assert databases == ["db20", "db40", "db20", "db20"]
