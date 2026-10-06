"""Frozen canonical contexts, injected without any financial-provider transport."""

from datetime import date
from pathlib import Path

from financial_research.evals.schemas import FrozenFixture
from financial_research.schemas.research import ResearchContext
from financial_research.skills.defaults import create_skill_registry
from financial_research.skills.registry import SkillRegistry


class FrozenContextBuilder:
    def __init__(self, fixture: FrozenFixture) -> None:
        self.fixture = fixture

    def build(self, *, ticker: str, as_of_date: date) -> ResearchContext:
        context = self.fixture.context
        if (ticker, as_of_date) != (context.ticker, context.as_of_date):
            raise ValueError("case identity does not match frozen fixture")
        return context.model_copy(deep=True)


def load_fixtures(root: Path) -> dict[str, FrozenFixture]:
    fixtures = {}
    for path in sorted((root / "fixtures").glob("*.json")):
        fixture = FrozenFixture.model_validate_json(path.read_text())
        if fixture.scenario_id in fixtures:
            raise ValueError("duplicate fixture scenario IDs")
        fixtures[fixture.scenario_id] = fixture
    if not fixtures:
        raise ValueError("no frozen fixtures found")
    return fixtures


def fixture_registry(fixture: FrozenFixture) -> SkillRegistry:
    return create_skill_registry(FrozenContextBuilder(fixture))
