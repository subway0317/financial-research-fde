"""Explicit in-process registration; no discovery, downloads or silent overwrites."""

from datetime import date
from typing import Protocol

from financial_research.exceptions import DataValidationError
from financial_research.schemas.skills import SkillDefinition, SkillResult
from financial_research.skills.context import SkillExecutionContext


class RegisteredSkill(Protocol):
    @property
    def definition(self) -> SkillDefinition: ...
    def run(self, *, ticker: str, as_of_date: date) -> SkillResult: ...
    def run_from_context(self, execution: SkillExecutionContext) -> SkillResult: ...


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, RegisteredSkill] = {}

    def register(self, skill: RegisteredSkill) -> None:
        definition = SkillDefinition.model_validate(skill.definition.model_dump())
        if definition.skill_id in self._skills:
            raise DataValidationError("duplicate skill ID registration")
        self._skills[definition.skill_id] = skill

    def get(self, skill_id: str) -> RegisteredSkill:
        return self._skills[skill_id]

    def list(self) -> tuple[SkillDefinition, ...]:
        return tuple(self._skills[key].definition for key in sorted(self._skills))
