from pydantic import Field, model_validator

from ad_rca.domain.enums import Confidence, HypothesisType, RunStatus
from ad_rca.domain.models import (
    AttributionResult,
    CoreInvestigationResult,
    Incident,
    StrictModel,
)


class PlanningRequest(StrictModel):
    incident: Incident
    candidates: tuple[HypothesisType, ...]
    attributions: tuple[AttributionResult, ...]
    round_number: int = Field(default=1, ge=1, le=2)
    investigated: tuple[HypothesisType, ...] = ()


class InvestigationPlan(StrictModel):
    hypotheses: tuple[HypothesisType, ...] = Field(min_length=1, max_length=3)
    rationale: str = Field(min_length=1, max_length=1000)


class ReportConclusion(StrictModel):
    hypothesis: HypothesisType
    confidence: Confidence
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: tuple[str, ...]
    explained_loss: float = Field(ge=0)

    @model_validator(mode="after")
    def require_evidence(self) -> "ReportConclusion":
        if not self.evidence_ids:
            raise ValueError("report conclusions require at least one evidence ID")
        return self


class ReportRequest(StrictModel):
    run_id: str
    result: CoreInvestigationResult


class InvestigationReport(StrictModel):
    run_id: str
    incident_id: str
    status: RunStatus = RunStatus.COMPLETED
    summary: str = Field(min_length=1, max_length=8000)
    conclusions: tuple[ReportConclusion, ...] = ()
    recommendations: tuple[str, ...] = ()
    generated_without_llm: bool = False
    warnings: tuple[str, ...] = ()


class QuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    report: InvestigationReport


class QuestionAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[str, ...] = ()
    generated_without_llm: bool = False


def validate_report_conclusions(
    report: InvestigationReport,
    result: CoreInvestigationResult,
) -> None:
    supported = {
        item.hypothesis: item for item in result.hypotheses if item.status.value == "supported"
    }
    seen: set[str] = set()
    for conclusion in report.conclusions:
        hypothesis = supported.get(conclusion.hypothesis)
        if hypothesis is None or conclusion.hypothesis in seen:
            raise ValueError("report conclusion is unsupported or duplicated")
        seen.add(conclusion.hypothesis)
        if conclusion.confidence != hypothesis.confidence:
            raise ValueError("report changed verified confidence")
        if conclusion.explained_loss != hypothesis.explained_loss:
            raise ValueError("report changed verified loss")
        if not set(conclusion.evidence_ids) <= {e.evidence_id for e in hypothesis.evidence}:
            raise ValueError("report cites evidence from a different hypothesis")
