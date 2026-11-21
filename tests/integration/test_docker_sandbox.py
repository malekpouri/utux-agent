"""M1-07: what the sandbox prevents, shown inside a real container.

Marked `docker`: these tests need a Docker daemon and the local image
`python:3.12-slim-bookworm`, and run only with `uv run pytest -m docker`.
Every program run here is written in this file; none comes from a model.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from utux.errors import ExecutorError, ExecutorUnavailableError
from utux.executors.docker import DockerExecutor
from utux.interfaces.executor import ExecutionStep, LimitKind, ResourceLimits, RunResult

pytestmark = pytest.mark.docker

IMAGE = "python:3.12-slim-bookworm"
OUTPUT = "runs/r001/outputs"


@pytest.fixture(scope="module")
def digest() -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"the image {IMAGE} is not present locally; run: docker pull {IMAGE}")
    return result.stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "code").mkdir(parents=True)
    (project / "code" / "train.py").write_text("print('synthetic')\n", encoding="utf-8")
    (project / "inputs").mkdir()
    (project / "inputs" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    # A project file that is not mounted.
    (project / "secret.txt").write_text("synthetic, not to be read\n", encoding="utf-8")
    return project


def _run(
    project: Path,
    digest: str,
    script: str,
    *,
    limits: ResourceLimits | None = None,
    timeout_seconds: float = 60.0,
    environment: dict[str, str] | None = None,
) -> RunResult:
    step = ExecutionStep(
        run_id="r001",
        command=("python", "-c", script),
        image_digest=digest,
        read_only_paths=("code", "inputs"),
        output_directory=OUTPUT,
        limits=limits or ResourceLimits(memory_mb=256, max_processes=64, cpus=1.0, disk_mb=64),
        timeout_seconds=timeout_seconds,
        environment=environment or {},
    )
    return DockerExecutor(project).run(step)


def _report(result: RunResult) -> dict[str, object]:
    assert result.exit_status == 0, result.stderr.content.decode(errors="replace")
    data = json.loads(result.stdout.content)
    assert isinstance(data, dict)
    return data


# Each probe tries one thing and prints whether it worked, so a failure of the
# sandbox shows as a wrong value rather than a crash.
PROBE = """
import json, sys
def attempt(action):
    try:
        action()
        return "allowed"
    except OSError as error:
        return type(error).__name__
"""


def test_writing_outside_the_output_directory_fails(project: Path, digest: str) -> None:
    script = (
        PROBE
        + f"""
targets = ["/project/code/new.py", "/project/inputs/new.csv", "/etc/utux", "/utux", "/project/new"]
result = {{t: attempt(lambda t=t: open(t, "w").write("x")) for t in targets}}
result["output"] = attempt(lambda: open("{OUTPUT}/ok.txt", "w").write("x"))
result["tmp"] = attempt(lambda: open("/tmp/ok.txt", "w").write("x"))
print(json.dumps(result))
"""
    )
    report = _report(_run(project, digest, script))
    assert report.pop("output") == "allowed"
    assert report.pop("tmp") == "allowed"
    assert all(outcome != "allowed" for outcome in report.values()), report
    assert not (project / "code" / "new.py").exists()


def test_opening_a_network_connection_fails(project: Path, digest: str) -> None:
    script = (
        PROBE
        + """
import socket
def connect(host, port):
    with socket.create_connection((host, port), timeout=3):
        pass
result = {
    "ip": attempt(lambda: connect("1.1.1.1", 53)),
    "dns": attempt(lambda: socket.getaddrinfo("example.org", 443)),
}
print(json.dumps(result))
"""
    )
    report = _report(_run(project, digest, script))
    assert report["ip"] != "allowed"
    assert report["dns"] != "allowed"


def test_reading_a_host_path_that_was_not_mounted_fails(project: Path, digest: str) -> None:
    home = str(Path.home())
    script = (
        PROBE
        + f"""
import os
result = {{
    "project_file": attempt(lambda: open("/project/secret.txt").read()),
    "home": attempt(lambda: os.listdir({home!r})),
    "docker_socket": attempt(lambda: open("/var/run/docker.sock", "rb")),
    "mounted_input": attempt(lambda: open("/project/inputs/data.csv").read()),
}}
print(json.dumps(result))
"""
    )
    report = _report(_run(project, digest, script))
    assert report.pop("mounted_input") == "allowed"
    assert all(outcome != "allowed" for outcome in report.values()), report


def test_a_fork_bomb_is_contained_and_ends_within_its_timeout(project: Path, digest: str) -> None:
    script = """
import os, time
children = 0
while True:
    try:
        if os.fork() == 0:
            while True:
                time.sleep(1)
        children += 1
    except OSError:
        time.sleep(0.1)
"""
    started = time.monotonic()
    result = _run(
        project,
        digest,
        script,
        limits=ResourceLimits(memory_mb=256, max_processes=32, cpus=1.0, disk_mb=64),
        timeout_seconds=10.0,
    )
    elapsed = time.monotonic() - started
    # Contained: the run ends, by its timeout at the latest, with a small
    # margin for stopping the container. Which limit is named is not asserted.
    assert elapsed < 10.0 + 30.0
    assert result.stopped_by is LimitKind.WALL_CLOCK or result.exit_status is not None


def test_memory_beyond_the_limit_ends_the_run(project: Path, digest: str) -> None:
    script = "blocks = []\nwhile True:\n    blocks.append(bytearray(16 * 1024 * 1024))\n"
    started = time.monotonic()
    result = _run(
        project,
        digest,
        script,
        limits=ResourceLimits(memory_mb=64, max_processes=32, cpus=1.0, disk_mb=64),
        timeout_seconds=60.0,
    )
    # What utux promises: the run is killed (137), within its timeout, and it
    # names memory only when Docker reports it. Some Docker setups do not
    # report the kill; the run then names no limit, and never another one.
    assert time.monotonic() - started < 60.0
    assert result.exit_status == 137
    assert result.stopped_by in (LimitKind.MEMORY, None)


def test_no_host_variable_reaches_the_container(
    project: Path, digest: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UTUX_SYNTHETIC_HOST_VARIABLE", "host-only")
    script = "import json, os; print(json.dumps(dict(os.environ)))"
    report = _report(_run(project, digest, script, environment={"UTUX_STEP_VARIABLE": "given"}))
    assert report["UTUX_STEP_VARIABLE"] == "given"
    assert "UTUX_SYNTHETIC_HOST_VARIABLE" not in report
    # Every variable comes from the image, from Docker itself, or from the step.
    image = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .Config.Env}}", digest],
        capture_output=True,
        text=True,
        check=True,
    )
    from_image = {entry.split("=", 1)[0] for entry in json.loads(image.stdout)}
    assert set(report) <= from_image | {"HOSTNAME", "HOME", "UTUX_STEP_VARIABLE"}


def test_the_container_runs_as_the_host_user_not_root(project: Path, digest: str) -> None:
    script = "import json, os; print(json.dumps({'uid': os.getuid(), 'gid': os.getgid()}))"
    report = _report(_run(project, digest, script))
    assert report["uid"] == os.getuid() != 0
    assert report["gid"] == os.getgid()


def test_an_image_that_is_not_present_is_refused_without_pulling(project: Path) -> None:
    step = ExecutionStep(
        run_id="r001",
        command=("python", "-c", "pass"),
        image_digest="sha256:" + "0" * 64,
        read_only_paths=(),
        output_directory=OUTPUT,
        limits=ResourceLimits(),
        timeout_seconds=10.0,
        environment={},
    )
    with pytest.raises(ExecutorError, match="not present"):
        DockerExecutor(project).run(step)


def test_an_unreachable_daemon_is_a_clear_error(project: Path, digest: str) -> None:
    executor = DockerExecutor(
        project, docker_environment={"DOCKER_HOST": "unix:///nonexistent/utux.sock"}
    )
    step = ExecutionStep(
        run_id="r001",
        command=("python", "-c", "pass"),
        image_digest=digest,
        read_only_paths=(),
        output_directory=OUTPUT,
        limits=ResourceLimits(),
        timeout_seconds=10.0,
        environment={},
    )
    with pytest.raises(ExecutorUnavailableError, match="daemon"):
        executor.run(step)
    assert not (project / OUTPUT).exists()


def test_rootless_mode_is_detected_as_docker_reports_it(project: Path) -> None:
    info = subprocess.run(
        ["docker", "info", "--format", "{{json .SecurityOptions}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = any("name=rootless" in option for option in json.loads(info.stdout))
    assert DockerExecutor(project).rootless() is expected


def test_writing_past_the_output_limit_stops_the_run(project: Path, digest: str) -> None:
    # 1 MiB every 0.1 s against a 4 MB limit, for at most 60 s.
    script = f"""
import time
with open("{OUTPUT}/big.bin", "wb") as stream:
    for _ in range(600):
        stream.write(b"x" * (1024 * 1024))
        stream.flush()
        time.sleep(0.1)
"""
    started = time.monotonic()
    result = _run(
        project,
        digest,
        script,
        limits=ResourceLimits(memory_mb=256, max_processes=32, cpus=1.0, disk_mb=64, output_mb=4),
        timeout_seconds=60.0,
    )
    assert result.stopped_by is LimitKind.OUTPUT_SIZE
    assert result.exit_status is None
    # Stopped by the measurement, long before the 60 s the script would take.
    assert time.monotonic() - started < 30.0
    # Checked about once a second, so the run may write past the limit by
    # what it writes within one interval, not much more.
    written = (project / OUTPUT / "big.bin").stat().st_size
    assert 4 * 1024 * 1024 < written < 40 * 1024 * 1024


def test_attached_docker_run_delivers_output_without_a_log_driver(digest: str) -> None:
    """The finding behind --log-driver=none: an attached `docker run` still
    streams both standard output and standard error."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--log-driver=none",
            "--network=none",
            digest,
            "python",
            "-c",
            "import sys; print('to stdout'); print('to stderr', file=sys.stderr)",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "to stdout\n"
    assert "to stderr" in result.stderr


def test_docker_keeps_no_copy_of_the_output(project: Path, digest: str) -> None:
    step = ExecutionStep(
        run_id="r001",
        command=("python", "-c", "import time; print('synthetic', flush=True); time.sleep(30)"),
        image_digest=digest,
        read_only_paths=(),
        output_directory=OUTPUT,
        limits=ResourceLimits(),
        timeout_seconds=8.0,
        environment={},
    )
    results: list[RunResult] = []
    worker = threading.Thread(target=lambda: results.append(DockerExecutor(project).run(step)))
    worker.start()
    log_driver = ""
    deadline = time.monotonic() + 6.0
    while not log_driver and time.monotonic() < deadline:
        names = subprocess.run(
            ["docker", "ps", "--filter", "name=utux-r001-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        if names:
            log_driver = subprocess.run(
                ["docker", "inspect", "--format", "{{.HostConfig.LogConfig.Type}}", names[0]],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        time.sleep(0.2)
    worker.join()
    # Docker stores no copy of the output, yet the executor still received it.
    assert log_driver == "none"
    assert results[0].stdout.content == b"synthetic\n"


def test_no_container_is_left_behind(project: Path, digest: str) -> None:
    _run(project, digest, "print('synthetic')")
    listing = subprocess.run(
        ["docker", "ps", "--all", "--filter", "name=utux-r001-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert listing.stdout.strip() == ""
