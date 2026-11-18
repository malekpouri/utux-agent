"""The `Executor` interface: one run of a command in a sandbox.

`Executor` is internal in v1 (ADR-0004), with the same typed contract and
conformance suite as the public interfaces. The core gives an executor an
`ExecutionStep` and gets a `RunResult` back; it never runs model-written
code itself. The hardened Docker executor is task M1-07.

A step names a command as a list of arguments, never a shell string, and the
exact environment variables the command sees. Names that look like
credentials are refused, so that no key can be handed to model-written code.
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.schemas.common import RelativePath, RunId, Sha256Hash, UtcTimestamp

DEFAULT_OUTPUT_CAP_BYTES = 1024 * 1024
"""How much of each output stream an executor keeps unless told otherwise."""

_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CREDENTIAL_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


class _Value(BaseModel):
    """Base of the contract's types: no unknown fields, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceLimits(_Value):
    """Limits of one run. A limit that is not set is left to the executor.

    Attributes:
        cpus: Number of CPUs, may be fractional.
        memory_mb: Memory in megabytes.
        gpus: Number of GPUs passed through.
        disk_mb: Size of the writable scratch space in megabytes.
        max_processes: Number of processes and threads.
    """

    cpus: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    memory_mb: Annotated[int, Field(gt=0, strict=True)] | None = None
    gpus: Annotated[int, Field(ge=0, strict=True)] | None = None
    disk_mb: Annotated[int, Field(gt=0, strict=True)] | None = None
    max_processes: Annotated[int, Field(gt=0, strict=True)] | None = None


def _overlaps(first: str, second: str) -> bool:
    """Whether one relative path is the other or lies inside it."""
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


class ExecutionStep(_Value):
    """What an executor is asked to run.

    Attributes:
        run_id: The run this step belongs to.
        command: The command and its arguments. Not a shell string.
        image_digest: The container image, by digest.
        read_only_paths: Project paths the command may read.
        output_directory: The project path the command may write; the only
            writable place. It may not overlap a read-only path.
        limits: Resource limits.
        timeout_seconds: Wall-clock limit. The run is stopped when it is
            reached, and the result says so.
        environment: The only environment variables the command sees. A
            name that contains `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, in
            any case, is refused.
    """

    run_id: RunId
    command: Annotated[
        tuple[Annotated[str, Field(min_length=1, strict=True)], ...], Field(min_length=1)
    ]
    image_digest: Sha256Hash
    read_only_paths: tuple[RelativePath, ...]
    output_directory: RelativePath
    limits: ResourceLimits
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    environment: dict[str, Annotated[str, Field(strict=True)]]

    @field_validator("environment")
    @classmethod
    def _plain_names_that_are_no_credentials(cls, value: dict[str, str]) -> dict[str, str]:
        errors: list[InitErrorDetails] = []
        for name in value:
            if _ENVIRONMENT_NAME.fullmatch(name) is None:
                problem = PydanticCustomError(
                    "invalid_environment_name",
                    "must be a name of letters, digits and _, not starting with a digit",
                )
            elif any(part in name.upper() for part in _CREDENTIAL_PARTS):
                # The value is never repeated, so a key cannot leak through the error.
                problem = PydanticCustomError(
                    "credential_like_name",
                    "looks like a credential (KEY, TOKEN, SECRET or PASSWORD); credentials "
                    "are never passed to a run",
                )
            else:
                continue
            errors.append({"type": problem, "loc": (name,), "input": name})
        if errors:
            raise ValidationError.from_exception_data(cls.__name__, errors)
        return value

    @model_validator(mode="after")
    def _output_apart_from_inputs(self) -> Self:
        if any(_overlaps(self.output_directory, path) for path in self.read_only_paths):
            raise ValidationError.from_exception_data(
                type(self).__name__,
                [
                    {
                        "type": PydanticCustomError(
                            "overlaps_read_only_path",
                            "the output directory may not be, contain or lie inside a "
                            "read-only path",
                        ),
                        "loc": ("output_directory",),
                        "input": self.output_directory,
                    }
                ],
            )
        return self


class LimitKind(StrEnum):
    """The limit that stopped a run."""

    WALL_CLOCK = "wall_clock"
    MEMORY = "memory"
    PROCESSES = "processes"
    DISK = "disk"


class CapturedOutput(_Value):
    """One output stream of a run, kept up to a cap.

    Attributes:
        content: The first `cap_bytes` bytes of the stream, or all of it.
        total_bytes: How many bytes the stream had in all.
        cap_bytes: The cap that applied.
        truncated: Whether bytes were cut. True exactly when `total_bytes`
            exceeds the length of `content`, so that a cut is never silent.
    """

    content: bytes
    total_bytes: Annotated[int, Field(ge=0, strict=True)]
    cap_bytes: Annotated[int, Field(gt=0, strict=True)]
    truncated: bool

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        kept = len(self.content)
        if kept > self.cap_bytes:
            raise ValueError("content is longer than the cap")
        if self.total_bytes < kept:
            raise ValueError("total_bytes is less than the content kept")
        if self.truncated != (self.total_bytes > kept):
            raise ValueError("truncated must say whether bytes were cut")
        return self


class OutputCapture:
    """Collects one output stream, keeping at most `cap_bytes` of it.

    Executors feed it chunks as they arrive. It counts every byte, so the
    result reports how much was cut.
    """

    def __init__(self, cap_bytes: int = DEFAULT_OUTPUT_CAP_BYTES) -> None:
        if cap_bytes <= 0:
            raise ValueError("the cap must be positive")
        self._cap = cap_bytes
        self._kept = bytearray()
        self._total = 0

    def feed(self, chunk: bytes) -> None:
        """Add a chunk of the stream."""
        self._total += len(chunk)
        room = self._cap - len(self._kept)
        if room > 0:
            self._kept += chunk[:room]

    def result(self) -> CapturedOutput:
        """Return what was kept and how much there was."""
        return CapturedOutput(
            content=bytes(self._kept),
            total_bytes=self._total,
            cap_bytes=self._cap,
            truncated=self._total > len(self._kept),
        )


class OutputFile(_Value):
    """A file a run wrote.

    Attributes:
        path: The path relative to the step's output directory.
        content_hash: The hash of its content.
        size_bytes: Its size.
    """

    path: RelativePath
    content_hash: Sha256Hash
    size_bytes: Annotated[int, Field(ge=0, strict=True)]


def _moment(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class RunResult(_Value):
    """How a run ended.

    Attributes:
        run_id: The run id of the step.
        exit_status: The command's exit status, or None when a limit stopped
            the run before it exited.
        started_at: When the run started, in UTC.
        ended_at: When it ended, in UTC; not before `started_at`.
        stdout: Standard output, capped.
        stderr: Standard error, capped.
        output_files: The files in the output directory after the run, each
            once.
        stopped_by: The limit that stopped the run, or None.

    A non-zero exit status is a result, not an error: the executor reports it
    and raises nothing.
    """

    run_id: RunId
    exit_status: Annotated[int, Field(strict=True)] | None
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    stdout: CapturedOutput
    stderr: CapturedOutput
    output_files: tuple[OutputFile, ...]
    stopped_by: LimitKind | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        errors: list[InitErrorDetails] = []
        if self.exit_status is None and self.stopped_by is None:
            errors.append(
                {
                    "type": PydanticCustomError(
                        "exit_status_required",
                        "a run that was not stopped by a limit has an exit status",
                    ),
                    "loc": ("exit_status",),
                    "input": None,
                }
            )
        if _moment(self.ended_at) < _moment(self.started_at):
            errors.append(
                {
                    "type": PydanticCustomError("ends_before_start", "ends before it starts"),
                    "loc": ("ended_at",),
                    "input": self.ended_at,
                }
            )
        seen: set[str] = set()
        for position, file in enumerate(self.output_files):
            if file.path in seen:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "duplicate_output_file", "{path} is listed twice", {"path": file.path}
                        ),
                        "loc": ("output_files", position),
                        "input": file.path,
                    }
                )
            seen.add(file.path)
        if errors:
            raise ValidationError.from_exception_data(type(self).__name__, errors)
        return self


@runtime_checkable
class Executor(Protocol):
    """Runs one step in a sandbox and reports how it ended.

    `run` raises `ExecutorUnavailableError` when the sandbox cannot be used
    at all, for example when Docker is missing; it never falls back to
    running on the host. Anything the command itself does, including a
    non-zero exit or hitting a limit, is reported in the `RunResult`.
    """

    @property
    def name(self) -> str:
        """A short name of the executor, for logs and manifests."""
        ...

    def run(self, step: ExecutionStep) -> RunResult:
        """Run the step and return its result."""
        ...
