# pyright: reportUnknownMemberType=false
import asyncio
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TextIO

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ad_rca.infrastructure.database.query_budget import QueryBudget
from ad_rca.infrastructure.database.query_specs import QuerySpec
from ad_rca.infrastructure.database.sql_guard import validate_readonly_sql


class MySqlQueryClient(Protocol):
    async def fetch_all(
        self,
        query: str,
        parameters: Mapping[str, object],
        timeout_seconds: float,
    ) -> Sequence[Mapping[str, object]]: ...


class QueryApprover(Protocol):
    def __call__(
        self,
        name: str,
        sql: str,
        parameters: Mapping[str, object],
    ) -> bool: ...


class QueryApprovalRejected(RuntimeError):
    pass


class TerminalQueryApprover:
    def __init__(
        self,
        *,
        reader: Callable[[], str] | None = None,
        output: TextIO | None = None,
    ) -> None:
        self._reader = reader or input
        self._output = output or sys.stderr

    def __call__(
        self,
        name: str,
        sql: str,
        parameters: Mapping[str, object],
    ) -> bool:
        print(f"\n待审批只读查询：{name}", file=self._output)
        print(sql, file=self._output)
        print(
            "参数：" + json.dumps(dict(parameters), ensure_ascii=False, default=str),
            file=self._output,
        )
        print("执行此只读查询？输入 y 批准 [y/N]：", end="", file=self._output, flush=True)
        try:
            response = self._reader()
        except EOFError:
            return False
        return response.strip().lower() == "y"


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
        budget: QueryBudget | None = None,
        *,
        auto_query_mode: int = 0,
        approver: QueryApprover | None = None,
    ) -> None:
        self._client = client
        self._query_specs = dict(query_specs)
        self._budget = budget or QueryBudget()
        self._auto_query_mode = auto_query_mode
        self._approver = approver or TerminalQueryApprover()

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
        if self._auto_query_mode != 1 and not self._approver(name, spec.sql, parameters):
            raise QueryApprovalRejected("query was not approved")
        self._budget.consume()
        rows = await self._client.fetch_all(spec.sql, parameters, spec.timeout_seconds)
        return tuple(rows)

    async def check(self) -> None:
        rows = await self.query("health", {})
        if not rows or rows[0].get("ok") != 1:
            raise RuntimeError("MySQL read check returned an invalid result")


def create_mysql_executor(
    url: str,
    query_specs: Mapping[str, QuerySpec],
    budget: QueryBudget | None = None,
    *,
    auto_query_mode: int = 0,
) -> ReadonlyMySqlExecutor:
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"autocommit": True},
    )
    return ReadonlyMySqlExecutor(
        SqlAlchemyMySqlQueryClient(engine),
        query_specs,
        budget,
        auto_query_mode=auto_query_mode,
    )
