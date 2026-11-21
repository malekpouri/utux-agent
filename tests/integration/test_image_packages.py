"""M1-08: the locked packages of an image are read from inside it.

Marked `docker`: it needs a Docker daemon and the local image
`python:3.12-slim-bookworm`. The program that lists the packages runs in the
hardened sandbox, like any other step.
"""

import subprocess

import pytest

from utux.executors.image import image_packages

pytestmark = pytest.mark.docker

IMAGE = "python:3.12-slim-bookworm"


def test_the_packages_are_read_from_inside_the_image() -> None:
    found = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        pytest.fail(f"the image {IMAGE} is not present locally; run: docker pull {IMAGE}")
    packages = image_packages(found.stdout.strip())
    # pip is installed in the official Python image; its version is the
    # image's own, whatever any file outside the image says.
    assert "pip" in packages
    version = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network=none",
            found.stdout.strip(),
            "python",
            "-c",
            "import importlib.metadata as m; print(m.version('pip'))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert packages["pip"] == version
