"""Schema of `outputs/metrics.json`, the computed values a step's code writes.

Numbers never come from model text. The code a step runs writes its values
to `metrics.json` in its output directory, in this shape, and utux turns
each entry into one result record (`utux.workspace.results`). An entry holds
what a result record holds except its id, run and source, which utux adds.
"""

import json
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.common import NonEmptyText
from utux.schemas.json_io import parse_json, read_json


class MetricEntry(ContractPart):
    """One computed value. Every field is required; `model` and `split` may be null.

    The fields mean what they mean in a result record
    (`utux.schemas.result_record.ResultRecord`).
    """

    metric: NonEmptyText
    value: Annotated[float, Field(allow_inf_nan=False, strict=True)]
    unit: NonEmptyText
    dataset: NonEmptyText
    model: NonEmptyText | None
    split: NonEmptyText | None
    tolerance: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


class MetricsFile(ContractDocument):
    """The content of a step's `metrics.json`.

    Attributes:
        entries: The values, possibly none. No two entries have the same
            metric, dataset, model and split (`duplicate_entry`).
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    entries: tuple[MetricEntry, ...]

    @model_validator(mode="after")
    def _each_value_once(self) -> Self:
        errors: list[InitErrorDetails] = []
        first: dict[tuple[str, str, str | None, str | None], int] = {}
        for position, entry in enumerate(self.entries):
            key = (entry.metric, entry.dataset, entry.model, entry.split)
            if key in first:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "duplicate_entry",
                            "the same metric, dataset, model and split is at position {first}",
                            {"first": first[key]},
                        ),
                        "loc": ("entries", position),
                        "input": None,
                    }
                )
            else:
                first[key] = position
        if errors:
            raise ValidationError.from_exception_data(type(self).__name__, errors)
        return self

    @classmethod
    def from_json(cls, text: str, source: str = "metrics.json") -> Self:
        """Parse and validate the text of a metrics file.

        Raises:
            ContractValidationError: If the text is not a valid metrics file.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json(self) -> str:
        """Return the metrics file as JSON text."""
        return json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_metrics_file(path: Path) -> MetricsFile:
    """Read and validate a metrics file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            metrics file. The error names the path as it was given.
    """
    return MetricsFile.validate_document(read_json(path), str(path))
