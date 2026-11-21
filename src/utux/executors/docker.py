"""The hardened Docker executor.

A step runs in a container started with `docker run` through `subprocess`;
no Docker SDK is used (M1-02). The flags follow the specification, section
10, and are built by `docker_run_arguments`, so that tests assert them
exactly:

- the host user's id, never root; a read-only root file system; all
  capabilities dropped; `no-new-privileges`; Docker's default seccomp
  profile, which the daemon must have enabled; no network;
- limits on processes, memory (swap included), CPUs, and a size-limited
  writable `/tmp`;
- the step's read-only paths mounted read-only, and only its output
  directory writable; nothing else of the host, never the home directory
  or the Docker socket;
- only the step's environment variables, each with its value;
- no `--privileged` and no `--device`; GPUs only when the step asks.

A limit is named in the result only when it is known for certain: the
wall-clock timeout from this executor's own timer, and memory from Docker's
report that the container was killed for it. Anything else shows as the exit
status and the captured output.

If Docker is missing or its daemon cannot be reached, `run` raises
`ExecutorUnavailableError`; nothing ever runs on the host instead.
"""

import json
import os
import secrets
import shutil
import stat
import subprocess
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from utux.errors import ExecutorError, ExecutorUnavailableError, HashingError
from utux.interfaces.executor import (
    DEFAULT_OUTPUT_CAP_BYTES,
    ExecutionStep,
    LimitKind,
    OutputCapture,
    ResourceLimits,
    RunResult,
)
from utux.workspace.outputs import collect_output_files

CONTAINER_PROJECT = "/project"
"""Where the project's mounted paths appear inside the container."""

DEFAULT_LIMITS = ResourceLimits(cpus=1.0, memory_mb=2048, disk_mb=512, max_processes=256)
"""The limits of a step that sets none."""

_COMMAND_TIMEOUT_SECONDS = 60.0
_READ_BYTES = 64 * 1024


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mount_source(path: Path) -> str:
    text = str(path)
    if "," in text or "\n" in text:
        raise ExecutorError(f"cannot mount {text}: a path with a comma or a newline is refused")
    return text


def docker_run_arguments(
    step: ExecutionStep,
    *,
    project: Path,
    container_name: str,
    user: str,
    defaults: ResourceLimits = DEFAULT_LIMITS,
    docker: str = "docker",
) -> list[str]:
    """Return the exact `docker run` command for a step.

    Paths are resolved against the project; the checks that they exist and
    stay inside the project are made by `DockerExecutor.run` first.

    Raises:
        ExecutorError: A path holds a comma or a newline, which the mount
            syntax cannot carry safely.
    """
    root = project.resolve()
    limits = step.limits
    pids = limits.max_processes or defaults.max_processes
    memory = limits.memory_mb or defaults.memory_mb
    cpus = limits.cpus or defaults.cpus
    disk = limits.disk_mb or defaults.disk_mb
    arguments = [
        docker,
        "run",
        f"--name={container_name}",
        f"--user={user}",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--network=none",
        "--hostname=utux-sandbox",
        f"--pids-limit={pids}",
        f"--memory={memory}m",
        # Equal to the memory limit, so that no swap is used beyond it.
        f"--memory-swap={memory}m",
        f"--cpus={cpus}",
        f"--tmpfs=/tmp:rw,noexec,nosuid,nodev,size={disk}m",
        f"--workdir={CONTAINER_PROJECT}",
    ]
    for relative in step.read_only_paths:
        source = _mount_source(root / relative)
        arguments.append(
            f"--mount=type=bind,source={source},target={CONTAINER_PROJECT}/{relative},readonly"
        )
    output = _mount_source(root / step.output_directory)
    arguments.append(
        f"--mount=type=bind,source={output},target={CONTAINER_PROJECT}/{step.output_directory}"
    )
    if limits.gpus:
        arguments.append(f"--gpus={limits.gpus}")
    # Always NAME=VALUE: a bare NAME would make docker copy it from the host.
    arguments += [f"--env={name}={value}" for name, value in sorted(step.environment.items())]
    arguments.append(step.image_digest)
    arguments += step.command
    return arguments


def _read_into(stream: IO[bytes], capture: OutputCapture) -> None:
    while chunk := stream.read(_READ_BYTES):
        capture.feed(chunk)


class DockerExecutor:
    """Runs steps in hardened Docker containers. See the module docstring."""

    def __init__(
        self,
        project: Path,
        *,
        output_cap_bytes: int = DEFAULT_OUTPUT_CAP_BYTES,
        default_limits: ResourceLimits = DEFAULT_LIMITS,
        docker: str = "docker",
        docker_environment: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Create the executor.

        Args:
            project: The project directory; step paths are relative to it.
            output_cap_bytes: How much of each output stream is kept.
            default_limits: The limits of a step that sets none.
            docker: The docker command.
            docker_environment: Variables added to the environment of the
                docker command itself, for example `DOCKER_HOST`. They never
                reach the container.
            clock: Returns the current time in UTC.
        """
        self._project = project
        self._cap = output_cap_bytes
        self._defaults = default_limits
        self._docker = docker
        self._docker_environment = dict(docker_environment or {})
        self._clock = clock
        self._rootless: bool | None = None

    @property
    def name(self) -> str:
        """The executor's name."""
        return "docker"

    def rootless(self) -> bool:
        """Whether the Docker daemon runs rootless, for the run manifest.

        Raises:
            ExecutorUnavailableError: Docker is missing or unreachable, or
                its default seccomp profile is not enabled.
        """
        if self._rootless is None:
            self._rootless = self._check_daemon()
        return self._rootless

    def run(self, step: ExecutionStep) -> RunResult:
        """Run a step in a new container and return how it ended.

        Raises:
            ExecutorError: The step cannot be run as asked: utux runs as
                root, a read-only path is missing, leads outside the project
                or is a socket, the output directory is not empty, the image
                is not present locally, or Docker could not start the
                container. Nothing ran.
            ExecutorUnavailableError: Docker is missing or unreachable.
                Nothing ran.
        """
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            raise ExecutorError(
                "utux does not run containers as root; run utux as an ordinary user"
            )
        output = self._check_paths(step)
        self.rootless()
        self._check_image(step.image_digest)
        output.mkdir(parents=True, exist_ok=True)
        name = f"utux-{step.run_id}-{secrets.token_hex(4)}"
        arguments = docker_run_arguments(
            step,
            project=self._project,
            container_name=name,
            user=f"{uid}:{gid}",
            defaults=self._defaults,
            docker=self._docker,
        )
        try:
            return self._run_container(step, arguments, name, output)
        finally:
            self._remove(name)

    # Checks

    def _check_paths(self, step: ExecutionStep) -> Path:
        root = self._project.resolve()
        home = Path.home().resolve()
        for relative in step.read_only_paths:
            path = self._project / relative
            if not path.exists():
                raise ExecutorError(f"the read-only path {relative} does not exist")
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ExecutorError(
                    f"the read-only path {relative} leads outside the project; it is not mounted"
                )
            if resolved == home or home.is_relative_to(resolved):
                raise ExecutorError("the home directory is never mounted")
            if stat.S_ISSOCK(resolved.stat().st_mode):
                raise ExecutorError(f"{relative} is a socket; sockets are never mounted")
        output = self._project / step.output_directory
        if output.exists():
            if not output.resolve().is_relative_to(root) or not output.is_dir():
                raise ExecutorError(
                    f"the output directory {step.output_directory} is not a directory "
                    "inside the project"
                )
            if any(output.iterdir()):
                raise ExecutorError(
                    f"the output directory {step.output_directory} is not empty; a run "
                    "writes into a fresh directory"
                )
        return output

    def _docker_command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self._docker, *arguments],
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=_COMMAND_TIMEOUT_SECONDS,
                env={**os.environ, **self._docker_environment},
            )
        except subprocess.TimeoutExpired as error:
            raise ExecutorUnavailableError(
                f"docker {arguments[0]} did not answer within {_COMMAND_TIMEOUT_SECONDS:.0f} s"
            ) from error

    def _check_daemon(self) -> bool:
        if shutil.which(self._docker) is None:
            raise ExecutorUnavailableError(
                f"Docker is not installed ({self._docker} was not found); utux runs code "
                "only inside a Docker sandbox and never on the host"
            )
        info = self._docker_command("info", "--format", "{{json .SecurityOptions}}")
        if info.returncode != 0:
            detail = (info.stderr.strip().splitlines() or ["no message"])[-1]
            raise ExecutorUnavailableError(
                f"the Docker daemon cannot be reached: {detail}; utux never runs code on "
                "the host instead"
            )
        try:
            options = json.loads(info.stdout)
        except json.JSONDecodeError as error:
            raise ExecutorUnavailableError("docker info gave an answer utux cannot read") from error
        if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
            raise ExecutorUnavailableError("docker info gave an answer utux cannot read")
        if not any(option.startswith("name=seccomp") for option in options):
            raise ExecutorUnavailableError(
                "the Docker daemon has no seccomp profile enabled; the sandbox requires it"
            )
        return any(option == "name=rootless" for option in options)

    def _check_image(self, digest: str) -> None:
        found = self._docker_command("image", "inspect", "--format", "{{.Id}}", digest)
        if found.returncode != 0 or found.stdout.strip() != digest:
            raise ExecutorError(
                f"the image {digest} is not present locally; utux does not pull images during a run"
            )

    # The run

    def _run_container(
        self, step: ExecutionStep, arguments: list[str], name: str, output: Path
    ) -> RunResult:
        stdout, stderr = OutputCapture(self._cap), OutputCapture(self._cap)
        started = self._clock()
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **self._docker_environment},
        )
        # Both are pipes, as asked above.
        assert process.stdout is not None
        assert process.stderr is not None
        readers = [
            threading.Thread(target=_read_into, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=_read_into, args=(process.stderr, stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=step.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._docker_command("kill", name)
            try:
                process.wait(timeout=_COMMAND_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for reader in readers:
            reader.join()
        ended = self._clock()
        status = process.returncode
        stopped_by: LimitKind | None = None
        if timed_out:
            stopped_by, exit_status = LimitKind.WALL_CLOCK, None
        else:
            state = self._docker_command("inspect", "--format", "{{.State.OOMKilled}}", name)
            if state.returncode != 0:
                # The container was never created; docker run said why.
                detail = stderr.result().content.decode("utf-8", errors="replace").strip()
                raise ExecutorError(f"Docker could not start the container: {detail}")
            if state.stdout.strip() == "true":
                stopped_by = LimitKind.MEMORY
            exit_status = status
        try:
            files = collect_output_files(output)
        except HashingError as error:
            raise ExecutorError(f"the run left an output utux cannot list: {error}") from error
        return RunResult(
            run_id=step.run_id,
            exit_status=exit_status,
            started_at=_timestamp(started),
            ended_at=_timestamp(max(ended, started)),
            stdout=stdout.result(),
            stderr=stderr.result(),
            output_files=files,
            stopped_by=stopped_by,
        )

    def _remove(self, name: str) -> None:
        removed = self._docker_command("rm", "--force", name)
        if removed.returncode != 0 and "No such container" not in removed.stderr:
            raise ExecutorError(f"the container {name} could not be removed: {removed.stderr}")
