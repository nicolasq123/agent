from pathlib import Path

from ad_rca.agent.models import PlanningRequest, ReportRequest
from ad_rca.application.core_service import CoreRcaService, default_verifiers
from ad_rca.data.fixture_repository import FixtureRepository
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


def _prepared_and_result():
    repository = FixtureRepository.load(Path("../fixtures/demo/pricing_error.json"))
    service = CoreRcaService(repository, default_verifiers())
    prepared = service.prepare(repository.scenario_id)
    result = service.verify(prepared, prepared.candidates[:3])
    return prepared, result


def test_fake_planner_deterministically_selects_first_allowed_candidates() -> None:
    prepared, _ = _prepared_and_result()
    assert prepared.incident is not None

    plan = FakePlanner().plan(
        PlanningRequest(
            incident=prepared.incident,
            candidates=prepared.candidates,
            attributions=prepared.attributions,
        )
    )

    assert plan.hypotheses == prepared.candidates[:3]


def test_template_report_cites_deterministic_evidence() -> None:
    _, result = _prepared_and_result()
    assert result.incident is not None

    report = TemplateReportComposer().compose(ReportRequest(run_id="run-1", result=result))

    assert report.generated_without_llm is True
    assert report.incident_id == result.incident.incident_id
    assert report.conclusions[0].evidence_ids == (result.evidence[0].evidence_id,)
    assert "900" in report.summary
