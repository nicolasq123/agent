from collections.abc import Mapping, Sequence
from io import StringIO
from typing import Literal

import pytest

from ad_rca.infrastructure.database.clickhouse import ReadonlyClickHouseExecutor
from ad_rca.infrastructure.database.mysql import ReadonlyMySqlExecutor, TerminalQueryApprover
from ad_rca.infrastructure.database.query_specs import QuerySpec


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordingClickHouseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object], Mapping[str, object]]] = []

    def query(
        self,
        query: str,
        parameters: Mapping[str, object],
        settings: Mapping[str, object],
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, parameters, settings))
        return ({"offer_id": "offer-a"},)


class RecordingMySqlClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object], float]] = []

    async def fetch_all(
        self, query: str, parameters: Mapping[str, object], timeout_seconds: float
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, parameters, timeout_seconds))
        return ({"offer_id": "offer-a"},)


class InvalidHealthMySqlClient(RecordingMySqlClient):
    async def fetch_all(
        self, query: str, parameters: Mapping[str, object], timeout_seconds: float
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, parameters, timeout_seconds))
        return ({"ok": 0},)


class ValidHealthMySqlClient(RecordingMySqlClient):
    async def fetch_all(
        self, query: str, parameters: Mapping[str, object], timeout_seconds: float
    ) -> Sequence[Mapping[str, object]]:
        self.calls.append((query, parameters, timeout_seconds))
        return ({"ok": 1},)


def _spec(dialect: Literal["mysql", "clickhouse"]) -> QuerySpec:
    return QuerySpec(
        name="performance",
        dialect=dialect,
        sql="SELECT offer_id FROM ad_hourly_performance WHERE event_hour >= :start LIMIT 10",
        allowed_tables=frozenset({"ad_hourly_performance"}),
        allowed_columns=frozenset({"offer_id", "event_hour"}),
        parameters=frozenset({"start"}),
    )


def test_terminal_query_approver_shows_fixed_sql_and_parameters() -> None:
    output = StringIO()
    approver = TerminalQueryApprover(reader=lambda: "y", output=output)

    approved = approver(
        "performance",
        "SELECT offer_id FROM stat LIMIT 10",
        {"offer_id": 12345},
    )

    rendered = output.getvalue()
    assert approved is True
    assert "performance" in rendered
    assert "SELECT offer_id FROM stat LIMIT 10" in rendered
    assert '"offer_id": 12345' in rendered


def test_terminal_query_approver_rejects_non_y_and_end_of_input() -> None:
    output = StringIO()

    assert (
        TerminalQueryApprover(reader=lambda: "no", output=output)("health", "SELECT 1", {}) is False
    )

    def end_of_input() -> str:
        raise EOFError

    assert (
        TerminalQueryApprover(reader=end_of_input, output=output)("health", "SELECT 1", {}) is False
    )


def test_clickhouse_executor_enforces_readonly_settings_and_fixed_parameters() -> None:
    client = RecordingClickHouseClient()
    executor = ReadonlyClickHouseExecutor(client, {"performance": _spec("clickhouse")})

    rows = executor.query("performance", {"start": "2026-09-03T00:00:00Z"})

    assert rows == ({"offer_id": "offer-a"},)
    assert client.calls[0][2] == {
        "readonly": 2,
        "max_result_rows": 10000,
        "result_overflow_mode": "throw",
        "max_execution_time": 10,
    }


@pytest.mark.anyio
async def test_mysql_executor_sends_only_validated_fixed_query() -> None:
    client = RecordingMySqlClient()
    executor = ReadonlyMySqlExecutor(client, {"performance": _spec("mysql")}, auto_query_mode=1)

    rows = await executor.query("performance", {"start": "2026-09-03T00:00:00Z"})

    assert rows == ({"offer_id": "offer-a"},)
    assert client.calls[0][2] == 10.0


@pytest.mark.anyio
async def test_mysql_executor_does_not_call_database_when_query_is_rejected() -> None:
    client = RecordingMySqlClient()
    executor = ReadonlyMySqlExecutor(
        client,
        {"performance": _spec("mysql")},
        approver=lambda name, sql, parameters: False,
    )

    with pytest.raises(RuntimeError, match="not approved"):
        await executor.query("performance", {"start": "2026-09-03T00:00:00Z"})

    assert client.calls == []


@pytest.mark.anyio
async def test_mysql_executor_calls_database_after_query_is_approved() -> None:
    client = RecordingMySqlClient()
    executor = ReadonlyMySqlExecutor(
        client,
        {"performance": _spec("mysql")},
        approver=lambda name, sql, parameters: True,
    )

    rows = await executor.query("performance", {"start": "2026-09-03T00:00:00Z"})

    assert rows == ({"offer_id": "offer-a"},)
    assert len(client.calls) == 1


@pytest.mark.anyio
async def test_auto_query_mode_one_does_not_request_approval() -> None:
    client = RecordingMySqlClient()

    def unexpected_approval(name: str, sql: str, parameters: Mapping[str, object]) -> bool:
        raise AssertionError("automatic mode must not request approval")

    executor = ReadonlyMySqlExecutor(
        client,
        {"performance": _spec("mysql")},
        auto_query_mode=1,
        approver=unexpected_approval,
    )

    await executor.query("performance", {"start": "2026-09-03T00:00:00Z"})

    assert len(client.calls) == 1


def test_clickhouse_rejects_unknown_queries_and_parameter_mismatch() -> None:
    executor = ReadonlyClickHouseExecutor(
        RecordingClickHouseClient(), {"performance": _spec("clickhouse")}
    )

    with pytest.raises(ValueError):
        executor.query("unknown", {})
    with pytest.raises(ValueError, match="parameters"):
        executor.query("performance", {"unexpected": 1})


def test_database_executors_expose_no_write_or_raw_execution_api() -> None:
    forbidden = {
        "command",
        "delete",
        "drop",
        "execute",
        "insert",
        "raw_connection",
        "update",
    }

    for executor_type in (ReadonlyClickHouseExecutor, ReadonlyMySqlExecutor):
        assert forbidden.isdisjoint(dir(executor_type))


@pytest.mark.anyio
async def test_mysql_rejects_unknown_queries_and_parameter_mismatch() -> None:
    executor = ReadonlyMySqlExecutor(
        RecordingMySqlClient(), {"performance": _spec("mysql")}, auto_query_mode=1
    )

    with pytest.raises(ValueError):
        await executor.query("unknown", {})
    with pytest.raises(ValueError, match="parameters"):
        await executor.query("performance", {"unexpected": 1})


@pytest.mark.anyio
async def test_mysql_check_uses_only_the_fixed_health_query() -> None:
    health = QuerySpec(
        name="health",
        dialect="mysql",
        sql="SELECT 1 AS ok LIMIT 1",
        allowed_tables=frozenset(),
        allowed_columns=frozenset(),
    )
    client = ValidHealthMySqlClient()
    executor = ReadonlyMySqlExecutor(client, {"health": health}, auto_query_mode=1)

    await executor.check()

    assert client.calls == [("SELECT 1 AS ok LIMIT 1", {}, 10.0)]


@pytest.mark.anyio
async def test_mysql_check_rejects_an_invalid_health_result() -> None:
    health = QuerySpec(
        name="health",
        dialect="mysql",
        sql="SELECT 1 AS ok LIMIT 1",
        allowed_tables=frozenset(),
        allowed_columns=frozenset(),
    )
    executor = ReadonlyMySqlExecutor(
        InvalidHealthMySqlClient(), {"health": health}, auto_query_mode=1
    )

    with pytest.raises(RuntimeError, match="invalid result"):
        await executor.check()
