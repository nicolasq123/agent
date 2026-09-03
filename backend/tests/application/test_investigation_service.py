from pathlib import Path

from ad_rca.application.investigation_service import build_fixture_service
from ad_rca.infrastructure.models.fake import FakePlanner, TemplateReportComposer


def _ids():
    number = 0

    def next_id() -> str:
        nonlocal number
        number += 1
        return f"run-{number}"

    return next_id


def test_service_lists_and_completes_all_three_fixture_incidents(tmp_path: Path) -> None:
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=_ids(),
    )

    incidents = service.list_incidents()
    runs = tuple(service.start_investigation(item.incident_id) for item in incidents)

    assert len(incidents) == 3
    assert {run.report.incident_id for run in runs} == {
        incident.incident_id for incident in incidents
    }
    assert all(run.events[-1].event_type == "report_generated" for run in runs)


def test_service_replays_report_and_events_after_in_memory_registry_is_lost(
    tmp_path: Path,
) -> None:
    first = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-replay",
    )
    run = first.start_investigation(first.list_incidents()[0].incident_id)
    restarted = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
    )

    assert restarted.get_report(run.run_id) == run.report
    assert restarted.get_events(run.run_id) == run.events


def test_question_answer_cites_only_current_report_evidence(tmp_path: Path) -> None:
    service = build_fixture_service(
        Path("../fixtures/demo"),
        tmp_path,
        FakePlanner(),
        TemplateReportComposer(),
        id_factory=lambda: "run-question",
    )
    run = service.start_investigation(service.list_incidents()[0].incident_id)

    answer = service.answer_question(run.run_id, "为什么利润下降？")

    allowed = {
        evidence_id
        for conclusion in run.report.conclusions
        for evidence_id in conclusion.evidence_ids
    }
    assert set(answer.evidence_ids).issubset(allowed)
    assert "为什么利润下降" in answer.answer
