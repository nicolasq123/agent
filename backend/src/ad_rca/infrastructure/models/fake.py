from ad_rca.agent.models import (
    InvestigationPlan,
    InvestigationReport,
    PlanningRequest,
    QuestionAnswer,
    QuestionRequest,
    ReportConclusion,
    ReportRequest,
)
from ad_rca.domain.enums import HypothesisStatus


class FakePlanner:
    def plan(self, request: PlanningRequest) -> InvestigationPlan:
        available = tuple(
            candidate for candidate in request.candidates if candidate not in request.investigated
        )
        selected = available[:3]
        if not selected:
            raise ValueError("no uninvestigated candidates are available")
        return InvestigationPlan(
            hypotheses=selected,
            rationale="Deterministic candidate priority from the RCA engine.",
        )


class TemplateReportComposer:
    def compose(self, request: ReportRequest) -> InvestigationReport:
        result = request.result
        if result.incident is None:
            raise ValueError("cannot compose an investigation report without an incident")
        conclusions = tuple(
            ReportConclusion(
                hypothesis=item.hypothesis,
                confidence=item.confidence,
                statement=_conclusion_statement(item.hypothesis.value),
                evidence_ids=tuple(evidence.evidence_id for evidence in item.evidence),
                explained_loss=item.explained_loss,
            )
            for item in result.hypotheses
            if item.status is HypothesisStatus.SUPPORTED and item.evidence
        )
        incident = result.incident
        summary = (
            f"检测到利润异常：实际利润 {incident.actual_profit:.2f}，"
            f"预期利润 {incident.expected_profit:.2f}，损失 {incident.lost_profit:.2f}。"
        )
        return InvestigationReport(
            run_id=request.run_id,
            incident_id=incident.incident_id,
            status=result.status,
            summary=summary,
            conclusions=conclusions,
            recommendations=tuple(_recommendation(item.hypothesis.value) for item in conclusions),
            generated_without_llm=True,
        )

    def answer(self, request: QuestionRequest) -> QuestionAnswer:
        evidence_ids = tuple(
            evidence_id
            for conclusion in request.report.conclusions
            for evidence_id in conclusion.evidence_ids
        )
        return QuestionAnswer(
            answer=(
                "当前回答基于已完成调查报告。"
                f"问题：{request.question}；结论摘要：{request.report.summary}"
            ),
            evidence_ids=evidence_ids,
            generated_without_llm=True,
        )


def _conclusion_statement(hypothesis: str) -> str:
    labels = {
        "payout_price_increase": "转化佣金上涨是已验证的利润损失原因。",
        "revenue_price_decrease": "转化收入下降是已验证的利润损失原因。",
        "traffic_volume_drop": "流量下降是已验证的利润损失原因。",
        "traffic_mix_shift": "流量结构变化是已验证的利润损失原因。",
        "conversion_path_failure": "转化链路异常是已验证的利润损失原因。",
        "cap_reached": "投放上限触发是已验证的利润损失原因。",
        "traffic_quality_degradation": "流量质量下降是已验证的利润损失原因。",
    }
    return labels[hypothesis]


def _recommendation(hypothesis: str) -> str:
    return f"复核 {hypothesis} 对应配置和监控告警，确认后由人工处理。"
