import ast
from pathlib import Path


def test_production_layers_never_import_evaluations_or_judge():
    root = Path(__file__).parents[2] / "src/financial_research"
    violations = []
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[0] == "evals":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(name.startswith("financial_research.evals") for name in names):
                violations.append(str(path))
    assert violations == []
