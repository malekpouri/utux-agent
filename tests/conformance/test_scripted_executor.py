"""M1-06: the scripted executor passes the `Executor` conformance suite."""

from pathlib import Path

from executor_suite import (
    SUCCESS_CONTENT,
    SUCCESS_FILE,
    SUCCESS_STDOUT,
    ExecutorConformance,
    noisy_stream,
)

from utux.executors.scripted import ScriptedExecutor, ScriptedRun, ScriptedUnavailable
from utux.interfaces.executor import ExecutionStep, LimitKind, ResourceLimits


def _step(timeout_seconds: float = 60.0) -> ExecutionStep:
    return ExecutionStep(
        run_id="r001",
        command=("python", "synthetic.py"),
        image_digest="sha256:" + "a" * 64,
        read_only_paths=("code",),
        output_directory="runs/r001/outputs",
        limits=ResourceLimits(),
        timeout_seconds=timeout_seconds,
        environment={},
    )


class TestScriptedExecutor(ExecutorConformance):
    def make_succeeding(self, project: Path) -> tuple[ScriptedExecutor, ExecutionStep]:
        run = ScriptedRun(stdout=SUCCESS_STDOUT, files={SUCCESS_FILE: SUCCESS_CONTENT})
        return ScriptedExecutor(project, [run]), _step()

    def make_exiting(self, project: Path, status: int) -> tuple[ScriptedExecutor, ExecutionStep]:
        return ScriptedExecutor(project, [ScriptedRun(exit_status=status)]), _step()

    def make_noisy(
        self, project: Path, cap_bytes: int, total_bytes: int
    ) -> tuple[ScriptedExecutor, ExecutionStep]:
        run = ScriptedRun(stdout=noisy_stream(total_bytes))
        return ScriptedExecutor(project, [run], output_cap_bytes=cap_bytes), _step()

    def make_slow(self, project: Path) -> tuple[ScriptedExecutor, ExecutionStep]:
        run = ScriptedRun(exit_status=None, stopped_by=LimitKind.WALL_CLOCK, duration_seconds=2.0)
        return ScriptedExecutor(project, [run]), _step(timeout_seconds=1.0)

    def make_unavailable(self, project: Path) -> tuple[ScriptedExecutor, ExecutionStep]:
        return ScriptedExecutor(project, [ScriptedUnavailable()]), _step()


def test_the_scripted_executor_records_the_steps_it_was_given(tmp_path: Path) -> None:
    executor = ScriptedExecutor(tmp_path, [ScriptedRun()])
    step = _step()
    executor.run(step)
    assert executor.steps == [step]
