from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, SecretStr, ValidationError

from ad_rca.agent.models import (
    InvestigationPlan,
    InvestigationReport,
    PlanningRequest,
    QuestionAnswer,
    QuestionRequest,
    ReportRequest,
)


class ModelUnavailableError(RuntimeError):
    pass


class InvalidModelOutputError(ValueError):
    pass


class JsonCompletionClient(Protocol):
    def complete_json(self, system: str, user: str) -> str: ...


class OpenAIJsonClient:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key.get_secret_value(),
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=1,
        )
        self._model = model

    def complete_json(self, system: str, user: str) -> str:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=(
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ),
                response_format={"type": "json_object"},
                temperature=0,
            )
        except OpenAIError as error:
            raise ModelUnavailableError(f"model request failed ({type(error).__name__})") from error
        content = completion.choices[0].message.content
        if not content:
            raise InvalidModelOutputError("model returned empty content")
        return content


class DeepSeekPlanner:
    def __init__(self, client: JsonCompletionClient) -> None:
        self._client = client

    def plan(self, request: PlanningRequest) -> InvestigationPlan:
        payload = {
            "incident": request.incident.model_dump(mode="json"),
            "candidates": [item.value for item in request.candidates],
            "attributions": [item.model_dump(mode="json") for item in request.attributions[:10]],
            "round_number": request.round_number,
        }
        system = (
            "You are a bounded RCA planner. Return JSON only with hypotheses and rationale. "
            "Choose one to three hypotheses only from candidates. Never calculate metrics, "
            "invent evidence, request credentials, or produce SQL."
        )
        return _validated_call(
            self._client,
            system,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            InvestigationPlan,
            lambda plan: _validate_plan(plan, request),
        )


class DeepSeekReportComposer:
    def __init__(self, client: JsonCompletionClient) -> None:
        self._client = client

    def compose(self, request: ReportRequest) -> InvestigationReport:
        result = request.result
        if result.incident is None:
            raise ValueError("cannot compose an investigation report without an incident")
        payload = {
            "run_id": request.run_id,
            "result": result.model_dump(mode="json"),
        }
        system = (
            "Write a concise Chinese RCA report as JSON matching the requested schema. "
            "Use only supplied calculations, hypotheses, and evidence IDs. Every conclusion "
            "must cite supplied evidence IDs. Do not create facts, calculations, or SQL."
        )
        return _validated_call(
            self._client,
            system,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            InvestigationReport,
            lambda report: _validate_report(report, request),
        )

    def answer(self, request: QuestionRequest) -> QuestionAnswer:
        payload = request.model_dump(mode="json")
        allowed_ids = {
            evidence_id
            for conclusion in request.report.conclusions
            for evidence_id in conclusion.evidence_ids
        }
        return _validated_call(
            self._client,
            (
                "Answer only within this incident report. Return JSON with answer and "
                "evidence_ids. Cite only supplied IDs; say evidence is insufficient when needed."
            ),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            QuestionAnswer,
            lambda answer: _validate_answer(answer, allowed_ids),
        )


def _validated_call[ModelT: BaseModel](
    client: JsonCompletionClient,
    system: str,
    user: str,
    model: type[ModelT],
    validate: Callable[[ModelT], None],
) -> ModelT:
    validation_error = ""
    for attempt in range(2):
        prompt = user
        if attempt:
            prompt = json.dumps(
                {
                    "original_request": json.loads(user),
                    "validation_error": validation_error,
                    "instruction": "Return corrected JSON only.",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        raw = client.complete_json(system, prompt)
        try:
            parsed = model.model_validate_json(raw)
            validate(parsed)
            return parsed
        except (ValidationError, ValueError) as error:
            validation_error = str(error)[:1000]
    raise InvalidModelOutputError("model output failed validation after one repair attempt")


def _validate_plan(plan: InvestigationPlan, request: PlanningRequest) -> None:
    if any(item not in request.candidates for item in plan.hypotheses):
        raise ValueError("model selected a hypothesis outside deterministic candidates")
    if any(item in request.investigated for item in plan.hypotheses):
        raise ValueError("model selected an already investigated hypothesis")


def _validate_report(report: InvestigationReport, request: ReportRequest) -> None:
    result = request.result
    if result.incident is None:
        raise ValueError("missing incident")
    if report.run_id != request.run_id or report.incident_id != result.incident.incident_id:
        raise ValueError("model changed run or incident identity")
    allowed_ids = {item.evidence_id for item in (*result.evidence, *result.contradictions)}
    result_hypotheses = {item.hypothesis for item in result.hypotheses}
    for conclusion in report.conclusions:
        if conclusion.hypothesis not in result_hypotheses:
            raise ValueError("model created a new root-cause type")
        if any(evidence_id not in allowed_ids for evidence_id in conclusion.evidence_ids):
            raise ValueError("model created an unknown evidence ID")


def _validate_answer(answer: QuestionAnswer, allowed_ids: set[str]) -> None:
    if any(evidence_id not in allowed_ids for evidence_id in answer.evidence_ids):
        raise ValueError("model created an unknown evidence ID")
