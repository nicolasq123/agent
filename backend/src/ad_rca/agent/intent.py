from enum import StrEnum

from pydantic import Field

from ad_rca.domain.models import SliceKey, StrictModel, TimeWindow


class AnalysisKind(StrEnum):
    PROFIT_RCA = "profit_rca"


class AnalysisIntent(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    kind: AnalysisKind = AnalysisKind.PROFIT_RCA
    window: TimeWindow
    scope: SliceKey = SliceKey()
    timezone: str = "Asia/Shanghai"
