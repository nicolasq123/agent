# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
from collections.abc import Mapping, Sequence
from typing import Protocol, cast

import clickhouse_connect
from pydantic import SecretStr

from ad_rca.infrastructure.database.query_specs import QuerySpec
from ad_rca.infrastructure.database.sql_guard import validate_readonly_sql


class ClickHouseQueryClient(Protocol):
    def query(
        self,
        query: str,
        parameters: Mapping[str, object],
        settings: Mapping[str, object],
    ) -> Sequence[Mapping[str, object]]: ...


class ClickHouseResult(Protocol):
    column_names: tuple[str, ...]
    result_rows: Sequence[Sequence[object]]


class RawClickHouseClient(Protocol):
    def query(
        self,
        query: str,
        parameters: Mapping[str, object] | None = None,
        settings: Mapping[str, object] | None = None,
    ) -> ClickHouseResult: ...


class ClickHouseConnectQueryClient:
    def __init__(self, client: RawClickHouseClient) -> None:
        self._client = client

    def query(
        self,
        query: str,
        parameters: Mapping[str, object],
        settings: Mapping[str, object],
    ) -> Sequence[Mapping[str, object]]:
        result = self._client.query(query, parameters=parameters, settings=settings)
        return tuple(dict(zip(result.column_names, row, strict=True)) for row in result.result_rows)


class ReadonlyClickHouseExecutor:
    def __init__(
        self,
        client: ClickHouseQueryClient,
        query_specs: Mapping[str, QuerySpec],
    ) -> None:
        self._client = client
        self._query_specs = dict(query_specs)

    def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        spec = self._query_specs.get(name)
        if spec is None or spec.dialect != "clickhouse":
            raise ValueError("unknown ClickHouse query spec")
        _validate_parameters(spec, parameters)
        validate_readonly_sql(
            spec.sql,
            dialect="clickhouse",
            allowed_tables=spec.allowed_tables,
            allowed_columns=spec.allowed_columns,
            max_result_rows=spec.max_result_rows,
        )
        rows = self._client.query(
            spec.sql,
            parameters,
            {
                "readonly": 2,
                "max_result_rows": spec.max_result_rows,
                "result_overflow_mode": "throw",
                "max_execution_time": int(spec.timeout_seconds),
            },
        )
        return tuple(rows)


def create_clickhouse_executor(
    *,
    host: str,
    port: int,
    username: str,
    password: SecretStr,
    secure: bool,
    query_specs: Mapping[str, QuerySpec],
) -> ReadonlyClickHouseExecutor:
    raw = clickhouse_connect.get_client(
        host=host,
        port=port,
        username=username,
        password=password.get_secret_value(),
        secure=secure,
        settings={"readonly": 2},
    )
    client = ClickHouseConnectQueryClient(cast(RawClickHouseClient, raw))
    return ReadonlyClickHouseExecutor(client, query_specs)


def _validate_parameters(spec: QuerySpec, parameters: Mapping[str, object]) -> None:
    if set(parameters) != set(spec.parameters):
        raise ValueError("query parameters do not match fixed query spec")
