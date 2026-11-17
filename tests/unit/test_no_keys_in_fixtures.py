"""M0-10: no fixture holds an API key or an authorization header."""

import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

PATTERNS = [
    re.compile(r"sk-or-v1-[0-9a-f]{16,}"),  # OpenRouter keys
    re.compile(r"sk-(proj-)?[A-Za-z0-9_-]{20,}"),  # OpenAI keys
    re.compile(r"Bearer\s+\S+"),
    re.compile(r"(?i)authorization\s*[:=]"),
    re.compile(r"synthetic-test-key-"),  # the key the tests set
]


def _files() -> list[Path]:
    return sorted(path for path in FIXTURES.rglob("*") if path.is_file())


def test_there_are_fixtures_to_check() -> None:
    assert len(_files()) > 100


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.pattern)
def test_no_fixture_holds_a_key(pattern: re.Pattern[str]) -> None:
    found = [
        str(path.relative_to(FIXTURES))
        for path in _files()
        if pattern.search(path.read_bytes().decode("utf-8", errors="replace"))
    ]
    assert found == []
