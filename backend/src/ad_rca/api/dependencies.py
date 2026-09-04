from ad_rca.application.investigation_service import (
    InvestigationService,
    build_fixture_service,
)
from ad_rca.application.natural_language_service import NaturalLanguageAnalysisService
from ad_rca.config import Settings
from ad_rca.data.mysql_snapshot import MySqlSnapshotLoader
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.database.mysql import create_mysql_executor
from ad_rca.infrastructure.database.mysql_catalog import config_query_specs, stat_query_specs
from ad_rca.infrastructure.database.query_budget import QueryBudget
from ad_rca.infrastructure.models.deepseek import (
    DeepSeekPlanner,
    DeepSeekReportComposer,
    OpenAIJsonClient,
)
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.infrastructure.models.intent import DeepSeekIntentParser, RuleIntentParser


def build_service(settings: Settings | None = None) -> InvestigationService:
    configured = settings or Settings()
    if configured.data_mode != "fixture":
        raise RuntimeError(
            "readonly_db mode requires production table mappings; use fixture mode until configured"
        )
    if configured.model_mode == "deepseek":
        if configured.deepseek_api_key is None:
            raise RuntimeError("DeepSeek API key is not configured")
        client = OpenAIJsonClient(
            api_key=configured.deepseek_api_key,
            base_url=configured.deepseek_base_url,
            model=configured.deepseek_model,
            timeout_seconds=configured.model_timeout_seconds,
        )
        planner = DeepSeekPlanner(client)
        composer = DeepSeekReportComposer(client)
    else:
        planner = FakePlanner()
        composer = TemplateReportComposer()
    return build_fixture_service(
        configured.fixture_dir,
        configured.artifacts_dir,
        planner,
        composer,
    )


def build_natural_language_service(
    settings: Settings | None = None,
) -> NaturalLanguageAnalysisService:
    configured = settings or Settings()
    if configured.data_mode != "readonly_db":
        raise RuntimeError("natural-language analysis requires DATA_MODE=readonly_db")
    if configured.mysql_stat_url is None or configured.mysql_config_url is None:
        raise RuntimeError("read-only MySQL URLs are not configured")

    budget = QueryBudget(max_queries=20)
    stat_reader = create_mysql_executor(
        configured.mysql_stat_url.get_secret_value(),
        stat_query_specs(),
        budget,
        auto_query_mode=configured.auto_query_mode,
    )
    config_reader = create_mysql_executor(
        configured.mysql_config_url.get_secret_value(),
        config_query_specs(),
        budget,
        auto_query_mode=configured.auto_query_mode,
    )
    loader = MySqlSnapshotLoader(
        stat_reader,
        config_reader,
        stat_timezone=configured.stat_timezone,
        query_budget=budget,
    )
    if configured.model_mode == "deepseek":
        if configured.deepseek_api_key is None:
            raise RuntimeError("DeepSeek API key is not configured")
        client = OpenAIJsonClient(
            api_key=configured.deepseek_api_key,
            base_url=configured.deepseek_base_url,
            model=configured.deepseek_model,
            timeout_seconds=configured.model_timeout_seconds,
        )
        parser = DeepSeekIntentParser(client, timezone=configured.cli_timezone)
        planner = DeepSeekPlanner(client)
        composer = DeepSeekReportComposer(client)
    else:
        parser = RuleIntentParser(timezone=configured.cli_timezone)
        planner = FakePlanner()
        composer = TemplateReportComposer()
    return NaturalLanguageAnalysisService(
        parser=parser,
        loader=loader,
        planner=planner,
        composer=composer,
        artifact_store=ArtifactStore(configured.artifacts_dir),
    )
