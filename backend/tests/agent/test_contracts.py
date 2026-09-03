import pytest
from pydantic import ValidationError

from ad_rca.agent.models import InvestigationPlan, InvestigationReport, ReportConclusion
from ad_rca.config import Settings
from ad_rca.domain.enums import Confidence, HypothesisType


def test_settings_default_to_fixture_and_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_MODE", raising=False)
    monkeypatch.delenv("DATA_MODE", raising=False)

    settings = Settings()

    assert settings.data_mode == "fixture"
    assert settings.model_mode == "fake"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-v4-flash"


def test_real_model_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        Settings(model_mode="deepseek", deepseek_api_key=None)


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
