"""M1-06: the types of the `Executor` contract.

A step names what to run and with what limits; a result says how the run
ended. Both refuse what the contract does not allow. The values here are
synthetic.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from utux.interfaces.executor import (
    CapturedOutput,
    ExecutionStep,
    LimitKind,
    OutputCapture,
    OutputFile,
    ResourceLimits,
    RunResult,
)

DIGEST = "sha256:" + "a" * 64
HASH = "sha256:" + "b" * 64


def _step(**changes: Any) -> ExecutionStep:
    fields: dict[str, Any] = {
        "run_id": "r012",
        "command": ("python", "train.py"),
        "image_digest": DIGEST,
        "read_only_paths": ("code", "inputs/data.csv"),
        "output_directory": "runs/r012/outputs",
        "limits": ResourceLimits(cpus=2.0, memory_mb=2048, max_processes=64, disk_mb=512),
        "timeout_seconds": 600.0,
        "environment": {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "2"},
    }
    return ExecutionStep(**{**fields, **changes})


def _codes(error: ValidationError) -> list[tuple[str, str]]:
    return [(".".join(str(part) for part in e["loc"]), e["type"]) for e in error.errors()]


# The step


def test_a_step_holds_what_the_plan_lists() -> None:
    step = _step()
    assert step.command == ("python", "train.py")
    assert step.read_only_paths == ("code", "inputs/data.csv")
    assert step.limits.memory_mb == 2048
    assert step.environment["OMP_NUM_THREADS"] == "2"


@pytest.mark.parametrize(
    "name",
    [
        "OPENROUTER_API_KEY",
        "api_key",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "DB_PASSWORD",
        "my_Secret",
        "KEYRING",
    ],
)
def test_environment_names_that_look_like_credentials_are_refused(name: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _step(environment={name: "synthetic-value-never-shown"})
    assert _codes(caught.value) == [(f"environment.{name}", "credential_like_name")]
    # The value is not repeated in the error.
    assert "synthetic-value-never-shown" not in str(caught.value)


@pytest.mark.parametrize("name", ["", "1ABC", "A-B", "A B", "A=B"])
def test_environment_names_must_be_plain_names(name: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _step(environment={name: "x"})
    assert _codes(caught.value) == [(f"environment.{name}", "invalid_environment_name")]


def test_an_empty_command_is_refused() -> None:
    with pytest.raises(ValidationError) as caught:
        _step(command=())
    assert _codes(caught.value) == [("command", "too_short")]


def test_an_empty_argument_is_refused() -> None:
    with pytest.raises(ValidationError):
        _step(command=("python", ""))


@pytest.mark.parametrize("path", ["/etc", "../outside", "runs/../.."])
def test_paths_stay_inside_the_project(path: str) -> None:
    with pytest.raises(ValidationError):
        _step(read_only_paths=(path,))
    with pytest.raises(ValidationError):
        _step(output_directory=path)


@pytest.mark.parametrize("mounted", ["runs", "runs/r012/outputs", "runs/r012/outputs/sub"])
def test_the_output_directory_may_not_overlap_a_read_only_path(mounted: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _step(read_only_paths=(mounted,))
    assert _codes(caught.value) == [("output_directory", "overlaps_read_only_path")]


def test_a_sibling_with_a_common_prefix_does_not_overlap() -> None:
    assert _step(read_only_paths=("runs/r012/outputs-old",)).output_directory


def test_the_image_is_named_by_digest() -> None:
    with pytest.raises(ValidationError):
        _step(image_digest="python:3.12")


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf")])
def test_the_timeout_is_a_positive_finite_number(timeout: float) -> None:
    with pytest.raises(ValidationError):
        _step(timeout_seconds=timeout)


def test_a_step_is_immutable() -> None:
    step = _step()
    with pytest.raises(ValidationError):
        step.run_id = "r013"  # type: ignore[misc]


# Captured output


def test_output_within_the_cap_is_kept_whole() -> None:
    capture = OutputCapture(cap_bytes=10)
    capture.feed(b"abc")
    capture.feed(b"def")
    assert capture.result() == CapturedOutput(
        content=b"abcdef", total_bytes=6, cap_bytes=10, truncated=False
    )


def test_output_beyond_the_cap_is_cut_and_the_cut_is_reported() -> None:
    capture = OutputCapture(cap_bytes=4)
    for chunk in (b"ab", b"cdef", b"gh"):
        capture.feed(chunk)
    result = capture.result()
    assert result.content == b"abcd"
    assert result.total_bytes == 8
    assert result.cap_bytes == 4
    assert result.truncated is True


def test_output_of_exactly_the_cap_is_not_truncated() -> None:
    capture = OutputCapture(cap_bytes=4)
    capture.feed(b"abcd")
    assert capture.result().truncated is False


@pytest.mark.parametrize(
    "fields",
    [
        {"content": b"abcde", "total_bytes": 5, "cap_bytes": 4, "truncated": True},
        {"content": b"abc", "total_bytes": 5, "cap_bytes": 4, "truncated": False},
        {"content": b"abcd", "total_bytes": 4, "cap_bytes": 4, "truncated": True},
        {"content": b"abc", "total_bytes": 2, "cap_bytes": 4, "truncated": False},
    ],
)
def test_captured_output_that_contradicts_itself_is_refused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CapturedOutput(**fields)


# The result


def _result(**changes: Any) -> RunResult:
    empty = CapturedOutput(content=b"", total_bytes=0, cap_bytes=1024, truncated=False)
    fields: dict[str, Any] = {
        "run_id": "r012",
        "exit_status": 0,
        "started_at": "2026-11-18T10:00:00Z",
        "ended_at": "2026-11-18T10:00:05Z",
        "stdout": empty,
        "stderr": empty,
        "output_files": (OutputFile(path="metrics.json", content_hash=HASH, size_bytes=12),),
        "stopped_by": None,
    }
    return RunResult(**{**fields, **changes})


def test_a_result_holds_what_the_plan_lists() -> None:
    result = _result()
    assert result.exit_status == 0
    assert result.output_files[0].path == "metrics.json"
    assert result.stopped_by is None


def test_a_run_stopped_by_a_limit_names_it_and_may_have_no_exit_status() -> None:
    result = _result(exit_status=None, stopped_by=LimitKind.WALL_CLOCK)
    assert result.stopped_by is LimitKind.WALL_CLOCK


def test_the_limits_are_the_four_kinds() -> None:
    assert [kind.value for kind in LimitKind] == ["wall_clock", "memory", "processes", "disk"]


def test_a_run_without_an_exit_status_must_name_the_limit() -> None:
    with pytest.raises(ValidationError) as caught:
        _result(exit_status=None)
    assert _codes(caught.value) == [("exit_status", "exit_status_required")]


def test_a_run_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValidationError) as caught:
        _result(ended_at="2026-11-18T09:59:59Z")
    assert _codes(caught.value) == [("ended_at", "ends_before_start")]


def test_output_files_are_listed_once() -> None:
    file = OutputFile(path="a.txt", content_hash=HASH, size_bytes=1)
    with pytest.raises(ValidationError) as caught:
        _result(output_files=(file, file))
    assert _codes(caught.value) == [("output_files.1", "duplicate_output_file")]


def test_output_file_paths_are_relative_to_the_output_directory() -> None:
    with pytest.raises(ValidationError):
        OutputFile(path="../escape.txt", content_hash=HASH, size_bytes=1)
