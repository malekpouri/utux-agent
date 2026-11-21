# The `Executor` interface

An executor runs one command in a sandbox and reports how it ended. It is
internal in v1 (ADR-0004), with the same typed contract and conformance suite
as the public interfaces. The core never runs model-written code itself; it
hands an executor a step. The types are in `utux.interfaces.executor`. The
hardened Docker executor is task M1-07.

```python
class Executor(Protocol):
    @property
    def name(self) -> str: ...
    def run(self, step: ExecutionStep) -> RunResult: ...
```

## The step

| Field | Form | Meaning |
| --- | --- | --- |
| `run_id` | `r` and at least three digits | The run the step belongs to |
| `command` | list of non-empty arguments, at least one | The command. A list of arguments, never a shell string |
| `image_digest` | `sha256:` and 64 hexadecimal digits | The container image, by digest |
| `read_only_paths` | list of project paths | What the command may read |
| `output_directory` | project path | The only place the command may write. It may not be, contain or lie inside a read-only path (`overlaps_read_only_path`) |
| `limits` | `cpus`, `memory_mb`, `gpus`, `disk_mb`, `max_processes`, `output_mb`; each optional | Resource limits. A limit that is not set is left to the executor |
| `timeout_seconds` | number above 0 | The wall-clock limit |
| `environment` | mapping of name to text | The only environment variables the command sees |

Paths are relative to the project, with `/`, and without `.` or `..` parts.

An environment variable name must be letters, digits and `_`, not starting
with a digit (`invalid_environment_name`). A name that contains `KEY`,
`TOKEN`, `SECRET` or `PASSWORD`, in any case, is refused
(`credential_like_name`), so that no key reaches model-written code. The
rule is deliberately broad: `KEYRING` and `MONKEY_LEVEL` are refused too. A
harmless variable with such a name must be renamed, for example
`KEYRING` to `KR_BACKEND`, and the code that reads it changed to match. The
value is never repeated in the error.

## The result

| Field | Form | Meaning |
| --- | --- | --- |
| `run_id` | as in the step | |
| `exit_status` | integer, or null | The command's exit status. Null only when a limit stopped the run before it exited (`exit_status_required`) |
| `started_at`, `ended_at` | UTC timestamps | When the run started and ended; it cannot end before it starts (`ends_before_start`) |
| `stdout`, `stderr` | captured output | See below |
| `output_files` | list of `path`, `content_hash`, `size_bytes` | Every file in the output directory after the run, by its path relative to that directory, each once (`duplicate_output_file`) |
| `stopped_by` | `wall_clock`, `memory`, `processes`, `disk`, `output_size`, or null | The limit that stopped the run |

A non-zero exit status is a result, not an error: `run` reports it and raises
nothing. `run` raises `ExecutorUnavailableError` (an `ExecutorError`) only
when the sandbox cannot be used at all, for example when Docker is missing.
Nothing then runs, and nothing falls back to running on the host.

### Captured output

Each stream is kept up to a cap, by default 1 MiB, set when the executor is
created. A stream of up to the cap is kept whole. A longer one keeps half of
the cap from its start and half from its end (the extra byte of an odd cap
at the end), with a marker between them that states how many bytes were
left out, so that the end of a long standard error, where a traceback
usually is, is kept:

```text
<first half>
[utux: 936 bytes left out]
<last half>
```

| Field | Meaning |
| --- | --- |
| `content` | The stream, or its two ends with the marker between them |
| `total_bytes` | How many bytes the stream had in all |
| `cap_bytes` | The cap that applied |
| `omitted_bytes` | How many bytes were left out: `total_bytes` less `cap_bytes`, or 0 |
| `truncated` | True exactly when bytes were left out |

A cut is never silent: values that contradict each other are refused.
`OutputCapture` collects a stream chunk by chunk and gives this result;
`omission_marker(n)` is the marker.

### Output files

`utux.workspace.outputs.collect_output_files(directory)` lists the files
below the output directory in path order, with their hashes and sizes. A
symbolic link is refused with a `HashingError`, so that a run cannot make the
listing point outside its output directory. Every executor lists its outputs
with it.

## Implementations

Executors live in `utux.executors`. They depend only on the interfaces, the
schemas and `utux.workspace`, never on each other.

### The Docker executor

`utux.executors.docker.DockerExecutor(project)` runs each step in a new
container with `docker run`, through `subprocess`; no Docker SDK is used.
`docker_run_arguments` builds the command, and a unit test asserts it
argument by argument:

| Flag | Why |
| --- | --- |
| `--user=<uid>:<gid>` of the user running utux | Never root; outputs belong to the user. utux refuses to run as root |
| `--read-only` | The root file system cannot be written |
| `--cap-drop=ALL`, `--security-opt=no-new-privileges` | No Linux capabilities, no privilege gain |
| no seccomp option | Docker's default seccomp profile applies; utux refuses a daemon without seccomp |
| `--network=none` | No network |
| `--hostname=utux-sandbox` | The host name does not reach the container |
| `--log-driver=none` | Docker keeps no copy of the output on the host; the attached run still streams it to utux |
| `--pids-limit`, `--memory`, `--memory-swap` (equal), `--cpus` | Limits; a step's limit, else the executor's default (256 processes, 2048 MB, 1 CPU) |
| `--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=<disk_mb>m` | The only writable scratch space, size-limited (default 512 MB) |
| `--mount=...,readonly` per read-only path, one writable mount for the output directory | Under `/project`, the working directory |
| `--env=NAME=VALUE` per step variable | Nothing else of the host's environment |
| `--gpus=<n>` | Only when the step asks for GPUs; never `--device` |

Never `--privileged`, never the home directory, never the Docker socket.

Before a run, utux checks, without starting anything:
- that every read-only path exists, stays inside the project after
  symbolic links are resolved, and is not a socket;
- that the output directory is empty or does not exist yet, and that the
  nearest part of its path that exists is inside the project and is not a
  symbolic link; after creating it, that it is still inside the project and
  not a symbolic link;
- that Docker is installed and its daemon answers;
- that the image is present locally with exactly the step's digest, the
  local image id. utux never pulls an image during a run.

A missing Docker or an unreachable daemon is `ExecutorUnavailableError`;
there is no fallback to the host.

**Which limit stopped a run.** A limit is named only when it is known for
certain:
- the wall-clock timeout, from the executor's own timer, which then kills
  the container: `wall_clock`, with no exit status;
- the size of the output directory, which the executor measures about once a
  second and kills the container when it exceeds `output_mb` (default 1024
  MiB): `output_size`, with no exit status. The check is periodic, so a run
  can exceed the limit by what it writes within one interval;
- memory, from Docker's report that the container was killed for it
  (`State.OOMKilled`): `memory`.

Anything else is not guessed. The process limit, for example, usually makes
a fork fail inside the container rather than end the run; the result then
shows the exit status and the captured output.

The container is removed after the run. `rootless()` says whether the daemon
runs rootless, for `container.rootless` in the run manifest. Rootless Docker
is preferred but not required. With rootless Docker, the host user's id
inside the container maps to a different id on the host, so the output
directory may not be writable; this is not tested yet.

The behaviour inside a real sandbox is tested by the tests marked `docker`,
which run only on request:

```bash
uv run pytest -m docker
```

They need a Docker daemon and the local image `python:3.12-slim-bookworm`.
They show that writing outside the output directory fails, that a network
connection fails, that unmounted host paths cannot be read, that a fork bomb
is contained and ends within its timeout, that memory beyond the limit ends
the run, and that no host variable reaches the container.

What the sandbox prevents and what it does not, the image digest and rootless
Docker are described in [The sandbox](sandbox.md).

## Conformance

`tests/conformance/executor_suite.py` holds the tests that every executor
must pass:

- the result of a successful run, with its output and files;
- a non-zero exit, reported and not raised;
- output beyond the cap, cut and reported;
- the wall-clock timeout, reported as `wall_clock`;
- a missing backend, a typed error with nothing run.

An implementation subclasses `ExecutorConformance` and supplies the steps.
The scripted executor, `utux.executors.scripted.ScriptedExecutor`, passes it.
It runs nothing: it writes the files of its script into the output directory
and returns the scripted result.
