"""Reading JSON contract files into plain Python data.

A key that appears twice in one object is an error: the plain parser would
keep the last value and drop the first without saying so. `NaN` and
`Infinity` are refused because they are not JSON.
"""

import json
from pathlib import Path
from typing import Any

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem
from utux.schemas.text_io import read_contract_text


class _DuplicateKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NotJsonConstantError(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _refuse_constant(name: str) -> None:
    raise _NotJsonConstantError(name)


def parse_json(text: str, source: str) -> object:
    """Parse JSON text into plain Python data.

    Args:
        text: The content of the file.
        source: The file name to use in error messages.

    Raises:
        ContractValidationError: If the text is not valid JSON or repeats a key.
    """
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_refuse_constant)
    except _DuplicateKeyError as error:
        problem = Problem(error.key, "key appears more than once", "duplicate_key")
    except _NotJsonConstantError as error:
        problem = Problem(DOCUMENT_FIELD, f"not valid JSON: {error} is not allowed", "invalid_json")
    except json.JSONDecodeError as error:
        problem = Problem(
            DOCUMENT_FIELD, f"not valid JSON: {error.msg} (line {error.lineno})", "invalid_json"
        )
    raise ContractValidationError(source, (problem,))


def read_json(path: Path) -> object:
    """Read and parse a JSON file.

    Raises:
        ContractValidationError: If the file cannot be read or parsed. The
            error names the path as it was given.
    """
    return parse_json(read_contract_text(path), str(path))
