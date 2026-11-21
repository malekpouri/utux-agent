"""A pack's container image: building it, its recorded digest, its packages.

A pack keeps its image in `<pack>/image/`: a `Dockerfile`, the hashed
`requirements.txt` it installs, and `digest.txt`, the id of the image the
maintainer built and committed. `build_image` builds the image and records
its id; `require_recorded_image` makes a run refuse any other image; and
`image_packages` reads the installed packages from inside the image, so that
a run manifest's `container.locked_packages` never comes from the Dockerfile.

Building needs the network to fetch the base image and the packages. Runs
never do: utux does not pull or build during a run.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

from utux.errors import ExecutorError, PackImageError
from utux.executors.docker import DockerExecutor
from utux.interfaces.executor import ExecutionStep, ResourceLimits
from utux.workspace.atomic import atomic_write_text

DIGEST_FILE = "digest.txt"
"""The file in a pack's image directory that holds the recorded image id."""

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

_LIST_PACKAGES = (
    "import importlib.metadata as m, json; "
    "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}, "
    "sort_keys=True))"
)


def load_recorded_digest(image_directory: Path) -> str | None:
    """Return the recorded image id of a pack, or None if none is recorded yet.

    `digest.txt` is empty, or holds one line: `sha256:` and 64 hexadecimal
    digits.

    Raises:
        PackImageError: The file is missing or holds anything else.
    """
    path = image_directory / DIGEST_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PackImageError(f"cannot read {path}: {error.strerror}") from error
    if text == "":
        return None
    lines = text.splitlines()
    if len(lines) != 1 or _DIGEST.fullmatch(lines[0]) is None:
        raise PackImageError(
            f"{DIGEST_FILE} must be empty or hold one image id, sha256: and 64 hexadecimal digits"
        )
    return lines[0]


def require_recorded_image(image_directory: Path, image_digest: str) -> None:
    """Refuse a run whose image is not the pack's recorded one.

    Raises:
        ExecutorError: No image is recorded yet, or the step's image differs
            from the recorded one.
        PackImageError: The digest file cannot be read.
    """
    recorded = load_recorded_digest(image_directory)
    if recorded is None:
        raise ExecutorError(
            f"no image is recorded in {image_directory / DIGEST_FILE}; build it with "
            "utux image build and commit the digest"
        )
    if image_digest != recorded:
        raise ExecutorError(
            f"the image {image_digest} differs from the recorded {recorded}; a run uses "
            "only the pack's recorded image"
        )


def build_image(image_directory: Path, *, docker: str = "docker") -> str:
    """Build a pack's image and record its id in `digest.txt`.

    The output of `docker build` goes to the terminal. The id is taken from
    `docker build --iidfile` and written with the atomic writer only after
    the build succeeded.

    Returns:
        The image id.

    Raises:
        PackImageError: There is no Dockerfile, the build failed, or it gave
            no image id. Nothing is recorded.
    """
    if not (image_directory / "Dockerfile").is_file():
        raise PackImageError(f"there is no Dockerfile in {image_directory}")
    with tempfile.TemporaryDirectory() as scratch:
        iidfile = Path(scratch) / "iid"
        try:
            built = subprocess.run(
                [docker, "build", "--pull=false", "--iidfile", str(iidfile), str(image_directory)],
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise PackImageError(f"Docker is not installed ({docker} was not found)") from error
        if built.returncode != 0:
            raise PackImageError(f"docker build failed with exit status {built.returncode}")
        image_id = iidfile.read_text(encoding="utf-8").strip() if iidfile.exists() else ""
    if _DIGEST.fullmatch(image_id) is None:
        raise PackImageError(f"docker build gave no image id that utux can record: {image_id!r}")
    atomic_write_text(image_directory / DIGEST_FILE, image_id + "\n")
    return image_id


def image_packages(image_digest: str, *, docker: str = "docker") -> dict[str, str]:
    """Read the installed Python packages, by name and version, from inside an image.

    The listing runs in the hardened sandbox, with no network, like any step.

    Raises:
        ExecutorError: The listing did not run, failed, or gave output that
            is not a mapping of names to versions.
        ExecutorUnavailableError: Docker is missing or unreachable.
    """
    with tempfile.TemporaryDirectory() as scratch:
        executor = DockerExecutor(Path(scratch), docker=docker)
        result = executor.run(
            ExecutionStep(
                run_id="r000",
                command=("python", "-c", _LIST_PACKAGES),
                image_digest=image_digest,
                read_only_paths=(),
                output_directory="outputs",
                limits=ResourceLimits(memory_mb=512, max_processes=32, cpus=1.0, disk_mb=64),
                timeout_seconds=120.0,
                environment={},
            )
        )
    if result.exit_status != 0 or result.stdout.truncated:
        raise ExecutorError(
            f"listing the packages of {image_digest} failed: exit status {result.exit_status}"
        )
    try:
        packages = json.loads(result.stdout.content)
    except json.JSONDecodeError as error:
        raise ExecutorError("listing the packages gave output utux cannot read") from error
    if not isinstance(packages, dict) or not all(
        isinstance(name, str) and isinstance(version, str) for name, version in packages.items()
    ):
        raise ExecutorError("listing the packages gave output utux cannot read")
    return packages
