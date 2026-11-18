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
| `limits` | `cpus`, `memory_mb`, `gpus`, `disk_mb`, `max_processes`; each optional | Resource limits. A limit that is not set is left to the executor |
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
| `stopped_by` | `wall_clock`, `memory`, `processes`, `disk`, or null | The limit that stopped the run |

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
