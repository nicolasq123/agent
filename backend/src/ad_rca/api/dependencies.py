from ad_rca.application.investigation_service import (
    InvestigationService,
    build_fixture_service,
)
from ad_rca.config import Settings
from ad_rca.infrastructure.models.deepseek import (
    DeepSeekPlanner,
    DeepSeekReportComposer,
    OpenAIJsonClient,
)
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


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

