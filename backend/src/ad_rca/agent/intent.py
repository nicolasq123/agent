from enum import StrEnum

from pydantic import Field

from ad_rca.domain.models import SliceKey, StrictModel, TimeWindow


class AnalysisKind(StrEnum):
    SUMMARY = "summary"
    PROFIT_RCA = "profit_rca"


def analysis_kind(question: str) -> AnalysisKind:
    terms = ("为什么", "原因", "归因", "异常", "下降", "下滑", "亏损", "why", "drop", "rca")
    return (
        AnalysisKind.PROFIT_RCA
        if any(term in question.lower() for term in terms)
        else AnalysisKind.SUMMARY
    )


class AnalysisIntent(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    kind: AnalysisKind = AnalysisKind.PROFIT_RCA
    window: TimeWindow
    scope: SliceKey = SliceKey()
    timezone: str = "Asia/Shanghai"
