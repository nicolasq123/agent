import json
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from ad_rca.config import Settings
from ad_rca.infrastructure.database.http_query import (
    HttpQueryClient,
    HttpQueryError,
    decode_rows,
    render_query,
)
from ad_rca.infrastructure.database.mysql import ReadonlyMySqlExecutor
from ad_rca.infrastructure.database.mysql_catalog import config_query_specs, stat_query_specs
from ad_rca.infrastructure.database.sql_guard import validate_readonly_sql


@pytest.mark.anyio
async def test_http_uses_bearer_db_and_bound_sql_and_preserves_decimal() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://test/v1/query"
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["db"] == "db20"
        assert set(body) == {"db", "sql"}
        assert ":window_start" not in body["sql"]
        assert "2026-09-10" in body["sql"]
        return httpx.Response(
            200,
            content=(
                b'{"rows":[{"revenue":10000000000000000.03,"payout":"0.01",'
                b'"event_hour":"2026-09-10 00:00:00"}]}'
            ),
        )

    client = HttpQueryClient(
        "http://test/v1/query",
        SecretStr("test-token"),
        "db20",
        transport=httpx.MockTransport(handle),
    )
    reader = ReadonlyMySqlExecutor(client, stat_query_specs(), auto_query_mode=1)
    rows = await reader.query(
        "period_totals",
        {
            "window_start": datetime(2026, 9, 10),
            "window_end": datetime(2026, 9, 11),
            "advertiser_id": None,
            "offer_id": "123",
            "channel_id": None,
            "country": "US",
        },
    )
    assert rows[0]["revenue"] == Decimal("10000000000000000.03")
    assert rows[0]["event_hour"] == datetime(2026, 9, 10)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [301, 401, 403, 500])
async def test_http_failures_hide_credentials_and_response_body(status: int) -> None:
    client = HttpQueryClient(
        "http://test/v1/query",
        SecretStr("test-token"),
        "db20",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret-server-details")
        ),
    )
    with pytest.raises(HttpQueryError) as error:
        await ReadonlyMySqlExecutor(client, stat_query_specs(), auto_query_mode=1).check()
    assert "test-token" not in str(error.value)
    assert "secret-server-details" not in str(error.value)


def test_http_settings_do_not_require_mysql_credentials() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_mode="readonly_db",
        model_mode="fake",
        query_backend="http",
        http_query_url="http://test/v1/query",
        http_query_token=SecretStr("test-token"),
    )
    assert settings.mysql_stat_url is None
    assert settings.query_backend == "http"


def test_all_fixed_catalog_queries_remain_readonly_after_http_binding() -> None:
    for spec in (*stat_query_specs().values(), *config_query_specs().values()):
        parameters = {name: None for name in spec.parameters}
        rendered = render_query(spec.sql, parameters)
        validate_readonly_sql(
            rendered,
            dialect="mysql",
            allowed_tables=spec.allowed_tables,
            allowed_columns=spec.allowed_columns,
            max_result_rows=spec.max_result_rows,
        )


def test_binding_does_not_turn_text_into_sql() -> None:
    value = "US\\'; DROP TABLE stat; -- 中文"
    sql = render_query(
        "SELECT :value AS v, :value AS again, :empty AS empty LIMIT 1",
        {"value": value, "empty": None},
    )
    assert "DROP" not in sql
    assert ";" not in sql
    assert value.encode().hex() in sql
    assert "NULL AS `empty`" in sql
    with pytest.raises(ValueError, match="parameters"):
        render_query("SELECT :x LIMIT 1", {})
    with pytest.raises(ValueError, match="type"):
        render_query("SELECT :x LIMIT 1", {"x": ["unsafe"]})


@pytest.mark.parametrize(
    "body,code",
    [
        (b"not json", "FORMAT"),
        (b"[]", "FORMAT"),
        (b"{}", "FORMAT"),
        (b'{"rows":[1]}', "FORMAT"),
        (b'{"rows":[{"a":[]}]}', "FORMAT"),
        (b'{"rows":[{"event_hour":"not-a-date"}]}', "DATETIME"),
        (b'{"rows":[],"has_more":true}', "INCOMPLETE"),
        (b'{"rows":[],"error":"private details"}', "REMOTE_ERROR"),
    ],
)
def test_invalid_or_incomplete_responses_are_not_silent_empty_results(
    body: bytes, code: str
) -> None:
    with pytest.raises(HttpQueryError, match=code):
        decode_rows(body)


@pytest.mark.anyio
async def test_approval_rejection_never_sends_http_request() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("rejected queries must not reach HTTP")

    client = HttpQueryClient(
        "http://test/v1/query",
        SecretStr("token"),
        "db20",
        transport=httpx.MockTransport(unexpected),
    )
    reader = ReadonlyMySqlExecutor(
        client, stat_query_specs(), approver=lambda name, sql, parameters: False
    )
    with pytest.raises(RuntimeError, match="approved"):
        await reader.check()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure,code", [(httpx.ReadTimeout, "TIMEOUT"), (httpx.ConnectError, "CONNECTION")]
)
async def test_network_errors_are_sanitized(failure: type[httpx.RequestError], code: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise failure("private-token-and-url", request=request)

    client = HttpQueryClient(
        "http://test/v1/query", SecretStr("token"), "db20", transport=httpx.MockTransport(fail)
    )
    with pytest.raises(HttpQueryError, match=code) as error:
        await client.fetch_all("SELECT 1 LIMIT 1", {}, 1)
    assert "private" not in str(error.value)


@pytest.mark.anyio
async def test_response_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ad_rca.infrastructure.database.http_query.MAX_RESPONSE_BYTES", 10)
    client = HttpQueryClient(
        "http://test/v1/query",
        SecretStr("token"),
        "db20",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 11)),
    )
    with pytest.raises(HttpQueryError, match="TOO_LARGE"):
        await client.fetch_all("SELECT 1 LIMIT 1", {}, 1)
