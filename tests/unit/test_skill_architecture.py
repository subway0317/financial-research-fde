import ast
import importlib
from pathlib import Path

from pydantic import BaseModel

from financial_research.skills import create_skill_registry


def test_registry_schema_references_resolve_without_network() -> None:
    for definition in create_skill_registry().list():
        for reference in (definition.input_type, definition.output_type):
            module, name = reference.rsplit(".", 1)
            assert issubclass(getattr(importlib.import_module(module), name), BaseModel)


def test_skill_dependency_direction_and_no_transport_or_agent_imports() -> None:
    root = Path(__file__).parents[2] / "src/financial_research"
    forbidden_sdks = (
        "openai",
        "anthropic",
        "langchain",
        "langgraph",
        "crewai",
        "autogen",
        "pydantic_ai",
    )
    violations = []
    for path in root.rglob("*.py"):
        layer = path.relative_to(root).parts[0]
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for module in modules:
                if layer != "skills" and module.startswith("financial_research.skills"):
                    violations.append((path, module))
                if layer == "skills" and module.startswith(
                    ("fastapi", "financial_research.api", *forbidden_sdks)
                ):
                    violations.append((path, module))
    assert violations == []
