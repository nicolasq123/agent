from datetime import UTC, datetime

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.agent.models import InvestigationReport
from ad_rca.application.natural_language_service import NaturalLanguageAnalysis
from ad_rca.domain.enums import RunStatus
from ad_rca.domain.models import CoreInvestigationResult, SliceKey, TimeWindow
from ad_rca.presentation.markdown import render_analysis_markdown
from ad_rca.workflow.graph import WorkflowRun


def test_markdown_renders_no_incident_explicitly() -> None:
    window = TimeWindow(
        start=datetime(2026, 9, 3, tzinfo=UTC),
        end=datetime(2026, 9, 4, tzinfo=UTC),
    )
    report = InvestigationReport(
        run_id="run-none",
        incident_id="no-incident",
        summary="请求时间范围内未检测到利润异常。",
        generated_without_llm=True,
    )
    analysis = NaturalLanguageAnalysis(
        intent=AnalysisIntent(question="昨天利润正常吗", window=window, timezone="UTC"),
        selected_scope=SliceKey(),
        run=WorkflowRun(
            run_id="run-none",
            rounds=0,
            result=CoreInvestigationResult(
                status=RunStatus.COMPLETED,
                incident=None,
                residual_loss=0,
            ),
            report=report,
            events=(),
        ),
    )

    rendered = render_analysis_markdown(analysis)

    assert "未检测到利润异常" in rendered
    assert "2026-09-03" in rendered
    assert "原始数据库行" not in rendered
