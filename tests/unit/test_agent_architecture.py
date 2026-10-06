import ast
from pathlib import Path


def test_agent_llm_and_core_dependency_boundaries():
    root = Path(__file__).parents[2] / "src/financial_research"
    sdk_path = root / "llm/openai_responses.py"
    lower_layers = {
        "company",
        "fundamentals",
        "market",
        "providers",
        "quality",
        "research",
        "tools",
        "skills",
    }
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
                if module.startswith("openai") and path != sdk_path:
                    violations.append((path, module))
                if layer in lower_layers and module.startswith(
                    ("financial_research.agent", "financial_research.llm")
                ):
                    violations.append((path, module))
                if layer == "agent" and module.startswith(
                    (
                        "financial_research.tools",
                        "financial_research.providers",
                        "financial_research.fundamentals",
                        "financial_research.market",
                        "financial_research.research",
                        "financial_research.api",
                        "fastapi",
                    )
                ):
                    violations.append((path, module))
                if (
                    layer == "agent"
                    and path.name != "smoke.py"
                    and module.startswith("financial_research.llm.openai_responses")
                ):
                    violations.append((path, module))
                if layer == "llm" and module.startswith(
                    (
                        "financial_research.skills",
                        "financial_research.tools",
                        "financial_research.providers",
                        "financial_research.agent",
                    )
                ):
                    violations.append((path, module))
    assert violations == []
