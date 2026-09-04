import pytest
from pydantic import SecretStr, ValidationError

from ad_rca.agent.models import InvestigationPlan, InvestigationReport, ReportConclusion
from ad_rca.config import Settings
from ad_rca.domain.enums import Confidence, HypothesisType


def test_settings_default_to_fixture_and_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_MODE", raising=False)
    monkeypatch.delenv("DATA_MODE", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.data_mode == "fixture"
    assert settings.model_mode == "fake"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.auto_query_mode == 0


def test_auto_query_mode_one_enables_automatic_queries() -> None:
    settings = Settings(_env_file=None, auto_query_mode=1)  # type: ignore[call-arg]

    assert settings.auto_query_mode == 1


def test_real_model_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        Settings(model_mode="deepseek", deepseek_api_key=None)


def test_readonly_db_requires_both_mysql_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYSQL_STAT_URL", raising=False)
    monkeypatch.delenv("MYSQL_CONFIG_URL", raising=False)

    with pytest.raises(ValidationError, match="MYSQL_STAT_URL and MYSQL_CONFIG_URL"):
        Settings(data_mode="readonly_db", mysql_stat_url=None, mysql_config_url=None)


def test_readonly_db_accepts_separate_secret_urls() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_mode="readonly_db",
        mysql_stat_url=SecretStr("mysql+asyncmy://db20/au_stat"),
        mysql_config_url=SecretStr("mysql+asyncmy://db40/ymgw"),
    )

    assert settings.mysql_stat_url is not None
    assert settings.mysql_config_url is not None
    assert "stat-secret" not in str(settings.mysql_stat_url)
    assert "config-secret" not in str(settings.mysql_config_url)
    assert settings.stat_timezone == "UTC"
    assert settings.cli_timezone == "Asia/Shanghai"


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Settings(cli_timezone="Mars/Olympus_Mons")


def test_env_example_loads_as_complete_readonly_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "DATA_MODE",
        "MODEL_MODE",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "MYSQL_STAT_URL",
        "MYSQL_CONFIG_URL",
        "STAT_TIMEZONE",
        "CLI_TIMEZONE",
        "MODEL_TIMEOUT_SECONDS",
        "ARTIFACTS_DIR",
        "FIXTURE_DIR",
        "AUTO_QUERY_MODE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file="../.env.example")  # type: ignore[call-arg]

    assert settings.data_mode == "readonly_db"
    assert settings.model_mode == "deepseek"
    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "replace-with-your-deepseek-api-key"
    assert settings.mysql_stat_url is not None
    assert settings.mysql_stat_url.get_secret_value() == (
        "mysql+asyncmy://readonly_user:replace-with-password@"
        "db20.example.internal:3306/au_stat?charset=utf8mb4"
    )
    assert settings.mysql_config_url is not None
    assert settings.mysql_config_url.get_secret_value() == (
        "mysql+asyncmy://readonly_user:replace-with-password@"
        "db40.example.internal:3306/ymgw?charset=utf8mb4"
    )
    assert settings.model_timeout_seconds == 30
    assert settings.artifacts_dir.as_posix() == "artifacts"
    assert settings.fixture_dir.as_posix() == "../fixtures/demo"
    assert settings.auto_query_mode == 0


def test_plan_rejects_more_than_three_hypotheses() -> None:
    with pytest.raises(ValidationError):
        InvestigationPlan(
            hypotheses=(
                HypothesisType.PAYOUT_PRICE_INCREASE,
                HypothesisType.REVENUE_PRICE_DECREASE,
                HypothesisType.TRAFFIC_VOLUME_DROP,
                HypothesisType.TRAFFIC_MIX_SHIFT,
            ),
            rationale="too many",
        )


def test_report_requires_every_conclusion_to_cite_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence"):
        InvestigationReport(
            run_id="run-1",
            incident_id="inc-1",
            summary="Profit fell.",
            conclusions=(
                ReportConclusion(
                    hypothesis=HypothesisType.PAYOUT_PRICE_INCREASE,
                    confidence=Confidence.CONFIRMED,
                    statement="Payout increased.",
                    evidence_ids=(),
                    explained_loss=900.0,
                ),
            ),
        )
