"""Checks that every contract schema must pass, shared by the M0-06b test modules.

Each test module states its own table of invalid fixtures and calls these
helpers, so the expected (field, code) of every fixture stays written out in
the module that owns it.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError
from utux.schemas.base import ContractDocument

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures"

Row = tuple[str, str, str]
Loader = Callable[[Path], ContractDocument]


def check_table(contract: str, table: list[Row]) -> None:
    """At least five invalid fixtures, no repeated reason, and none unlisted."""
    reasons = [(field, code) for _, field, code in table]
    assert len(table) >= 5
    assert len(set(reasons)) == len(reasons)
    on_disk = sorted(path.name for path in (FIXTURES_ROOT / contract / "invalid").glob("*.json"))
    assert on_disk == sorted(name for name, _, _ in table)


def check_invalid(contract: str, load: Loader, row: Row) -> None:
    """The fixture fails for exactly its own reason, and the message names the file."""
    name, field, code = row
    path = FIXTURES_ROOT / contract / "invalid" / name
    with pytest.raises(ContractValidationError) as caught:
        load(path)
    error = caught.value
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    assert error.source == str(path)
    assert str(error) == f"{path}: {field}: {error.problems[0].reason}"


def check_round_trip(model: type[Any], load: Loader, path: Path) -> None:
    """A valid fixture survives reading, writing and reading again unchanged."""
    document = load(path)
    text = document.to_json()  # type: ignore[attr-defined]
    again = model.from_json(text)
    assert again == document
    assert again.to_json() == text
    assert text.endswith("\n")
    assert json.loads(text) == json.loads(path.read_text(encoding="utf-8"))


def valid_paths(contract: str) -> list[Path]:
    return sorted((FIXTURES_ROOT / contract / "valid").glob("*.json"))


def read_valid(contract: str, name: str) -> dict[str, Any]:
    document = json.loads((FIXTURES_ROOT / contract / "valid" / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def problems(model: type[Any], document: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        model.from_json(json.dumps(document), source="document.json")
    return [(p.field, p.code) for p in caught.value.problems]
