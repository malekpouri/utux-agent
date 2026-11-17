"""M0-16: the user and contributor documents state what they must."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_security_policy_says_how_to_report_and_what_runs_arbitrary_code() -> None:
    text = _read("SECURITY.md")
    assert "This is a stub" not in text
    assert "private vulnerability reporting" in text
    assert "public issue" in text
    assert "Plugins and MCP servers run arbitrary code" in text


def test_contributing_guide_names_the_checks_and_the_process() -> None:
    text = _read("CONTRIBUTING.md")
    assert "This is a stub" not in text
    for command in (
        "uv run pytest",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy src",
    ):
        assert command in text
    assert "AGENTS.md" in text
    assert "Apache-2.0" in text
