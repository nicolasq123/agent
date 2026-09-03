import operator
from typing import Annotated, TypedDict

from ad_rca.agent.models import InvestigationPlan, InvestigationReport
from ad_rca.application.investigation_case import PreparedInvestigation
from ad_rca.domain.enums import HypothesisType
from ad_rca.domain.models import CoreInvestigationResult
from ad_rca.workflow.events import WorkflowEvent


class InvestigationState(TypedDict):
    scenario_id: str
    run_id: str
    round_number: int
    rounds_completed: int
    prepared: PreparedInvestigation | None
    plan: InvestigationPlan | None
    investigated: tuple[HypothesisType, ...]
    result: CoreInvestigationResult | None
    report: InvestigationReport | None
    events: Annotated[list[WorkflowEvent], operator.add]
    warnings: Annotated[list[str], operator.add]
