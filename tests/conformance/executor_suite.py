"""Conformance suite for `Executor` (ADR-0004: internal, with a typed contract).

Every implementation must pass this suite. To run it against an executor,
subclass `ExecutorConformance` in a test module, name the subclass `Test...`,
and implement the `make_...` methods. Each returns an executor working on
the given project directory and a step for it that behaves as described.
"""

import hashlib
import inspect
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import pytest

from utux.errors import ExecutorUnavailableError, UtuxError
from utux.interfaces.executor import ExecutionStep, Executor, LimitKind, RunResult

# What a succeeding step writes, as every implementation must reproduce it.
SUCCESS_STDOUT = b"synthetic output\n"
SUCCESS_FILE = "result.txt"
SUCCESS_CONTENT = b"synthetic result\n"


def noisy_stream(total_bytes: int) -> bytes:
    """What a noisy step writes: `S`, then `x`, then `E`; both ends are visible."""
    return b"S" + b"x" * (total_bytes - 2) + b"E"


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def assert_well_formed(result: object, step: ExecutionStep, project: Path) -> None:
    """Check everything the contract promises about a result."""
    assert isinstance(result, RunResult)
    assert result.run_id == step.run_id
    assert _time(result.started_at) <= _time(result.ended_at)
    output = project / step.output_directory
    for file in result.output_files:
        # Every listed file is in the output directory and has the listed hash.
        path = output / file.path
        assert path.is_file()
        content = path.read_bytes()
        assert file.content_hash == "sha256:" + hashlib.sha256(content).hexdigest()
        assert file.size_bytes == len(content)
    if result.exit_status is None:
        assert result.stopped_by is not None


class ExecutorConformance(ABC):
    """Tests that every `Executor` implementation must pass."""

    @abstractmethod
    def make_succeeding(self, project: Path) -> tuple[Executor, ExecutionStep]:
        """A step that exits 0, writes `SUCCESS_STDOUT` to standard output and
        `SUCCESS_CONTENT` to `SUCCESS_FILE` in its output directory."""

    @abstractmethod
    def make_exiting(self, project: Path, status: int) -> tuple[Executor, ExecutionStep]:
        """A step that exits with `status` and writes nothing."""

    @abstractmethod
    def make_noisy(
        self, project: Path, cap_bytes: int, total_bytes: int
    ) -> tuple[Executor, ExecutionStep]:
        """An executor that keeps at most `cap_bytes` of each output stream, and
        a step that writes `noisy_stream(total_bytes)` to standard output."""

    @abstractmethod
    def make_slow(self, project: Path) -> tuple[Executor, ExecutionStep]:
        """A step that runs longer than its wall-clock timeout."""

    @abstractmethod
    def make_unavailable(self, project: Path) -> tuple[Executor, ExecutionStep]:
        """An executor whose backend is missing, for example no Docker daemon."""

    # Shape of the interface

    def test_is_an_executor(self, tmp_path: Path) -> None:
        executor, _ = self.make_succeeding(tmp_path)
        assert isinstance(executor, Executor)

    def test_run_takes_the_step_and_nothing_else(self, tmp_path: Path) -> None:
        executor, _ = self.make_succeeding(tmp_path)
        assert list(inspect.signature(executor.run).parameters) == ["step"]

    def test_name_is_non_empty_text(self, tmp_path: Path) -> None:
        executor, _ = self.make_succeeding(tmp_path)
        assert isinstance(executor.name, str)
        assert executor.name.strip()

    # Results

    def test_a_successful_run_reports_its_output_and_files(self, tmp_path: Path) -> None:
        executor, step = self.make_succeeding(tmp_path)
        result = executor.run(step)
        assert_well_formed(result, step, tmp_path)
        assert result.exit_status == 0
        assert result.stopped_by is None
        assert result.stdout.content == SUCCESS_STDOUT
        assert result.stdout.truncated is False
        assert [(f.path, f.content_hash) for f in result.output_files] == [
            (SUCCESS_FILE, "sha256:" + hashlib.sha256(SUCCESS_CONTENT).hexdigest())
        ]

    @pytest.mark.parametrize("status", [1, 3, 137])
    def test_a_non_zero_exit_is_reported_not_raised(self, tmp_path: Path, status: int) -> None:
        executor, step = self.make_exiting(tmp_path, status)
        result = executor.run(step)
        assert_well_formed(result, step, tmp_path)
        assert result.exit_status == status
        assert result.stopped_by is None

    def test_output_beyond_the_cap_is_cut_and_the_cut_is_reported(self, tmp_path: Path) -> None:
        executor, step = self.make_noisy(tmp_path, cap_bytes=64, total_bytes=1000)
        result = executor.run(step)
        assert_well_formed(result, step, tmp_path)
        stream = noisy_stream(1000)
        # Half of the cap from the start, half from the end, and a marker.
        assert result.stdout.content == stream[:32] + omission_marker(936) + stream[-32:]
        assert result.stdout.cap_bytes == 64
        assert result.stdout.total_bytes == 1000
        assert result.stdout.omitted_bytes == 936
        assert result.stdout.truncated is True

    def test_the_wall_clock_timeout_stops_the_run_and_is_reported(self, tmp_path: Path) -> None:
        executor, step = self.make_slow(tmp_path)
        result = executor.run(step)
        assert_well_formed(result, step, tmp_path)
        assert result.stopped_by is LimitKind.WALL_CLOCK

    def test_a_missing_backend_is_a_typed_error_and_nothing_runs(self, tmp_path: Path) -> None:
        executor, step = self.make_unavailable(tmp_path)
        with pytest.raises(ExecutorUnavailableError) as caught:
            executor.run(step)
        assert isinstance(caught.value, UtuxError)
        output = tmp_path / step.output_directory
        assert not output.exists() or not any(output.iterdir())
