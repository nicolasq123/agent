from typing import Literal, Self

from pydantic import Field, model_validator

from ad_rca.domain.models import StrictModel
from ad_rca.infrastructure.database.sql_guard import validate_readonly_sql


class QuerySpec(StrictModel):
    name: str
    dialect: Literal["mysql", "clickhouse"]
    sql: str
    allowed_tables: frozenset[str] = frozenset()
    allowed_columns: frozenset[str] = frozenset()
    parameters: frozenset[str] = frozenset()
    timeout_seconds: float = Field(default=10.0, gt=0, le=10)
    max_result_rows: int = Field(default=10_000, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_sql(self) -> Self:
        validate_readonly_sql(
            self.sql,
            dialect=self.dialect,
            allowed_tables=self.allowed_tables,
            allowed_columns=self.allowed_columns,
            max_result_rows=self.max_result_rows,
        )
        return self
