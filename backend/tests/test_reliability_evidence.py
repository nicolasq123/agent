from datetime import timedelta

import pytest

from ad_rca.agent.models import ReportRequest, validate_report_conclusions
from ad_rca.domain.enums import Confidence, RunStatus
from ad_rca.domain.models import CoreInvestigationResult
from ad_rca.infrastructure.models.fake import TemplateReportComposer
from ad_rca.rca.contribution import attribute_loss
from ad_rca.rca.verifiers.cap import CapVerifier
from ad_rca.rca.verifiers.pricing import PricingVerifier
from tests.rca.test_candidates import context_fixture
from tests.test_reliability_regressions import START, row


def test_cap_hit_does_not_quantify_or_confirm_causality() -> None:
    result = CapVerifier().verify(context_fixture())
    assert result.confidence is not Confidence.CONFIRMED
    assert result.explained_loss == 0
    assert result.explanatory_power == 0


def test_same_slice_on_different_dates_has_distinct_evidence() -> None:
    context = context_fixture()
    first = PricingVerifier().verify(context)
    window = context.incident.window
    later = window.model_copy(
        update={
            "start": window.start + timedelta(days=1),
            "end": window.end + timedelta(days=1),
        }
    )
    second = PricingVerifier().verify(
        context.model_copy(
            update={
                "incident": context.incident.model_copy(update={"window": later}),
            }
        )
    )
    assert first.evidence[0].evidence_id != second.evidence[0].evidence_id


def test_report_cannot_inflate_confidence_or_loss() -> None:
    context = context_fixture().model_copy(update={"config_changes": ()})
    hypothesis = PricingVerifier().verify(context)
    result = CoreInvestigationResult(
        status=RunStatus.COMPLETED,
        incident=context.incident,
        residual_loss=0,
        hypotheses=(hypothesis,),
        evidence=hypothesis.evidence,
    )
    report = TemplateReportComposer().compose(ReportRequest(run_id="check", result=result))
    validate_report_conclusions(report, result)
    for update in ({"confidence": Confidence.CONFIRMED}, {"explained_loss": 999999.0}):
        altered = report.model_copy(
            update={"conclusions": (report.conclusions[0].model_copy(update=update),)}
        )
        with pytest.raises(ValueError):
            validate_report_conclusions(altered, result)


def test_gross_losses_and_gains_reconcile_with_net_loss() -> None:
    a = row(START, 100, 0)
    b = a.model_copy(update={"offer_id": "2"})
    result = attribute_loss(
        (a.model_copy(update={"revenue": 0.0}), b.model_copy(update={"revenue": 180.0})),
        (a, b),
        ("offer_id",),
    )
    assert result.total_loss == 100
    assert result.offsetting_gain == 80
    assert result.net_loss == 20
