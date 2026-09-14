"""Select a transport without changing query catalogs or analysis logic."""

from collections.abc import Mapping
from typing import Literal

from ad_rca.config import Settings
from ad_rca.infrastructure.database.http_query import HttpQueryClient
from ad_rca.infrastructure.database.mysql import ReadonlyMySqlExecutor, create_mysql_executor
from ad_rca.infrastructure.database.query_budget import QueryBudget
from ad_rca.infrastructure.database.query_specs import QuerySpec


def create_query_executor(
    settings: Settings,
    source: Literal["stat", "config"],
    specs: Mapping[str, QuerySpec],
    budget: QueryBudget | None = None,
) -> ReadonlyMySqlExecutor:
    if settings.query_backend == "http":
        if settings.http_query_url is None or settings.http_query_token is None:
            raise ValueError("HTTP query endpoint and token are required")
        database = (
            settings.http_query_stat_db if source == "stat" else settings.http_query_config_db
        )
        return ReadonlyMySqlExecutor(
            HttpQueryClient(settings.http_query_url, settings.http_query_token, database),
            specs,
            budget,
            auto_query_mode=settings.auto_query_mode,
        )
    url = settings.mysql_stat_url if source == "stat" else settings.mysql_config_url
    if url is None:
        raise ValueError("MySQL source URL is required")
    return create_mysql_executor(
        url.get_secret_value(), specs, budget, auto_query_mode=settings.auto_query_mode
    )
