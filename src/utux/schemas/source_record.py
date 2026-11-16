"""Schema of a source record, the metadata file of one source in `sources/`.

A source record says where a source came from, under which terms it may be
used, and what is known about the text that was stored for it (specification,
section 14; RFC-001, S2; RFC-002, section 2). The stored text itself is not
part of the record.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, model_validator

from utux.schemas.base import ContractDocument, field_problem, raise_field_problems
from utux.schemas.claim_ledger import CheckedText, ExtractionQuality
from utux.schemas.common import Identifier, NonEmptyText, Sha256Hash, UtcTimestamp
from utux.schemas.json_io import read_json


class Redistribution(StrEnum):
    """What the licence permits to be redistributed."""

    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"
    NONE = "none"


class SourceVersion(StrEnum):
    """Which version of the source was retrieved."""

    PUBLISHER = "publisher"
    PREPRINT = "preprint"
    INDEX_ABSTRACT = "index_abstract"


_TEXT_FIELDS = ("text_hash", "extraction_method", "extraction_tool_version", "extraction_quality")
_REQUIRED_WITH_TEXT = ("text_hash", "extraction_method", "extraction_quality")


class SourceRecord(ContractDocument):
    """What is known about one source. Every field is required; some may be null.

    Attributes:
        source_id: Identifier of the source, such as `doi:10.0000/example`.
            Evidence entries in the claim ledger refer to it.
        url: The original URL, http or https.
        licence: The licence or access terms.
        redistribution: What the licence permits to be redistributed.
        source_version: Which version of the source was retrieved.
        retrieval_route: A code for how the source was retrieved, for example
            `openalex`.
        retrieved_at: When it was retrieved.
        stored_text: Which text is stored, `abstract` or `full_text`, or null
            when no text is stored.
        text_hash: Hash of the stored text. Null exactly when no text is
            stored.
        extraction_method: A code for how the text was extracted. Null exactly
            when no text is stored.
        extraction_tool_version: The extraction tool and its version, or null.
        extraction_quality: The quality rating of the stored text. Null
            exactly when no text is stored.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    source_id: NonEmptyText
    url: Annotated[str, Field(pattern=r"^https?://[^\s/]+\S*$", strict=True)]
    licence: NonEmptyText
    redistribution: Redistribution
    source_version: SourceVersion
    retrieval_route: Identifier
    retrieved_at: UtcTimestamp
    stored_text: CheckedText | None
    text_hash: Sha256Hash | None
    extraction_method: Identifier | None
    extraction_tool_version: NonEmptyText | None
    extraction_quality: ExtractionQuality | None

    @model_validator(mode="after")
    def _text_fields_follow_stored_text(self) -> Self:
        if self.stored_text is None:
            problems = [
                field_problem(
                    "not_allowed_without_text", "must be null when no text is stored", name
                )
                for name in _TEXT_FIELDS
                if getattr(self, name) is not None
            ]
        else:
            problems = [
                field_problem("required_with_text", "must not be null when text is stored", name)
                for name in _REQUIRED_WITH_TEXT
                if getattr(self, name) is None
            ]
        raise_field_problems(type(self).__name__, problems)
        return self


def load_source_record(path: Path) -> SourceRecord:
    """Read and validate a source record file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            record. The error names the path as it was given.
    """
    return SourceRecord.validate_document(read_json(path), str(path))
