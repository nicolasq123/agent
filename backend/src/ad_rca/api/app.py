# pyright: reportUnusedFunction=false
import json
from collections.abc import Iterator

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse

from ad_rca.agent.models import InvestigationReport, QuestionAnswer
from ad_rca.api.schemas import DetectionResponse, InvestigationCreated, QuestionBody
from ad_rca.application.investigation_service import InvestigationService
from ad_rca.domain.models import Incident
from ad_rca.workflow.events import WorkflowEvent


def create_app(service: InvestigationService) -> FastAPI:
    app = FastAPI(title="ProfitLens", version="0.2.0")

    @app.get("/api/incidents", response_model=list[Incident])
    def list_incidents() -> tuple[Incident, ...]:
        return service.list_incidents()

    @app.post("/api/detections/run", response_model=DetectionResponse)
    def run_detection() -> DetectionResponse:
        return DetectionResponse(incidents=service.run_detection())

    @app.get("/api/incidents/{incident_id}", response_model=Incident)
    def get_incident(incident_id: str) -> Incident:
        try:
            return service.get_incident(incident_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="incident not found") from error

    @app.post(
        "/api/incidents/{incident_id}/investigations",
        response_model=InvestigationCreated,
        status_code=status.HTTP_201_CREATED,
    )
    def create_investigation(incident_id: str) -> InvestigationCreated:
        try:
            run = service.start_investigation(incident_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="incident not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail="run could not be created") from error
        return InvestigationCreated(
            run_id=run.run_id,
            incident_id=run.report.incident_id,
            status=run.result.status.value,
            events_url=f"/api/investigations/{run.run_id}/events",
            report_url=f"/api/investigations/{run.run_id}/report",
        )

    @app.get("/api/investigations/{run_id}/events")
    def get_events(run_id: str) -> StreamingResponse:
        try:
            events = service.get_events(run_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="investigation not found") from error
        return StreamingResponse(
            _sse_frames(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/investigations/{run_id}/report", response_model=InvestigationReport)
    def get_report(run_id: str) -> InvestigationReport:
        try:
            return service.get_report(run_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="investigation not found") from error

    @app.post("/api/investigations/{run_id}/questions", response_model=QuestionAnswer)
    def answer_question(run_id: str, body: QuestionBody) -> QuestionAnswer:
        try:
            return service.answer_question(run_id, body.question)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="investigation not found") from error

    return app


def _sse_frames(events: tuple[WorkflowEvent, ...]) -> Iterator[str]:
    for event in events:
        data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
