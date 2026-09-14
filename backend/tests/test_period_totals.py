from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ad_rca.application.natural_language_service import NaturalLanguageAnalysisService
from ad_rca.data.mysql_snapshot import MySqlSnapshotLoader
from ad_rca.infrastructure.artifacts import ArtifactStore
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer
from ad_rca.infrastructure.models.intent import RuleIntentParser
from tests.data.test_mysql_snapshot import RecordingReader


@pytest.mark.anyio
async def test_summary_preserves_scope_and_decimal_without_history(tmp_path: Path) -> None:
    stat = RecordingReader(
        {
            "period_totals": (
                {
                    "source_rows": 20001,
                    "revenue_rows": 20001,
                    "payout_rows": 20001,
                    "revenue": Decimal("10000000000000000.03"),
                    "payout": Decimal("10000000000000000.01"),
                    "first_dt": "2026-09-10 00:00:00",
                    "last_dt": "2026-09-10 23:00:00",
                },
            )
        }
    )
    config = RecordingReader({})
    service = NaturalLanguageAnalysisService(
        parser=RuleIntentParser(timezone="UTC", now=lambda: datetime(2026, 9, 11, tzinfo=UTC)),
        loader=MySqlSnapshotLoader(stat, config, stat_timezone="UTC"),
        planner=FakePlanner(),
        composer=TemplateReportComposer(),
        artifact_store=ArtifactStore(tmp_path),
    )
    analysis = await service.ask("分析昨天 offer 12345 的收入")
    assert "利润 0.02" in analysis.run.report.summary
    assert "20001" in analysis.run.report.summary
    assert analysis.selected_scope.offer_id == "12345"
    assert [name for name, _ in stat.calls] == ["period_totals"]
    assert stat.calls[0][1]["offer_id"] == "12345"
    assert not config.calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "count,revenue_rows,code", [(0, 0, "NoCurrentDataError"), (1, 0, "DATA_AMOUNT_MISSING")]
)
async def test_totals_distinguish_missing_data_and_missing_amount(
    count: int,
    revenue_rows: int,
    code: str,
) -> None:
    stat = RecordingReader(
        {
            "period_totals": (
                {
                    "source_rows": count,
                    "revenue_rows": revenue_rows,
                    "payout_rows": count,
                },
            )
        }
    )
    loader = MySqlSnapshotLoader(stat, RecordingReader({}), stat_timezone="UTC")
    intent = RuleIntentParser(now=lambda: datetime(2026, 9, 11, tzinfo=UTC)).parse("昨天收入")
    with pytest.raises((ValueError, RuntimeError)) as error:
        await loader.summarize(intent)
    assert code in str(error.value) + type(error.value).__name__
