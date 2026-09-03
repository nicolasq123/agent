from datetime import datetime
from typing import Literal

from ad_rca.domain.models import StrictModel

EventType = Literal[
    "baseline_loaded",
    "attribution_completed",
    "hypothesis_generated",
    "plan_created",
    "verifier_started",
    "evidence_found",
    "hypothesis_rejected",
    "root_cause_confirmed",
    "report_generated",
]


class WorkflowEvent(StrictModel):
    run_id: str
    sequence: int
    event_type: EventType
    occurred_at: datetime
    payload: dict[str, object]
