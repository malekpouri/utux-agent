"""M1-07: the arguments and checks of the Docker executor, without Docker.

The exact `docker run` arguments are asserted here, so that every hardening
flag of the specification, section 10, is enforced in code. The behaviour
inside a real sandbox is tested in tests/integration/test_docker_sandbox.py,
marked `docker`.
"""

import os
import socket
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ExecutorError, ExecutorUnavailableError
from utux.executors.docker import (
    CONTAINER_PROJECT,
    DEFAULT_LIMITS,
    DockerExecutor,
    directory_size,
    docker_run_arguments,
)
from utux.interfaces.executor import ExecutionStep, ResourceLimits

DIGEST = "sha256:" + "a" * 64


def _step(**changes: Any) -> ExecutionStep:
    fields: dict[str, Any] = {
        "run_id": "r012",
        "command": ("python", "code/train.py", "--seed", "0"),
        "image_digest": DIGEST,
        "read_only_paths": ("code", "inputs"),
        "output_directory": "runs/r012/outputs",
        "limits": ResourceLimits(cpus=2.0, memory_mb=1024, max_processes=64, disk_mb=128),
        "timeout_seconds": 600.0,
        "environment": {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "2"},
    }
    return ExecutionStep(**{**fields, **changes})


def _arguments(project: Path, step: ExecutionStep | None = None) -> list[str]:
    return docker_run_arguments(
        step or _step(),
        project=project,
        container_name="utux-r012-0000",
        user="1000:1000",
        defaults=DEFAULT_LIMITS,
    )


# The arguments


def test_the_arguments_are_exactly_these(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert _arguments(tmp_path) == [
        "docker",
        "run",
        "--name=utux-r012-0000",
        "--user=1000:1000",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--network=none",
        "--hostname=utux-sandbox",
        "--log-driver=none",
        "--pids-limit=64",
        "--memory=1024m",
        "--memory-swap=1024m",
        "--cpus=2.0",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=128m",
        f"--workdir={CONTAINER_PROJECT}",
        f"--mount=type=bind,source={root}/code,target=/project/code,readonly",
        f"--mount=type=bind,source={root}/inputs,target=/project/inputs,readonly",
        f"--mount=type=bind,source={root}/runs/r012/outputs,target=/project/runs/r012/outputs",
        "--env=OMP_NUM_THREADS=2",
        "--env=PYTHONHASHSEED=0",
        DIGEST,
        "python",
        "code/train.py",
        "--seed",
        "0",
    ]


def test_limits_that_are_not_set_take_the_defaults(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path, _step(limits=ResourceLimits()))
    assert f"--pids-limit={DEFAULT_LIMITS.max_processes}" in arguments
    assert f"--memory={DEFAULT_LIMITS.memory_mb}m" in arguments
    assert f"--memory-swap={DEFAULT_LIMITS.memory_mb}m" in arguments
    assert f"--cpus={DEFAULT_LIMITS.cpus}" in arguments
    assert any(a.endswith(f"size={DEFAULT_LIMITS.disk_mb}m") for a in arguments)
    assert DEFAULT_LIMITS.output_mb == 1024


def test_nothing_widens_the_sandbox(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    joined = " ".join(arguments)
    for forbidden in ("--privileged", "--device", "seccomp=unconfined", "--cap-add", "--pid=host"):
        assert forbidden not in joined
    assert "--network=host" not in arguments
    assert "docker.sock" not in joined
    assert f"source={Path.home()}," not in joined
    # Only the output directory is mounted writable.
    writable = [a for a in arguments if a.startswith("--mount=") and not a.endswith(",readonly")]
    assert writable == [
        f"--mount=type=bind,source={tmp_path.resolve()}/runs/r012/outputs,"
        "target=/project/runs/r012/outputs"
    ]


def test_only_the_steps_variables_are_passed_each_with_its_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UTUX_SYNTHETIC_HOST_VARIABLE", "host-only")
    arguments = _arguments(tmp_path)
    environment = [a for a in arguments if a.startswith("--env") or a in ("-e",)]
    assert environment == ["--env=OMP_NUM_THREADS=2", "--env=PYTHONHASHSEED=0"]
    # NAME without a value would make docker copy it from the host.
    assert all("=" in a.removeprefix("--env=") for a in environment)
    assert "UTUX_SYNTHETIC_HOST_VARIABLE" not in " ".join(arguments)


def test_gpus_are_passed_through_only_when_configured(tmp_path: Path) -> None:
    assert not any(a.startswith("--gpus") for a in _arguments(tmp_path))
    with_gpu = _arguments(tmp_path, _step(limits=ResourceLimits(gpus=1)))
    assert "--gpus=1" in with_gpu
    assert not any(a.startswith("--device") for a in with_gpu)


def test_a_path_that_would_break_the_mount_syntax_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "a,b"
    project.mkdir()
    with pytest.raises(ExecutorError, match="comma"):
        _arguments(project)


# Checks before anything runs


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    for directory in ("code", "inputs"):
        (project / directory).mkdir(parents=True)
    return project


def _missing_docker(project: Path) -> DockerExecutor:
    return DockerExecutor(project, docker="utux-synthetic-no-such-docker")


def test_a_missing_docker_is_a_clear_error_and_nothing_runs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(ExecutorUnavailableError, match="Docker"):
        _missing_docker(project).run(_step())
    assert not (project / "runs").exists()


def test_a_read_only_path_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(ExecutorError, match=r"inputs/missing\.csv"):
        _missing_docker(project).run(_step(read_only_paths=("inputs/missing.csv",)))


def test_a_read_only_path_that_leads_outside_the_project_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "inputs" / "escape").symlink_to(tmp_path)
    with pytest.raises(ExecutorError, match="outside the project"):
        _missing_docker(project).run(_step(read_only_paths=("inputs/escape",)))


def test_a_socket_is_never_mounted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project / "inputs" / "s"
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(path))
        with pytest.raises(ExecutorError, match="socket"):
            _missing_docker(project).run(_step(read_only_paths=("inputs/s",)))
    finally:
        server.close()


def test_an_output_directory_that_is_not_empty_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = project / "runs" / "r012" / "outputs"
    output.mkdir(parents=True)
    (output / "old.txt").write_bytes(b"synthetic")
    with pytest.raises(ExecutorError, match="not empty"):
        _missing_docker(project).run(_step())


def test_utux_refuses_to_run_a_container_as_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "getuid", lambda: 0)
    with pytest.raises(ExecutorError, match="root"):
        _missing_docker(_project(tmp_path)).run(_step())


def test_an_output_directory_whose_parent_leads_outside_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "runs").symlink_to(outside)
    with pytest.raises(ExecutorError, match="outside the project"):
        _missing_docker(project).run(_step())
    # Nothing was created through the link.
    assert list(outside.iterdir()) == []


def test_the_output_directory_is_checked_again_after_it_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulates a parent that is swapped for a symbolic link between the first
    # check and the creation of the directory.
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    executor = DockerExecutor(project)
    monkeypatch.setattr(executor, "rootless", lambda: False)
    monkeypatch.setattr(executor, "_check_image", lambda digest: None)
    original_mkdir = Path.mkdir

    def mkdir_through_a_link(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == project / "runs" / "r012" / "outputs":
            (project / "runs").symlink_to(outside)
            original_mkdir(outside / "r012" / "outputs", parents=True)
            return
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir_through_a_link)
    with pytest.raises(ExecutorError, match="outside the project"):
        executor.run(_step())


def test_the_size_of_a_directory_counts_every_file_below_it(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "a").write_bytes(b"x" * 10)
    (tmp_path / "sub" / "b").write_bytes(b"x" * 5)
    (tmp_path / "link").symlink_to(tmp_path / "a")
    # A symbolic link counts as itself, not as what it points to.
    assert directory_size(tmp_path) == 15 + (tmp_path / "link").lstat().st_size
    assert directory_size(tmp_path / "missing") == 0


def test_the_executor_is_named_docker(tmp_path: Path) -> None:
    assert _missing_docker(tmp_path).name == "docker"


# Docker's report of a kill for memory (M1-07 follow-up)


def _fake_inspect(tmp_path: Path, answers: list[str]) -> Path:
    """A docker stand-in whose `inspect` gives the answers in turn, then the last."""
    calls = tmp_path / "calls"
    calls.write_text("0", encoding="utf-8")
    lines = "\n".join(f'    {n}) echo "{answer}" ;;' for n, answer in enumerate(answers))
    script = tmp_path / "fake-docker"
    script.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{calls}")\n'
        f'echo $((n + 1)) > "{calls}"\n'
        'case "$n" in\n'
        f"{lines}\n"
        f'    *) echo "{answers[-1]}" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _calls(tmp_path: Path) -> int:
    return int((tmp_path / "calls").read_text(encoding="utf-8"))


def test_a_late_report_after_exit_137_is_waited_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("utux.executors.docker.time.sleep", lambda seconds: None)
    docker = _fake_inspect(tmp_path, ["false", "false", "true"])
    executor = DockerExecutor(tmp_path, docker=str(docker))
    assert executor._oom_killed("utux-r001-0000", 137) is True
    assert _calls(tmp_path) == 3


def test_without_a_report_no_limit_is_named_after_about_a_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waited: list[float] = []
    monkeypatch.setattr("utux.executors.docker.time.sleep", waited.append)
    docker = _fake_inspect(tmp_path, ["false"])
    executor = DockerExecutor(tmp_path, docker=str(docker))
    assert executor._oom_killed("utux-r001-0000", 137) is False
    assert 0.8 <= sum(waited) <= 1.5
    assert _calls(tmp_path) > 1


def test_another_exit_status_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("utux.executors.docker.time.sleep", lambda seconds: None)
    docker = _fake_inspect(tmp_path, ["false", "true"])
    executor = DockerExecutor(tmp_path, docker=str(docker))
    assert executor._oom_killed("utux-r001-0000", 1) is False
    assert _calls(tmp_path) == 1


# Naming the memory limit in a whole run, with a fake docker


def _fake_docker_run(tmp_path: Path, oom_killed: str) -> Path:
    """A docker stand-in for a whole run: the daemon answers with seccomp on,
    the image is present, the container exits with 137, and inspect reports
    OOMKilled as given."""
    script = tmp_path / "fake-docker"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  info) echo '[\"name=seccomp,profile=builtin\"]' ;;\n"
        f'  image) echo "{DIGEST}" ;;\n'
        "  run) exit 137 ;;\n"
        f'  inspect) echo "{oom_killed}" ;;\n'
        "  rm|kill) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.mark.parametrize(("reported", "named"), [("true", "memory"), ("false", None)])
def test_memory_is_named_exactly_when_docker_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reported: str, named: str | None
) -> None:
    monkeypatch.setattr("utux.executors.docker.time.sleep", lambda seconds: None)
    project = _project(tmp_path)
    executor = DockerExecutor(project, docker=str(_fake_docker_run(tmp_path, reported)))
    result = executor.run(_step())
    assert result.exit_status == 137
    assert (None if result.stopped_by is None else result.stopped_by.value) == named
