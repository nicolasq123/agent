# pyright: reportUnknownMemberType=false
import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ad_rca.infrastructure.database.query_specs import QuerySpec
from ad_rca.infrastructure.database.sql_guard import validate_readonly_sql


class MySqlQueryClient(Protocol):
    async def fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object],
        timeout_seconds: float,
    ) -> Sequence[Mapping[str, object]]: ...


class SqlAlchemyMySqlQueryClient:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object],
        timeout_seconds: float,
    ) -> Sequence[Mapping[str, object]]:
        async with asyncio.timeout(timeout_seconds):
            async with self._engine.connect() as connection:
                result = await connection.execute(text(query), dict(parameters))
                return tuple(dict(row) for row in result.mappings().all())


class ReadonlyMySqlExecutor:
    def __init__(
        self,
        client: MySqlQueryClient,
        query_specs: Mapping[str, QuerySpec],
    ) -> None:
        self._client = client
        self._query_specs = dict(query_specs)

    async def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        spec = self._query_specs.get(name)
        if spec is None or spec.dialect != "mysql":
            raise ValueError("unknown MySQL query spec")
        if set(parameters) != set(spec.parameters):
            raise ValueError("query parameters do not match fixed query spec")
        validate_readonly_sql(
            spec.sql,
            dialect="mysql",
            allowed_tables=spec.allowed_tables,
            allowed_columns=spec.allowed_columns,
            max_result_rows=spec.max_result_rows,
        )
        rows = await self._client.fetch_all(spec.sql, parameters, spec.timeout_seconds)
        return tuple(rows)


def create_mysql_executor(url: str, query_specs: Mapping[str, QuerySpec]) -> ReadonlyMySqlExecutor:
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"autocommit": True},
    )
    return ReadonlyMySqlExecutor(SqlAlchemyMySqlQueryClient(engine), query_specs)
