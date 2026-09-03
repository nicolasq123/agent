from pydantic import Field

from ad_rca.domain.models import Incident, StrictModel


class DetectionResponse(StrictModel):
    incidents: tuple[Incident, ...]


class InvestigationCreated(StrictModel):
    run_id: str
    incident_id: str
    status: str
    events_url: str
    report_url: str


class QuestionBody(StrictModel):
    question: str = Field(min_length=1, max_length=1000)

