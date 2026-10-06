"""Deterministic bilingual presentation; canonical diagnostic text remains verbatim."""

from financial_research.schemas.agent import (
    AgentStatus,
    ClaimSection,
    GroundedResearchAnswer,
    ResponseLanguage,
)


def render_answer(answer: GroundedResearchAnswer) -> str:
    chinese = answer.response_language == ResponseLanguage.CHINESE
    sections = {
        ClaimSection.COMPANY: "公司" if chinese else "Company",
        ClaimSection.FUNDAMENTALS: "基本面" if chinese else "Fundamentals",
        ClaimSection.MARKET: "市场" if chinese else "Market",
        ClaimSection.QUALITY: "质量" if chinese else "Quality",
    }
    lines = [
        "研究摘要" if chinese else "Research Summary",
        f"{answer.ticker} 截至 {answer.as_of_date} 的研究"
        if chinese
        else f"{answer.ticker} research as of {answer.as_of_date}",
        f"状态：{answer.agent_status} | 数据质量：{answer.quality.status}"
        if chinese
        else f"Status: {answer.agent_status} | Quality: {answer.quality.status}",
        f"技能：{answer.used_skill_ids[0]} | 就绪状态：{answer.synthesis_readiness}"
        if chinese
        else f"Skill: {answer.used_skill_ids[0]} | Readiness: {answer.synthesis_readiness}",
    ]
    if answer.agent_status == AgentStatus.BLOCKED:
        lines.append(
            "所需证据不可用，研究综合已停止。"
            if chinese
            else "Research synthesis is blocked because required evidence is unavailable."
        )
        lines.extend(f"- {context}" for context in answer.unavailable_context)
    if answer.claims:
        lines.extend(("", "关键发现" if chinese else "Key Findings"))
    for section in ClaimSection:
        claims = tuple(claim for claim in answer.claims if claim.section == section)
        if claims:
            lines.extend(("", sections[section]))
            for claim in claims:
                citations = " ".join(f"[{key}]" for key in claim.evidence_ids)
                lines.append(f"- {claim.statement} {citations}")
    lines.extend(("", "数据质量" if chinese else "Data Quality"))
    if answer.quality.issues:
        lines.append("质量诊断（原始审计文本）" if chinese else "Quality issues")
        lines.extend(
            f"- {issue.severity}: {issue.code}: {issue.message}" for issue in answer.quality.issues
        )
    if answer.limitations:
        lines.extend(("", "限制" if chinese else "Limitations"))
        lines.extend(f"- {limitation}" for limitation in answer.limitations)
    return "\n".join(lines)
