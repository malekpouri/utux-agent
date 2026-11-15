"""Enumerations and field types shared by several contract schemas."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field


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
