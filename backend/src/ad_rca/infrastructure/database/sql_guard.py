# pyright: reportUnknownMemberType=false
from collections.abc import Collection
from typing import Literal

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import SqlglotError

SqlDialect = Literal["mysql", "clickhouse"]
MAX_RESULT_ROWS = 10_000

_FORBIDDEN_KEYS = {
    "alter",
    "command",
    "commit",
    "copy",
    "create",
    "delete",
    "drop",
    "grant",
    "insert",
    "into",
    "load",
    "lock",
    "merge",
    "replace",
    "revoke",
    "rollback",
    "set",
    "transaction",
    "truncate",
    "update",
    "use",
}
_FORBIDDEN_FUNCTIONS = {
    "file",
    "hdfs",
    "jdbc",
    "mysql",
    "odbc",
    "postgresql",
    "remote",
    "remotesecure",
    "s3",
    "url",
}


class ReadonlySqlError(ValueError):
    pass


def validate_readonly_sql(
    sql: str,
    *,
    dialect: SqlDialect,
    allowed_tables: Collection[str],
    allowed_columns: Collection[str],
    max_result_rows: int = MAX_RESULT_ROWS,
) -> exp.Expression:
    if not sql.strip() or ";" in sql:
        raise ReadonlySqlError("query must be one non-empty statement without semicolons")
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except SqlglotError as error:
        raise ReadonlySqlError("query could not be parsed as read-only SQL") from error
    if len(statements) != 1 or statements[0] is None:
        raise ReadonlySqlError("query must contain exactly one statement")
    expression = statements[0]
    if not isinstance(expression, (exp.Select, exp.Union)):
        raise ReadonlySqlError("only SELECT queries are allowed")
    for node in expression.walk():
        if node.key.lower() in _FORBIDDEN_KEYS:
            raise ReadonlySqlError(f"forbidden SQL operation: {node.key}")
        if isinstance(node, exp.Star):
            raise ReadonlySqlError("wildcard columns are not allowed")
        if isinstance(node, exp.Func) and _function_name(node) in _FORBIDDEN_FUNCTIONS:
            raise ReadonlySqlError("remote and file table functions are forbidden")

    cte_names = {
        cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE) if cte.alias_or_name
    }
    table_names = {
        table.name.lower()
        for table in expression.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    }
    allowed_table_names = {name.lower() for name in allowed_tables}
    if table_names and not table_names.issubset(allowed_table_names):
        raise ReadonlySqlError("query table is outside the allowlist")
    if not table_names and allowed_table_names:
        raise ReadonlySqlError("query table is outside the allowlist")

    column_names = {column.name.lower() for column in expression.find_all(exp.Column)}
    allowed_column_names = {name.lower() for name in allowed_columns}
    if not column_names.issubset(allowed_column_names):
        raise ReadonlySqlError("query column is outside the allowlist")

    limit = expression.args.get("limit")
    if not isinstance(limit, exp.Limit) or not isinstance(limit.expression, exp.Literal):
        raise ReadonlySqlError("query must include a literal LIMIT")
    try:
        limit_value = int(limit.expression.this)
    except (TypeError, ValueError) as error:
        raise ReadonlySqlError("query LIMIT must be an integer") from error
    if limit_value < 1 or limit_value > max_result_rows:
        raise ReadonlySqlError(f"query LIMIT must be between 1 and {max_result_rows}")
    return expression


def _function_name(function: exp.Func) -> str:
    if isinstance(function, exp.Anonymous):
        return function.name.lower()
    return function.sql_name().lower()
