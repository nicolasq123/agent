from collections.abc import Mapping

from ad_rca.infrastructure.database.query_specs import QuerySpec

_STAT_COLUMNS = frozenset(
    {
        "dt",
        "ader_id",
        "oid_",
        "aid",
        "gid",
        "country",
        "clk_os",
        "carrier",
        "clk",
        "clk2",
        "cov",
        "cov_aff",
        "revenue",
        "payout",
    }
)
_PERFORMANCE_SELECT = """dt AS event_hour,
       ader_id AS advertiser_id,
       oid_ AS offer_id,
       aid AS channel_id,
       country,
       clk_os,
       carrier,
       SUM(clk) AS clicks,
       SUM(clk2) AS invalid_clicks,
       SUM(cov) AS conversions,
       SUM(cov_aff) AS settled_conversions,
       SUM(revenue) AS revenue,
       SUM(payout) AS payout"""
_HEALTH = QuerySpec(
    name="health",
    dialect="mysql",
    sql="SELECT 1 AS ok LIMIT 1",
)


def _stat_spec(
    name: str,
    sql: str,
    parameters: frozenset[str],
    *,
    max_result_rows: int = 10_000,
) -> QuerySpec:
    return QuerySpec(
        name=name,
        dialect="mysql",
        sql=sql,
        allowed_tables=frozenset({"stat"}),
        allowed_columns=_STAT_COLUMNS,
        parameters=parameters,
        max_result_rows=max_result_rows,
    )


def _candidate_spec(name: str, column: str) -> QuerySpec:
    return _stat_spec(
        name,
        f"""SELECT {column} AS dimension_value,
       SUM(clk) AS clicks,
       SUM(cov) AS conversions,
       SUM(revenue) AS revenue,
       SUM(payout) AS payout
FROM au_stat.stat
WHERE dt >= :history_start AND dt < :window_end
GROUP BY {column}
ORDER BY SUM(clk) DESC, {column} ASC
LIMIT 6""",
        frozenset({"history_start", "window_end"}),
        max_result_rows=6,
    )


def _series_spec(name: str, column: str) -> QuerySpec:
    values = ", ".join(f":value_{index}" for index in range(1, 7))
    parameters = {"history_start", "window_end"}
    parameters.update(f"value_{index}" for index in range(1, 7))
    return _stat_spec(
        name,
        f"""SELECT dt AS event_hour,
       {column} AS dimension_value,
       SUM(clk) AS clicks,
       SUM(cov) AS conversions,
       SUM(revenue) AS revenue,
       SUM(payout) AS payout
FROM au_stat.stat
WHERE dt >= :history_start AND dt < :window_end
  AND {column} IN ({values})
GROUP BY dt, {column}
ORDER BY dt ASC, {column} ASC
LIMIT 10000""",
        frozenset(parameters),
    )


def stat_query_specs() -> Mapping[str, QuerySpec]:
    specs: dict[str, QuerySpec] = {"health": _HEALTH}
    specs["performance_scoped"] = _stat_spec(
        "performance_scoped",
        f"""SELECT {_PERFORMANCE_SELECT}
FROM au_stat.stat
WHERE dt >= :history_start AND dt < :window_end
  AND (:advertiser_id IS NULL OR ader_id = :advertiser_id)
  AND (:offer_id IS NULL OR oid_ = :offer_id)
  AND (:channel_id IS NULL OR aid = :channel_id)
  AND (:country IS NULL OR country = :country)
GROUP BY dt, ader_id, oid_, aid, country, clk_os, carrier
ORDER BY dt ASC, ader_id ASC, oid_ ASC, aid ASC, country ASC, clk_os ASC, carrier ASC
LIMIT 10000""",
        frozenset(
            {
                "history_start",
                "window_end",
                "advertiser_id",
                "offer_id",
                "channel_id",
                "country",
            }
        ),
    )
    dimensions = {
        "advertiser": "ader_id",
        "offer": "oid_",
        "channel": "aid",
        "country": "country",
    }
    for name, column in dimensions.items():
        specs[f"scope_candidates_by_{name}"] = _candidate_spec(
            f"scope_candidates_by_{name}", column
        )
        specs[f"performance_by_{name}"] = _series_spec(
            f"performance_by_{name}", column
        )
    return specs


def _config_spec(
    name: str,
    sql: str,
    tables: frozenset[str],
    columns: frozenset[str],
    parameters: frozenset[str],
) -> QuerySpec:
    return QuerySpec(
        name=name,
        dialect="mysql",
        sql=sql,
        allowed_tables=tables,
        allowed_columns=columns,
        parameters=parameters,
    )


def config_query_specs() -> Mapping[str, QuerySpec]:
    scope_time = frozenset(
        {"advertiser_id", "offer_id", "channel_id", "evidence_start", "window_end"}
    )
    return {
        "health": _HEALTH,
        "settlement": _config_spec(
            "settlement",
            """SELECT id, oid, aid, payout, ratio, status, inactive, ut
FROM ymgw.settlement
WHERE ut >= :evidence_start AND ut < :window_end
  AND (:offer_id IS NULL OR oid IN (0, :offer_id))
  AND (:channel_id IS NULL OR aid IN (0, :channel_id))
ORDER BY ut ASC, id ASC
LIMIT 10000""",
            frozenset({"settlement"}),
            frozenset({"id", "oid", "aid", "payout", "ratio", "status", "inactive", "ut"}),
            frozenset({"offer_id", "channel_id", "evidence_start", "window_end"}),
        ),
        "margin": _config_spec(
            "margin",
            """SELECT id, ader_id, oid, aid, ratio2, margin_type, status, inactive, ut
FROM ymgw.margin
WHERE ut >= :evidence_start AND ut < :window_end
  AND (:advertiser_id IS NULL OR ader_id IN (0, :advertiser_id))
  AND (:offer_id IS NULL OR oid IN (0, :offer_id))
  AND (:channel_id IS NULL OR aid IN (0, :channel_id))
ORDER BY ut ASC, id ASC
LIMIT 10000""",
            frozenset({"margin"}),
            frozenset(
                {"id", "ader_id", "oid", "aid", "ratio2", "margin_type", "status", "inactive", "ut"}
            ),
            scope_time,
        ),
        "cap_observations": _config_spec(
            "cap_observations",
            """SELECT c.id, c.ader_id, c.oid, c.aid, c.time_typ, c.cap_typ,
       c.cap AS cap_value, c.tz, c.status, c.inactive, c.ut,
       r.remain, r.usage_percent,
       l.create_at, l.expire_at, l.reason
FROM ymgw.cap AS c
LEFT JOIN ymgw.remain_cap AS r ON r.cap_id = c.id
  AND r.ader_id = c.ader_id AND r.oid = c.oid AND r.aid = c.aid
LEFT JOIN ymgw.cap_log AS l ON l.cap_id = c.id
  AND l.ader_id = c.ader_id AND l.oid = c.oid AND l.aid = c.aid
WHERE (:advertiser_id IS NULL OR c.ader_id IN (0, -1, :advertiser_id))
  AND (:offer_id IS NULL OR c.oid IN (0, -1, :offer_id))
  AND (:channel_id IS NULL OR c.aid IN (0, -1, :channel_id))
  AND (l.create_at IS NULL OR (l.create_at < :window_end AND l.expire_at >= :evidence_start))
ORDER BY c.ut ASC, c.id ASC, l.create_at ASC
LIMIT 10000""",
            frozenset({"cap", "cap_log", "remain_cap"}),
            frozenset(
                {
                    "id", "ader_id", "oid", "aid", "time_typ", "cap_typ", "cap", "tz",
                    "status", "inactive", "ut", "remain", "usage_percent", "cap_id",
                    "create_at", "expire_at", "reason",
                }
            ),
            scope_time,
        ),
        "routing_changes": _config_spec(
            "routing_changes",
            """SELECT id, ader_id, oid, aid, toid, inactive, ut
FROM ymgw.redirect
WHERE ut >= :evidence_start AND ut < :window_end
  AND (:advertiser_id IS NULL OR ader_id IN (0, :advertiser_id))
  AND (:offer_id IS NULL OR oid IN (0, :offer_id))
  AND (:channel_id IS NULL OR aid IN (0, :channel_id))
ORDER BY ut ASC, id ASC
LIMIT 10000""",
            frozenset({"redirect"}),
            frozenset({"id", "ader_id", "oid", "aid", "toid", "inactive", "ut"}),
            scope_time,
        ),
    }
