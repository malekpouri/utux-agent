"""Base classes shared by every file-contract schema.

A contract file is described by one `ContractDocument` subclass. Nested
objects inside it are `ContractPart` subclasses. Both reject unknown keys and
are immutable. Validation failures are reported as one
`ContractValidationError` that lists every problem with its field and reason.
"""

import json
from collections.abc import Mapping
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.errors import DOCUMENT_FIELD, ContractValidationError, Problem
from utux.schemas.json_io import parse_json

# Pydantic marks an error on a mapping key with this extra location entry.
_KEY_MARKER = "[key]"

_REASONS = {
    "missing": "required field is missing",
    "extra_forbidden": "unknown key",
}

_CODES = {
    "extra_forbidden": "unknown_key",
}


class ContractPart(BaseModel):
    """A nested object inside a contract file."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractDocument(ContractPart):
    """A whole contract file.

    Subclasses set `SCHEMA_VERSION` to the version they describe. The file
    must state `schema_version` itself; it is never assumed.
    """

    SCHEMA_VERSION: ClassVar[int]

    schema_version: StrictInt

    @classmethod
    def validate_document(cls, data: object, source: str) -> Self:
        """Validate parsed file content and return the model.

        Args:
            data: The parsed content of the file.
            source: The file name to use in error messages.

        Raises:
            ContractValidationError: If the content does not match the schema.
        """
        if not isinstance(data, Mapping):
            raise ContractValidationError(
                source,
                (Problem(DOCUMENT_FIELD, "the file must contain a mapping", "not_a_mapping"),),
            )
        version_problem = cls._schema_version_problem(data.get("schema_version"))
        if version_problem is not None:
            # A file of another version cannot be judged by this schema, so
            # nothing else is reported.
            raise ContractValidationError(source, (version_problem,))
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise ContractValidationError(source, _problems(error)) from error

    @classmethod
    def from_json(cls, text: str, source: str = "document") -> Self:
        """Parse and validate the JSON text of one document.

        Args:
            text: The JSON text.
            source: The file name to use in error messages.

        Raises:
            ContractValidationError: If the text is not a valid document.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json(self) -> str:
        """Return the document as indented JSON text that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def _schema_version_problem(cls, found: object) -> Problem | None:
        # bool is a subclass of int; leave it, and anything that is not an
        # integer, to the ordinary field validation.
        if not isinstance(found, int) or isinstance(found, bool) or found == cls.SCHEMA_VERSION:
            return None
        if found > cls.SCHEMA_VERSION:
            return Problem(
                "schema_version",
                f"the file was written with a newer schema version ({found}); "
                f"this version of utux supports {cls.SCHEMA_VERSION}",
                "schema_version_newer",
            )
        return Problem(
            "schema_version",
            f"schema version {found} is not supported; "
            f"this version of utux supports {cls.SCHEMA_VERSION}",
            "schema_version_unsupported",
        )


def field_problem(code: str, reason: str, *loc: str | int) -> InitErrorDetails:
    """Describe one problem of a rule between fields, at the given field path."""
    return {"type": PydanticCustomError(code, reason), "loc": loc, "input": None}


def raise_field_problems(title: str, problems: list[InitErrorDetails]) -> None:
    """Raise the problems of a rule between fields, if there are any."""
    if problems:
        raise ValidationError.from_exception_data(title, problems)


def _problems(error: ValidationError) -> tuple[Problem, ...]:
    problems = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        kind = item["type"]
        field = ".".join(str(part) for part in item["loc"] if part != _KEY_MARKER)
        problems.append(
            Problem(
                field=field or DOCUMENT_FIELD,
                reason=_REASONS.get(kind, item["msg"]),
                code=_CODES.get(kind, kind),
            )
        )
    return tuple(problems)
