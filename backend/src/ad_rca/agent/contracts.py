from typing import Protocol

from ad_rca.agent.intent import AnalysisIntent
from ad_rca.agent.models import (
    InvestigationPlan,
    InvestigationReport,
    PlanningRequest,
    QuestionAnswer,
    QuestionRequest,
    ReportRequest,
)


class IntentParser(Protocol):
    def parse(self, question: str) -> AnalysisIntent: ...


class InvestigationPlanner(Protocol):
    def plan(self, request: PlanningRequest) -> InvestigationPlan: ...


class ReportComposer(Protocol):
    def compose(self, request: ReportRequest) -> InvestigationReport: ...

    def answer(self, request: QuestionRequest) -> QuestionAnswer: ...
