from ad_rca.domain.enums import HypothesisType, RunStatus
from ad_rca.domain.models import AttributionResult, HypothesisResult, Incident, StrictModel
from ad_rca.rca.verifiers.base import VerificationContext


class PreparedInvestigation(StrictModel):
    status: RunStatus
    incident: Incident | None
    attributions: tuple[AttributionResult, ...] = ()
    residual_loss: float = 0.0
    context: VerificationContext | None = None
    candidates: tuple[HypothesisType, ...] = ()
    hypotheses: tuple[HypothesisResult, ...] = ()
