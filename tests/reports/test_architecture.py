import ast
from pathlib import Path


def test_reports_preserve_dependency_boundaries_and_compiler_is_pure():
    root = Path(__file__).parents[2] / "src/financial_research/reports"
    violations = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for module in modules:
                if module.startswith(
                    (
                        "openai",
                        "financial_research.providers",
                        "financial_research.llm.openai_responses",
                        "financial_research.evals",
                        "financial_research.tools",
                        "financial_research.skills",
                        "financial_research.market",
                        "financial_research.fundamentals",
                        "financial_research.research",
                        "financial_research.company",
                    )
                ):
                    violations.append((path.name, module))
                if path.name == "compiler.py" and module.startswith(
                    (
                        "financial_research.llm",
                        "financial_research.api",
                        "financial_research.agent.service",
                    )
                ):
                    violations.append((path.name, module))
                if module.startswith("financial_research.api") and path.name not in {
                    "cli.py",
                    "smoke.py",
                }:
                    violations.append((path.name, module))
    assert violations == []


def test_service_calls_shared_executor_and_compiler_once_without_judge():
    root = Path(__file__).parents[2] / "src/financial_research"
    tree = ast.parse((root / "reports/service.py").read_text())
    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert calls.count("execute_validated_plan") == calls.count("compile") == 1
    assert all(
        name not in calls
        for name in (
            "generate",
            "judge",
            "validate_grounding",
            "validate_research_policy",
            "synthesis_readiness",
        )
    )
    agent_tree = ast.parse((root / "agent/service.py").read_text())
    for name in ("_run", "execute_validated_plan"):
        function = next(
            node
            for node in ast.walk(agent_tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_execute"
            for node in ast.walk(function)
        )


def test_api_route_contains_no_compilation_hashing_or_export_logic():
    route = Path(__file__).parents[2] / "src/financial_research/api/routes/reports.py"
    tree = ast.parse(route.read_text())
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    calls = [
        node
        for statement in function.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    ]
    # HTTP adds the explicit disclosure boundary; compilation/export remain in
    # their existing internal layers. Only these two calls belong in the route.
    assert len(calls) == 2
    assert isinstance(calls[0].func, ast.Name) and calls[0].func.id == "project_report"
    assert isinstance(calls[1].func, ast.Attribute) and calls[1].func.attr == "run"
