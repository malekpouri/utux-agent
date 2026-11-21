"""Enumerations and field types shared by several contract schemas."""

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError


class Stage(StrEnum):
    """The six pipeline stages of the specification, section 4."""

    IDEATION = "ideation"
    LITERATURE = "literature"
    METHODOLOGY = "methodology"
    IMPLEMENTATION = "implementation"
    EXPERIMENT = "experiment"
    WRITING = "writing"


class Tier(StrEnum):
    """The three model tiers of the specification, section 9."""

    LIGHT = "light"
    STANDARD = "standard"
    STRONG = "strong"


Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
"""A lower-case name such as a profile, a domain pack or an agent role."""

PositiveUsd = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
"""An amount of money in US dollars, greater than zero."""

PositiveInt = Annotated[int, Field(gt=0, strict=True)]
"""A whole number greater than zero."""

NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
"""A whole number that may be zero."""

Sha256Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$", strict=True)]
"""A content hash: `sha256:` followed by 64 lower-case hexadecimal digits."""

ArtifactId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*-v[0-9]{3,}$", strict=True)]
"""An artifact version, a name and a version number, for example `method-v003`."""

Actor = Annotated[str, Field(pattern=r"^(agent|human|system):[a-z0-9][a-z0-9_.-]*$", strict=True)]
"""Who did something: `agent:<role>`, `human:<id>` or `system:<component>`."""

_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")


def _check_utc_timestamp(value: str) -> str:
    try:
        if _UTC_TIMESTAMP.fullmatch(value) is None:
            raise ValueError
        # The pattern fixes the form; this rejects dates and times that do
        # not exist, such as 30 February.
        datetime.fromisoformat(value.removesuffix("Z"))
    except ValueError:
        raise PydanticCustomError(
            "utc_timestamp",
            "must be a UTC timestamp in ISO 8601 form ending in Z, "
            "for example 2026-11-15T10:00:00Z",
        ) from None
    return value


UtcTimestamp = Annotated[str, Field(strict=True), AfterValidator(_check_utc_timestamp)]
"""A UTC timestamp in ISO 8601 form with a `Z` suffix.

It is kept as text, so a file that is read and written again keeps the exact
timestamp it had.
"""

EventId = Annotated[str, Field(pattern=r"^e-[0-9]{6,}$", strict=True)]
"""An event id: `e-` and a number of at least six digits, for example `e-000913`."""

NonEmptyText = Annotated[str, Field(min_length=1, strict=True)]
"""Text that may not be empty."""

Count = Annotated[int, Field(ge=0, strict=True)]
"""A whole number of zero or more, such as a token count or a duration."""

NonNegativeUsd = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
"""An amount of money in US dollars that may be zero."""

ClaimId = Annotated[str, Field(pattern=r"^C[0-9]{3,}$", strict=True)]
"""A claim id: `C` and at least three digits, for example `C031`."""

ResultId = Annotated[str, Field(pattern=r"^R[0-9]{3,}$", strict=True)]
"""A result record id: `R` and at least three digits, for example `R0042`."""


def _check_relative_path(value: str) -> str:
    parts = value.split("/")
    if not value or "\\" in value or any(part in ("", ".", "..") for part in parts):
        raise PydanticCustomError(
            "not_relative_path",
            "must be a path inside the project, relative, with / as separator "
            "and without . or .. parts",
        )
    return value


RelativePath = Annotated[str, Field(strict=True), AfterValidator(_check_relative_path)]
"""A path inside the project directory, such as `runs/r012/metrics.json`.

Absolute paths and paths with `..` are refused, so a contract file can never
point outside its project.
"""

Scalar = str | int | float | bool | None
"""A value in a flat object: a string, a number, a boolean or null."""


def _check_flat(value: object) -> object:
    """Reject nested values before the field's own type check runs.

    One problem is reported per offending value, on its own key.
    """
    if not isinstance(value, dict):
        return value
    errors: list[InitErrorDetails] = [
        {
            "type": PydanticCustomError(
                "not_scalar", "must be a string, a number, a boolean or null"
            ),
            "loc": (str(key),),
            "input": None,
        }
        for key, item in value.items()
        if not (item is None or isinstance(item, str | int | float | bool))
        or (isinstance(item, float) and not math.isfinite(item))
    ]
    if errors:
        raise ValidationError.from_exception_data("flat object", errors)
    return value


FlatObject = Annotated[dict[str, Scalar], BeforeValidator(_check_flat)]
"""An object whose values are all scalars. A nested value has code `not_scalar`."""

RunId = Annotated[str, Field(pattern=r"^r[0-9]{3,}$", strict=True)]
"""A run id: `r` and at least three digits, for example `r012`."""


class LimitKind(StrEnum):
    """The limit that stopped a run (run results and run manifests)."""

    WALL_CLOCK = "wall_clock"
    MEMORY = "memory"
    PROCESSES = "processes"
    DISK = "disk"
    OUTPUT_SIZE = "output_size"
