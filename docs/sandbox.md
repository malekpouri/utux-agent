# The sandbox

Model-written code runs only inside a Docker container started by
`utux.executors.docker.DockerExecutor`. The flags and checks are listed in
[The `Executor` interface](executor.md); this page says what the sandbox
prevents, what it does not, and what to know when reproducing a run.

## What it prevents

Shown by the tests marked `docker` (`uv run pytest -m docker`):

- writing anywhere but the run's output directory and a size-limited `/tmp`;
- opening a network connection or resolving a name;
- reading host paths that were not mounted, including the home directory and
  the Docker socket;
- running as root inside the container;
- receiving any host environment variable the step does not name;
- using memory beyond the limit, and more processes than the limit;
- running past the wall-clock timeout;
- writing more than the output size limit into the output directory.

## Limits and how they are reported

| Limit | Enforced by | Named in the result |
| --- | --- | --- |
| Wall clock | utux's own timer, which kills the container | `wall_clock` |
| Output directory size (`output_mb`, default 1024 MiB) | utux, measuring the directory about once a second and killing the container when it is exceeded | `output_size` |
| Memory (`memory_mb`, swap equal) | Docker; the container is killed | `memory`, from Docker's own report (`OOMKilled`), asked again for about a second after exit status 137, since the report can come a moment late |
| Processes (`max_processes`) | Docker; new processes fail | not named: the result shows the exit status and output |
| `/tmp` size (`disk_mb`) | Docker's tmpfs; writes fail | not named |
| CPUs | Docker; the run is slowed, not stopped | not named |

A limit is named only when it is known for certain.

**The memory kill is not always reported.** On some Docker setups, a
container killed for memory exits with status 137 while Docker's
`OOMKilled` stays false, even when asked again for about a second. The
result then shows exit status 137 with no limit named; utux does not guess
that the cause was memory. This happened in CI on Docker 29.4.2, and not on
Docker 29.8.2 locally.

**The output size check is periodic.** Between two measurements a run can
write past the limit by as much as it writes in about one second. The
directory is a bind mount on the host disk, so the check is what keeps a run
from filling it.

**Docker keeps no copy of the output.** Containers run with
`--log-driver=none`. Otherwise Docker would store its own full, uncapped copy
of everything a run prints on the host, beside utux's capped copy. An
attached `docker run` still streams standard output and standard error to
utux; a `docker` test checks that, and another checks that the running
container's log driver is `none`.

## The image digest

`image_digest` in a step and in the run manifest is the **local image id**,
as `docker image inspect --format '{{.Id}}'` prints it. utux checks that the
image with exactly that id is present and never pulls one during a run.

The id depends on how the image was built and stored. Two machines that build
the same Dockerfile separately get different ids, and Docker's storage
backend can change what the id is. Reproducing a run on another machine
therefore needs the same image, copied or pulled by digest, not rebuilt.

## Rootless Docker

Rootless Docker is preferred but not required (specification, section 10).
`DockerExecutor.rootless()` detects it from `docker info`, and the run
manifest records it in `container.rootless`. It is **detected but not
tested**: the tests so far ran on a Docker daemon that is not rootless. Under
rootless Docker the host user's id inside the container maps to another id
on the host, so the output directory may not be writable from the container.

## What it does not prevent

**Docker is not a complete security boundary.** A container shares the
host's kernel. A flaw in the kernel, in the container runtime or in Docker
itself can let code break out of any container, whatever its flags. With a
daemon that runs as root, which is the usual setup, a breakout gives root
on the host. The flags reduce what model-written code can reach; they do
not make it safe to run hostile code on a machine that holds secrets.

The sandbox does not prevent:

- **reading what is mounted.** The step's read-only paths, `code/` and
  `inputs/` in M1, are readable in full, data files included, and the code
  can copy any of it into its output directory;
- **writing anything into the output directory**, within its size limit:
  wrong numbers, numbers written into the code rather than computed (the
  check after the analysis catches only the plain case), or data hidden in
  an output. A person reviews the code at the experiment-plan gate;
- **using the CPUs, memory and time it is given**, up to the limits; a run
  that loops is stopped only by the wall-clock timeout;
- **side channels**, such as timing or the CPU's caches, which containers do
  not isolate;
- **flaws in the image**: the packages of the pack's image run with the
  code. They are pinned by hash in `requirements.txt`
  ([The image of a pack](pack-image.md)), which fixes what is installed but
  says nothing about flaws in it; utux does not scan the image for known
  vulnerabilities yet (the specification, section 14, plans automated
  scanning in CI);
- **what GPUs expose**, when a step asks for them: GPU drivers are not
  isolated as the rest is, and the tests do not cover GPUs;
- **an attack on Docker or the host from outside utux**: the host's own
  configuration, other containers, and who may use the Docker socket are
  the host's matter.

Run utux on a machine where a breakout would cost little: a separate user,
a virtual machine or a dedicated host, with no keys in the environment of
the user who runs Docker. Prefer rootless Docker where it works.

