import pytest

from ad_rca.infrastructure.database.sql_guard import ReadonlySqlError, validate_readonly_sql


def test_guard_accepts_bounded_select_from_allowlisted_table() -> None:
    expression = validate_readonly_sql(
        "SELECT offer_id, SUM(revenue) FROM ad_hourly_performance "
        "WHERE event_hour >= :start GROUP BY offer_id LIMIT 10000",
        dialect="mysql",
        allowed_tables={"ad_hourly_performance"},
        allowed_columns={"offer_id", "revenue", "event_hour"},
    )

    assert expression.key == "select"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO allowed_table VALUES (1)",
        "UPDATE allowed_table SET value = 1",
        "DELETE FROM allowed_table",
        "REPLACE INTO allowed_table VALUES (1)",
        "CREATE TABLE x (id INT)",
        "ALTER TABLE allowed_table ADD COLUMN x INT",
        "DROP TABLE allowed_table",
        "TRUNCATE TABLE allowed_table",
        "RENAME TABLE allowed_table TO x",
        "MERGE INTO allowed_table USING x ON 1=1 WHEN MATCHED THEN DELETE",
        "GRANT SELECT ON allowed_table TO user",
        "REVOKE SELECT ON allowed_table FROM user",
        "SELECT * FROM allowed_table; SELECT * FROM allowed_table",
        "SELECT * INTO OUTFILE '/tmp/data' FROM allowed_table",
        "SELECT * FROM allowed_table FOR UPDATE",
        "WITH changed AS (DELETE FROM allowed_table RETURNING id) SELECT * FROM changed",
        "SELECT * FROM url('https://example.com/data.csv') LIMIT 10",
        "SELECT * FROM remote('host', 'db', 'table') LIMIT 10",
    ],
)
def test_guard_rejects_every_non_readonly_query_family(sql: str) -> None:
    with pytest.raises(ReadonlySqlError):
        validate_readonly_sql(
            sql,
            dialect="mysql",
            allowed_tables={"allowed_table"},
            allowed_columns={"id", "value"},
        )


def test_guard_rejects_unbounded_and_over_limit_queries() -> None:
    for sql in (
        "SELECT id FROM allowed_table",
        "SELECT id FROM allowed_table LIMIT 10001",
    ):
        with pytest.raises(ReadonlySqlError, match="LIMIT"):
            validate_readonly_sql(
                sql,
                dialect="mysql",
                allowed_tables={"allowed_table"},
                allowed_columns={"id"},
            )


def test_guard_rejects_tables_and_columns_outside_allowlist() -> None:
    for sql in (
        "SELECT id FROM secret_table LIMIT 10",
        "SELECT secret_value FROM allowed_table LIMIT 10",
    ):
        with pytest.raises(ReadonlySqlError, match="allowlist"):
            validate_readonly_sql(
                sql,
                dialect="mysql",
                allowed_tables={"allowed_table"},
                allowed_columns={"id"},
            )
