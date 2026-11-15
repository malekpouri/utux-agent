"""Reading YAML contract files into plain Python data.

Only safe YAML is accepted. A key that appears twice in one mapping is an
error: the plain parser would keep the last value and drop the first without
saying so.
"""

from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem
from utux.schemas.text_io import read_contract_text


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: str, line: int) -> None:
        super().__init__(key)
        self.key = key
        self.line = line


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if isinstance(key, Hashable):
                if key in seen:
                    raise _DuplicateKeyError(str(key), key_node.start_mark.line + 1)
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def parse_yaml(text: str, source: str) -> object:
    """Parse YAML text into plain Python data.

    Args:
        text: The content of the file.
        source: The file name to use in error messages.

    Raises:
        ContractValidationError: If the text is not valid YAML or repeats a key.
    """
    try:
        # _UniqueKeyLoader derives from SafeLoader, so this is a safe load.
        return yaml.load(text, Loader=_UniqueKeyLoader)
    except _DuplicateKeyError as error:
        problem = Problem(
            error.key, f"key appears more than once (line {error.line})", "duplicate_key"
        )
    except yaml.MarkedYAMLError as error:
        where = f" (line {error.problem_mark.line + 1})" if error.problem_mark else ""
        problem = Problem(DOCUMENT_FIELD, f"not valid YAML: {error.problem}{where}", "invalid_yaml")
    except yaml.YAMLError:
        problem = Problem(DOCUMENT_FIELD, "not valid YAML", "invalid_yaml")
    raise ContractValidationError(source, (problem,))


def read_yaml(path: Path) -> object:
    """Read and parse a YAML file.

    Raises:
        ContractValidationError: If the file cannot be read or parsed. The
            error names the path as it was given.
    """
    return parse_yaml(read_contract_text(path), str(path))
