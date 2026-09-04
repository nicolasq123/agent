from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ad_rca.agent.intent import AnalysisIntent, AnalysisKind
from ad_rca.domain.models import SliceKey, TimeWindow


def test_analysis_intent_is_frozen_and_rejects_unknown_fields() -> None:
    intent = AnalysisIntent(
        question="分析昨天 offer 12345 为什么利润下降",
        kind=AnalysisKind.PROFIT_RCA,
        window=TimeWindow(
            start=datetime(2026, 9, 3, tzinfo=timezone.utc),
            end=datetime(2026, 9, 4, tzinfo=timezone.utc),
        ),
        scope=SliceKey(offer_id="12345"),
        timezone="Asia/Shanghai",
    )

    assert intent.scope.offer_id == "12345"
    with pytest.raises(ValidationError):
        AnalysisIntent.model_validate({**intent.model_dump(), "sql": "SELECT 1"})
    with pytest.raises(ValidationError):
        intent.question = "changed"  # type: ignore[misc]


def test_analysis_intent_rejects_blank_question() -> None:
    with pytest.raises(ValidationError):
        AnalysisIntent(
            question="",
            window=TimeWindow(
                start=datetime(2026, 9, 3, tzinfo=timezone.utc),
                end=datetime(2026, 9, 4, tzinfo=timezone.utc),
            ),
        )
