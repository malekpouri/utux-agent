"""Reading the text of a contract file."""

from pathlib import Path

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem


def read_contract_text(path: Path) -> str:
    """Read a contract file as UTF-8 text.

    Raises:
        ContractValidationError: If the file cannot be read. The error names
            the path as it was given.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        detail = error.strerror if isinstance(error, OSError) else "not UTF-8 text"
        problem = Problem(DOCUMENT_FIELD, f"the file cannot be read: {detail}", "unreadable")
        raise ContractValidationError(str(path), (problem,)) from error
