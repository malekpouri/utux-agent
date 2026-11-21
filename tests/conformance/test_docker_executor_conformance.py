"""M1-07: the Docker executor passes the `Executor` conformance suite.

Marked `docker`: it needs a Docker daemon and the local image
`python:3.12-slim-bookworm`. Run it with `uv run pytest -m docker`.
"""

import subprocess
from pathlib import Path

import pytest
from executor_suite import (
    SUCCESS_CONTENT,
    SUCCESS_FILE,
    SUCCESS_STDOUT,
    ExecutorConformance,
)

from utux.executors.docker import DockerExecutor
from utux.interfaces.executor import ExecutionStep, ResourceLimits

pytestmark = pytest.mark.docker

IMAGE = "python:3.12-slim-bookworm"
OUTPUT = "runs/r001/outputs"


def image_digest() -> str:
    """The local image id; the test fails, with what to do, if it is missing."""
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"the image {IMAGE} is not present locally; run: docker pull {IMAGE}")
    return result.stdout.strip()


def _step(script: str, timeout_seconds: float = 60.0) -> ExecutionStep:
    return ExecutionStep(
        run_id="r001",
        command=("python", "-c", script),
        image_digest=image_digest(),
        read_only_paths=(),
        output_directory=OUTPUT,
        limits=ResourceLimits(memory_mb=256, max_processes=64, cpus=1.0, disk_mb=64),
        timeout_seconds=timeout_seconds,
        environment={},
    )


class TestDockerExecutor(ExecutorConformance):
    def make_succeeding(self, project: Path) -> tuple[DockerExecutor, ExecutionStep]:
        script = (
            "import sys; "
            f"sys.stdout.buffer.write({SUCCESS_STDOUT!r}); "
            f"open({OUTPUT + '/' + SUCCESS_FILE!r}, 'wb').write({SUCCESS_CONTENT!r})"
        )
        return DockerExecutor(project), _step(script)

    def make_exiting(self, project: Path, status: int) -> tuple[DockerExecutor, ExecutionStep]:
        return DockerExecutor(project), _step(f"raise SystemExit({status})")

    def make_noisy(
        self, project: Path, cap_bytes: int, total_bytes: int
    ) -> tuple[DockerExecutor, ExecutionStep]:
        script = f"import sys; sys.stdout.buffer.write(b'S' + b'x' * {total_bytes - 2} + b'E')"
        return DockerExecutor(project, output_cap_bytes=cap_bytes), _step(script)

    def make_slow(self, project: Path) -> tuple[DockerExecutor, ExecutionStep]:
        return DockerExecutor(project), _step("import time; time.sleep(60)", timeout_seconds=2.0)

    def make_unavailable(self, project: Path) -> tuple[DockerExecutor, ExecutionStep]:
        step = ExecutionStep(
            run_id="r001",
            command=("python", "-c", "pass"),
            image_digest="sha256:" + "a" * 64,
            read_only_paths=(),
            output_directory=OUTPUT,
            limits=ResourceLimits(),
            timeout_seconds=10.0,
            environment={},
        )
        return DockerExecutor(
            project, docker_environment={"DOCKER_HOST": "unix:///nonexistent/utux.sock"}
        ), step
