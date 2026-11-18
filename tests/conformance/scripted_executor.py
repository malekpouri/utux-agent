"""A scripted `Executor` for tests.

It runs nothing. Each call to `run` plays the next step of its script: it
writes the scripted files into the step's output directory and returns the
scripted exit status and output, capped as a real executor caps them. It is
synthetic by construction and never executes code on the host.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from utux.errors import ExecutorUnavailableError
from utux.interfaces.executor import (
    DEFAULT_OUTPUT_CAP_BYTES,
    ExecutionStep,
    LimitKind,
    OutputCapture,
    RunResult,
)
from utux.workspace.outputs import collect_output_files


@dataclass(frozen=True)
class ScriptedRun:
    """One scripted run.

    Attributes:
        exit_status: The exit status to report, or None when a limit stopped
            the run.
        stdout: What the run writes to standard output.
        stderr: What the run writes to standard error.
        files: Files to write into the output directory, by relative path.
        stopped_by: The limit that stopped the run, if any.
        duration_seconds: How long the run takes on the executor's clock.
    """

    exit_status: int | None = 0
    stdout: bytes = b""
    stderr: bytes = b""
    files: dict[str, bytes] = field(default_factory=dict)
    stopped_by: LimitKind | None = None
    duration_seconds: float = 1.0


@dataclass(frozen=True)
class ScriptedUnavailable:
    """A step at which the backend is missing."""

    reason: str = "synthetic: the backend is not available"


ScriptedExecution = ScriptedRun | ScriptedUnavailable


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScriptedExecutor:
    """An `Executor` that plays back a script."""

    def __init__(
        self,
        project: Path,
        script: Sequence[ScriptedExecution],
        *,
        output_cap_bytes: int = DEFAULT_OUTPUT_CAP_BYTES,
        clock: Callable[[], datetime] = lambda: datetime(2026, 11, 18, 10, 0, tzinfo=UTC),
    ) -> None:
        self._project = project
        self._script = list(script)
        self._cap = output_cap_bytes
        self._clock = clock
        self.steps: list[ExecutionStep] = []

    @property
    def name(self) -> str:
        """The executor's name."""
        return "scripted"

    def run(self, step: ExecutionStep) -> RunResult:
        """Play the next scripted run for this step."""
        if not self._script:
            raise AssertionError("the scripted executor has no step left")
        scripted = self._script.pop(0)
        if isinstance(scripted, ScriptedUnavailable):
            raise ExecutorUnavailableError(scripted.reason)
        self.steps.append(step)
        started = self._clock()
        output = self._project / step.output_directory
        output.mkdir(parents=True, exist_ok=True)
        for relative, content in scripted.files.items():
            (output / relative).parent.mkdir(parents=True, exist_ok=True)
            (output / relative).write_bytes(content)
        captures = []
        for data in (scripted.stdout, scripted.stderr):
            capture = OutputCapture(cap_bytes=self._cap)
            capture.feed(data)
            captures.append(capture.result())
        return RunResult(
            run_id=step.run_id,
            exit_status=scripted.exit_status,
            started_at=_timestamp(started),
            ended_at=_timestamp(started + timedelta(seconds=scripted.duration_seconds)),
            stdout=captures[0],
            stderr=captures[1],
            output_files=collect_output_files(output),
            stopped_by=scripted.stopped_by,
        )
