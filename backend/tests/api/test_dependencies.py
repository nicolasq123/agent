from collections.abc import Mapping

import pytest
from pydantic import SecretStr

from ad_rca.api import dependencies
from ad_rca.config import Settings
from ad_rca.infrastructure.database.query_budget import QueryBudget
from ad_rca.infrastructure.database.query_specs import QuerySpec


class UnusedReader:
    async def query(
        self, name: str, parameters: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        raise AssertionError("service construction must not query MySQL")

    async def check(self) -> None:
        raise AssertionError("service construction must not check MySQL")


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_natural_language_service_passes_auto_query_mode_to_both_databases(
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    observed_modes: list[int] = []

    def create_executor(
        url: str,
        query_specs: Mapping[str, QuerySpec],
        budget: QueryBudget | None = None,
        *,
        auto_query_mode: int,
    ) -> UnusedReader:
        observed_modes.append(auto_query_mode)
        return UnusedReader()

    monkeypatch.setattr(dependencies, "create_mysql_executor", create_executor)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_mode="readonly_db",
        mysql_stat_url=SecretStr("mysql+asyncmy://db20/au_stat"),
        mysql_config_url=SecretStr("mysql+asyncmy://db40/ymgw"),
        auto_query_mode=mode,
    )

    dependencies.build_natural_language_service(settings)

    assert observed_modes == [mode, mode]
