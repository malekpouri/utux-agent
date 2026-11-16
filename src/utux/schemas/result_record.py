"""Schema of a result record, a line of `results.jsonl`.

A number is never stored bare: each computed value is a record that states
its metric, unit, dataset, model, split, run and tolerance, so its meaning
is checked along with its value (specification, section 7).
"""

import json
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field

from utux.schemas.base import ContractDocument
from utux.schemas.common import NonEmptyText, RelativePath, ResultId
from utux.schemas.json_io import parse_json, read_json


class ResultRecord(ContractDocument):
    """One computed value with everything that gives it meaning.

    Every field is required; `model` and `split` may be null.

    Attributes:
        id: Id of the record.
        metric: What was measured, for example `AUC`.
        value: The value.
        unit: The unit of the value.
        dataset: The dataset the value was computed on.
        model: The model the value belongs to, or null when it belongs to
            none, as for a statistic of a dataset.
        split: The split of the dataset, for example `test`, or null.
        run_id: The run that produced the value.
        source: The file inside the project that holds the value.
        tolerance: How far a number in the manuscript may differ from the
            value: an absolute difference, in the unit of the value. Zero
            means it must match exactly.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    id: ResultId
    metric: NonEmptyText
    value: Annotated[float, Field(allow_inf_nan=False, strict=True)]
    unit: NonEmptyText
    dataset: NonEmptyText
    model: NonEmptyText | None
    split: NonEmptyText | None
    run_id: NonEmptyText
    source: RelativePath
    tolerance: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]

    @classmethod
    def from_json(cls, text: str, source: str = "result record") -> Self:
        """Parse and validate the JSON text of one result record.

        Raises:
            ContractValidationError: If the text is not a valid record.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json_line(self) -> str:
        """Return the record as one line of JSON that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


def load_result_record(path: Path) -> ResultRecord:
    """Read and validate a file that holds one result record as a JSON document.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            record. The error names the path as it was given.
    """
    return ResultRecord.validate_document(read_json(path), str(path))
