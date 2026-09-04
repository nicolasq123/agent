from ad_rca.application.natural_language_service import NaturalLanguageAnalysis
from ad_rca.domain.models import SliceKey


def render_analysis_markdown(analysis: NaturalLanguageAnalysis) -> str:
    intent = analysis.intent
    result = analysis.run.result
    report = analysis.run.report
    lines = [
        "# ProfitLens 利润分析",
        "",
        f"- 分析时段：{intent.window.start.isoformat()} 至 {intent.window.end.isoformat()}",
        f"- 请求范围：{_scope(intent.scope)}",
        f"- 实际分析范围：{_scope(analysis.selected_scope)}",
        "",
    ]
    incident = result.incident
    if incident is None:
        lines.extend(("## 结果", "", report.summary))
        return "\n".join(lines)

    lines.extend(
        (
            "## 利润损失",
            "",
            f"- 实际利润：{incident.actual_profit:.2f}",
            f"- 预期利润：{incident.expected_profit:.2f}",
            f"- 利润损失：{incident.lost_profit:.2f}",
            "",
            "## 结论与 Evidence",
            "",
        )
    )
    if not report.conclusions:
        lines.append("证据不足，当前无法确认根因。")
    for index, conclusion in enumerate(report.conclusions, start=1):
        evidence = ", ".join(conclusion.evidence_ids) or "无"
        lines.extend(
            (
                f"{index}. {conclusion.statement}",
                f"   - 置信度：{conclusion.confidence.value}",
                f"   - 解释损失：{conclusion.explained_loss:.2f}",
                f"   - Evidence IDs：{evidence}",
            )
        )
    if report.recommendations:
        lines.extend(("", "## 建议", ""))
        lines.extend(f"- {item}" for item in report.recommendations)
    if analysis.run.warnings:
        lines.extend(("", f"提示：{', '.join(analysis.run.warnings)}"))
    return "\n".join(lines)


def _scope(scope: SliceKey) -> str:
    dimensions = scope.dimensions()
    if not dimensions:
        return "全局"
    labels = {
        "advertiser_id": "广告主",
        "offer_id": "Offer",
        "channel_id": "渠道",
        "country": "国家",
    }
    return "，".join(f"{labels[name]}={value}" for name, value in dimensions)
