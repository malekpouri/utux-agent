"""Schema of a run manifest, `runs/<run_id>/manifest.json`.

The manifest records what is needed to repeat a run: the command and its
parameters, the code and container, the data, the seeds, the hardware, any
models and services the run called, and how the run ended (specification,
section 7, "Run manifest").
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictBool, StrictInt, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError

from utux.schemas.base import ContractDocument, ContractPart, field_problem, raise_field_problems
from utux.schemas.common import (
    FlatObject,
    NonEmptyText,
    PositiveInt,
    RelativePath,
    Sha256Hash,
    UtcTimestamp,
)
from utux.schemas.json_io import read_json

RunId = Annotated[str, Field(pattern=r"^r[0-9]{3,}$", strict=True)]
"""A run id: `r` and at least three digits, for example `r012`."""


class FileRef(ContractPart):
    """A file inside the project and the hash of its content."""

    path: RelativePath
    hash: Sha256Hash


class GitState(ContractPart):
    """The commit the run was started from, and whether the tree had other changes."""

    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$", strict=True)]
    dirty: StrictBool


class Container(ContractPart):
    """The container image by digest, and the locked version of each package."""

    image_digest: Sha256Hash
    locked_packages: dict[NonEmptyText, NonEmptyText]


class Dataset(ContractPart):
    """One dataset: its version, how it was obtained, and its input files."""

    name: NonEmptyText
    version: NonEmptyText
    obtained_from: NonEmptyText
    files: tuple[FileRef, ...]


class Hardware(ContractPart):
    """The machine. CUDA and driver versions are given exactly when a GPU was used."""

    cpu: NonEmptyText
    cpu_count: PositiveInt
    memory_mb: PositiveInt
    gpu: NonEmptyText | None
    cuda_version: NonEmptyText | None
    driver_version: NonEmptyText | None

    @model_validator(mode="after")
    def _gpu_versions_follow_gpu(self) -> Self:
        names = ("cuda_version", "driver_version")
        if self.gpu is None:
            problems = [
                field_problem("not_allowed_without_gpu", "must be null when no GPU is used", name)
                for name in names
                if getattr(self, name) is not None
            ]
        else:
            problems = [
                field_problem("required_with_gpu", "must not be null when a GPU is used", name)
                for name in names
                if getattr(self, name) is None
            ]
        raise_field_problems(type(self).__name__, problems)
        return self


class ModelUse(ContractPart):
    """A model the run called, with its inference settings."""

    model: NonEmptyText
    version: NonEmptyText | None
    settings: FlatObject


class ExternalService(ContractPart):
    """An external API or service the run depends on."""

    name: NonEmptyText
    version: NonEmptyText


class RunManifest(ContractDocument):
    """Everything recorded about one run. Every field is required.

    Attributes:
        run_id: Id of the run.
        command: The command as a list of arguments, not as one shell string.
        parameters: The experiment parameters, as a flat object.
        config_files: The configuration files, each with its hash.
        git: The commit and whether the working tree had uncommitted changes.
        container: The image digest and the locked package versions.
        datasets: The datasets, with version, origin and input file hashes.
        seeds: The random seeds by name.
        hardware: The machine the run used.
        models: The models the run called. Empty if it called none.
        external_services: The services the run depends on. Empty if none.
        started_at: When the run started.
        ended_at: When the run ended. Not before `started_at`.
        exit_status: The exit status of the command.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    run_id: RunId
    command: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    parameters: FlatObject
    config_files: tuple[FileRef, ...]
    git: GitState
    container: Container
    datasets: tuple[Dataset, ...]
    seeds: dict[NonEmptyText, StrictInt]
    hardware: Hardware
    models: tuple[ModelUse, ...]
    external_services: tuple[ExternalService, ...]
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    exit_status: StrictInt

    @field_validator("ended_at")
    @classmethod
    def _ends_after_it_starts(cls, value: str, info: ValidationInfo) -> str:
        started = info.data.get("started_at")
        # Compared as times: as text, a fraction of a second sorts before "Z".
        if started is not None and _as_time(value) < _as_time(started):
            raise PydanticCustomError(
                "ended_before_started",
                "the run cannot end ({ended}) before it starts ({started})",
                {"ended": value, "started": started},
            )
        return value


def _as_time(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.removesuffix("Z"))


def load_run_manifest(path: Path) -> RunManifest:
    """Read and validate a run manifest file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            manifest. The error names the path as it was given.
    """
    return RunManifest.validate_document(read_json(path), str(path))
