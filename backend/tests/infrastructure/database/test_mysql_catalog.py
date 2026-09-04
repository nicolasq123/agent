# pyright: reportUnknownMemberType=false
import sqlglot
from sqlglot import expressions as exp

from ad_rca.infrastructure.database.mysql_catalog import (
    config_query_specs,
    stat_query_specs,
)


def test_catalog_contains_only_fixed_bounded_selects() -> None:
    specs = {**stat_query_specs(), **config_query_specs()}

    assert {
        "health",
        "performance_scoped",
        "scope_candidates_by_advertiser",
        "scope_candidates_by_offer",
        "scope_candidates_by_channel",
        "scope_candidates_by_country",
        "performance_by_advertiser",
        "performance_by_offer",
        "performance_by_channel",
        "performance_by_country",
        "settlement",
        "margin",
        "cap_observations",
        "routing_changes",
    } <= set(specs)
    assert all(spec.dialect == "mysql" for spec in specs.values())
    assert all("LIMIT" in spec.sql.upper() for spec in specs.values())

    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter)
    for spec in specs.values():
        expression = sqlglot.parse_one(spec.sql, read="mysql")
        assert expression.find(exp.Star) is None
        assert not any(expression.find(node_type) for node_type in forbidden)


def test_performance_queries_are_literal_and_bounded() -> None:
    specs = stat_query_specs()

    scoped = specs["performance_scoped"]
    assert scoped.allowed_tables == frozenset({"stat"})
    assert scoped.parameters == frozenset(
        {
            "history_start",
            "window_end",
            "advertiser_id",
            "offer_id",
            "channel_id",
            "country",
        }
    )
    assert "LIMIT 10000" in scoped.sql.upper()

    for dimension in ("advertiser", "offer", "channel", "country"):
        candidates = specs[f"scope_candidates_by_{dimension}"]
        series = specs[f"performance_by_{dimension}"]
        assert candidates.max_result_rows == 6
        assert "LIMIT 6" in candidates.sql.upper()
        assert series.parameters >= frozenset(f"value_{index}" for index in range(1, 7))
        assert "LIMIT 10000" in series.sql.upper()


def test_config_queries_use_only_documented_adn_tables() -> None:
    specs = config_query_specs()

    assert specs["health"].sql == "SELECT 1 AS ok LIMIT 1"
    assert specs["settlement"].allowed_tables == frozenset({"settlement"})
    assert specs["margin"].allowed_tables == frozenset({"margin"})
    assert specs["routing_changes"].allowed_tables == frozenset({"redirect"})
    assert specs["cap_observations"].allowed_tables == frozenset(
        {"cap", "cap_log", "remain_cap"}
    )
