"""Opt in: PROFITLENS_LIVE_MYSQL=1 uv run pytest tests/test_mysql_live_reliability.py.

Executes SELECT over synthetic derived tables; never creates or writes tables.
Uses MYSQL_STAT_URL from Settings without logging credentials or real rows.
"""

# pyright: reportUnknownMemberType=false
import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ad_rca.config import Settings
from ad_rca.infrastructure.database.http_query import render_query
from ad_rca.infrastructure.database.mysql_catalog import stat_query_specs

pytestmark = pytest.mark.skipif(
    os.environ.get("PROFITLENS_LIVE_MYSQL") != "1", reason="explicit live SELECT check"
)


@pytest.mark.anyio
async def test_real_mysql_aggregates_more_than_ten_thousand_source_rows() -> None:
    configured = Settings()
    assert configured.mysql_stat_url is not None
    engine = create_async_engine(configured.mysql_stat_url.get_secret_value())
    digits = "(" + " UNION ALL ".join(f"SELECT {n} AS n" for n in range(10)) + ")"
    # 100,000 synthetic facts: 50,000 in the selected offer and requested day.
    source = (
        "(SELECT CAST('2026-09-10 12:00:00' AS DATETIME) AS dt, "
        "1 AS ader_id, MOD(a.n, 2) AS oid_, 1 AS aid, 'US' AS country, "
        "CAST(0.03 AS DECIMAL(20,8)) AS revenue, CAST(0.01 AS DECIMAL(20,8)) AS payout "
        f"FROM {digits} a CROSS JOIN {digits} b CROSS JOIN {digits} c "
        f"CROSS JOIN {digits} d CROSS JOIN {digits} e) synthetic_stat"
    )
    sql = stat_query_specs()["period_totals"].sql.replace("au_stat.stat", source)
    parameters = {
        "window_start": datetime(2026, 9, 10),
        "window_end": datetime(2026, 9, 11),
        "advertiser_id": None,
        "offer_id": 1,
        "channel_id": None,
        "country": None,
    }
    try:
        async with engine.connect() as connection:
            result = (await connection.execute(text(sql), parameters)).mappings().one()
            assert result["source_rows"] == 50000
            assert result["revenue"] == Decimal("1500")
            assert result["payout"] == Decimal("500")
            assert result["revenue"] - result["payout"] == Decimal("1000")
            parameters["window_start"] = datetime(2026, 9, 11)
            parameters["window_end"] = datetime(2026, 9, 12)
            empty = (await connection.execute(text(sql), parameters)).mappings().one()
            assert empty["source_rows"] == 0
            assert empty["revenue"] is None
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_http_sql_parameter_encoding_roundtrips_on_real_mysql() -> None:
    settings = Settings()
    assert settings.mysql_stat_url is not None
    engine = create_async_engine(settings.mysql_stat_url.get_secret_value())
    payload = "US\\'; DROP TABLE stat; -- 中文"
    query = render_query(
        "SELECT :value AS payload, :empty AS n, :number AS i LIMIT 1",
        {"value": payload, "empty": None, "number": -1},
    )
    try:
        async with engine.connect() as connection:
            result = (await connection.execute(text(query))).mappings().one()
            assert result["payload"] == payload
            assert result["n"] is None
            assert result["i"] == -1
    finally:
        await engine.dispose()
