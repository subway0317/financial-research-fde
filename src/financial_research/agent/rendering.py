"""Render validated fields and citations; no additional interpretation or financial arithmetic."""

from financial_research.schemas.agent import AgentStatus, ClaimSection, GroundedResearchAnswer


def render_answer(answer: GroundedResearchAnswer) -> str:
    lines = [
        f"{answer.ticker} research as of {answer.as_of_date}",
        f"Status: {answer.agent_status} | Quality: {answer.quality.status}",
        f"Skill: {answer.used_skill_ids[0]} | Readiness: {answer.synthesis_readiness}",
    ]
    if answer.agent_status == AgentStatus.BLOCKED:
        lines.append("Research synthesis is blocked because required evidence is unavailable.")
        lines.extend(f"- {context}" for context in answer.unavailable_context)
    for section in ClaimSection:
        claims = tuple(claim for claim in answer.claims if claim.section == section)
        if claims:
            lines.extend(("", f"{section.value.title()}"))
            for claim in claims:
                citations = " ".join(f"[{key}]" for key in claim.evidence_ids)
                lines.append(f"- {claim.statement} {citations}")
    if answer.quality.issues:
        lines.extend(("", "Quality issues"))
        lines.extend(
            f"- {issue.severity}: {issue.code}: {issue.message}" for issue in answer.quality.issues
        )
    if answer.limitations:
        lines.extend(("", "Limitations"))
        lines.extend(f"- {limitation}" for limitation in answer.limitations)
    return "\n".join(lines)
