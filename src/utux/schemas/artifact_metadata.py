"""Schema of the metadata sidecar that accompanies every stage output.

The sidecar records what an output was built from, so the chain from the
manuscript back to the inputs can be rebuilt (specification, section 7,
"Artifact metadata and validity"). One sidecar is kept per artifact version
under `.utux/meta/`.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.schemas.base import ContractDocument
from utux.schemas.common import Actor, ArtifactId, Sha256Hash, Stage, UtcTimestamp
from utux.schemas.json_io import parse_json, read_json


class ArtifactState(StrEnum):
    """Whether an artifact may still be used.

    An artifact becomes `stale` when something it was built from has changed.
    """

    VALID = "valid"
    STALE = "stale"


class ArtifactMetadata(ContractDocument):
    """The content of one metadata sidecar. Every field is required.

    Attributes:
        artifact_id: The artifact version this sidecar describes.
        stage: The stage that owns the artifact.
        created_by: The agent or person that produced it.
        created_at: When it was produced, in UTC.
        input_artifacts: The exact artifact versions it was built from. May
            be empty. An entry may not be the artifact itself or be repeated.
        content_hash: Hash of the artifact's content.
        state: Whether the artifact is still valid.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    artifact_id: ArtifactId
    stage: Stage
    created_by: Actor
    created_at: UtcTimestamp
    input_artifacts: tuple[ArtifactId, ...]
    content_hash: Sha256Hash
    state: ArtifactState

    @model_validator(mode="after")
    def _inputs_are_other_artifacts_listed_once(self) -> Self:
        # One problem per offending entry, on its own position.
        errors: list[InitErrorDetails] = []
        first_position: dict[str, int] = {}
        for position, entry in enumerate(self.input_artifacts):
            if entry == self.artifact_id:
                problem = PydanticCustomError(
                    "self_reference", "an artifact cannot be built from itself"
                )
            elif entry in first_position:
                problem = PydanticCustomError(
                    "duplicate_input",
                    "{entry} is already listed at position {first}",
                    {"entry": entry, "first": first_position[entry]},
                )
            else:
                first_position[entry] = position
                continue
            errors.append({"type": problem, "loc": ("input_artifacts", position), "input": entry})
        if errors:
            raise ValidationError.from_exception_data(type(self).__name__, errors)
        return self

    @classmethod
    def from_json(cls, text: str, source: str = "sidecar") -> Self:
        """Parse and validate the text of a sidecar file.

        Args:
            text: The JSON text.
            source: The file name to use in error messages.

        Raises:
            ContractValidationError: If the text is not a valid sidecar.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json(self) -> str:
        """Return the sidecar as JSON text."""
        return json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def load_artifact_metadata(path: Path) -> ArtifactMetadata:
    """Read and validate a sidecar file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            sidecar. The error names the path as it was given.
    """
    return ArtifactMetadata.validate_document(read_json(path), str(path))
