"""Observe registry execution, production dependency boundaries and published policy."""

import ast
from datetime import date
from pathlib import Path

from financial_research.agent.errors import GroundingValidationError
from financial_research.agent.policy import validate_research_policy
from financial_research.schemas.agent import GroundedResearchAnswer
from financial_research.schemas.skills import SkillResult
from financial_research.skills.context import SkillExecutionContext
from financial_research.skills.registry import RegisteredSkill, SkillRegistry


class ObservedSkill:
    def __init__(self, original: RegisteredSkill, observer: "ObservedRegistry") -> None:
        self.original = original
        self.observer = observer
        self.definition = original.definition

    def run(self, *, ticker: str, as_of_date: date) -> SkillResult:
        self.observer.executions.append(self.definition.skill_id)
        result = self.original.run(ticker=ticker, as_of_date=as_of_date)
        self.observer.result = result
        return result

    def run_from_context(self, execution: SkillExecutionContext) -> SkillResult:
        self.observer.executions.append(self.definition.skill_id)
        result = self.original.run_from_context(execution)
        self.observer.result = result
        return result


class ObservedRegistry(SkillRegistry):
    def __init__(self, registry: SkillRegistry) -> None:
        super().__init__()
        self.executions: list[str] = []
        self.lookups: list[str] = []
        self.result: SkillResult | None = None
        for definition in registry.list():
            self.register(ObservedSkill(registry.get(definition.skill_id), self))

    def get(self, skill_id: str) -> RegisteredSkill:
        self.lookups.append(skill_id)
        return super().get(skill_id)


def agent_dependency_violations() -> int:
    root = Path(__file__).resolve().parents[1]
    violations = 0
    for path in sorted((root / "agent").glob("*.py")):
        if path.name == "smoke.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            violations += sum(
                module.startswith(
                    (
                        "financial_research.tools",
                        "financial_research.providers",
                        "financial_research.research",
                        "financial_research.fundamentals",
                        "financial_research.market",
                        "financial_research.evals",
                    )
                )
                for module in modules
            )
    return violations


def policy_passes(answer: GroundedResearchAnswer) -> bool:
    try:
        for claim in answer.claims:
            validate_research_policy(claim.statement)
    except GroundingValidationError:
        return False
    return True
