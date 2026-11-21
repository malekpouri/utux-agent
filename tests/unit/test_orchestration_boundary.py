"""M1-10: LangGraph is used only inside utux.core.

The fallback of ADR-0001 then stays a change inside one package.
"""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "utux"
ORCHESTRATION = ("langgraph", "langchain", "langchain_core", "langsmith")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_no_module_outside_utux_core_imports_the_orchestration_library() -> None:
    offenders = [
        str(path.relative_to(SOURCE))
        for path in sorted(SOURCE.rglob("*.py"))
        if path.relative_to(SOURCE).parts[0] != "core" and _imports(path) & set(ORCHESTRATION)
    ]
    assert offenders == []


def test_utux_core_does_import_it() -> None:
    used = set().union(*(_imports(p) for p in (SOURCE / "core").rglob("*.py")))
    assert "langgraph" in used
