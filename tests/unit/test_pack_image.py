"""M1-08: the generic pack's image, its recorded digest and `utux image build`.

The image is not built here. The build is tested with a fake `docker` that
writes an image id where `docker build --iidfile` would.
"""

import re
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.errors import ExecutorError, PackImageError
from utux.executors.image import (
    DIGEST_FILE,
    build_image,
    load_recorded_digest,
    require_recorded_image,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_IMAGE = REPO_ROOT / "packs" / "generic" / "image"
DIGEST = "sha256:" + "c" * 64
OTHER = "sha256:" + "d" * 64

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


# The Dockerfile


def _dockerfile() -> str:
    return (PACK_IMAGE / "Dockerfile").read_text(encoding="utf-8")


def test_the_base_image_is_pinned_by_digest() -> None:
    (base,) = re.findall(r"^FROM\s+(\S+)", _dockerfile(), flags=re.MULTILINE)
    assert re.fullmatch(r"[a-z0-9./_-]+(:[\w.-]+)?@sha256:[0-9a-f]{64}", base), base


def test_the_image_runs_as_a_non_root_user() -> None:
    users = re.findall(r"^USER\s+(\S+)", _dockerfile(), flags=re.MULTILINE)
    assert users, "the Dockerfile sets no USER"
    assert users[-1] not in ("root", "0", "0:0")


def test_every_package_is_pinned_with_its_hashes() -> None:
    text = (PACK_IMAGE / "requirements.txt").read_text(encoding="utf-8")
    requirements = re.findall(r"^([A-Za-z0-9_.-]+)==(\S+) \\", text, flags=re.MULTILINE)
    names = {name.lower() for name, _ in requirements}
    assert {"numpy", "pandas", "scikit-learn", "matplotlib"} <= names
    # Every requirement line is pinned and followed by at least one hash.
    blocks = [block for block in re.split(r"\n(?=\S)", text.strip()) if block]
    assert len(blocks) == len(requirements)
    assert all("--hash=sha256:" in block for block in blocks)
    assert "--require-hashes" in _dockerfile()


def test_nothing_in_the_image_needs_the_network_at_run_time() -> None:
    # Packages are installed at build time only; no entry point downloads.
    dockerfile = _dockerfile()
    assert "ENTRYPOINT" not in dockerfile
    assert not re.search(r"^CMD .*(pip|curl|wget)", dockerfile, flags=re.MULTILINE)


def test_the_recorded_digest_file_is_left_empty_for_the_maintainer() -> None:
    assert (PACK_IMAGE / DIGEST_FILE).read_text(encoding="utf-8") == ""
    assert load_recorded_digest(PACK_IMAGE) is None


# The recorded digest


def test_a_recorded_digest_is_read(tmp_path: Path) -> None:
    (tmp_path / DIGEST_FILE).write_text(DIGEST + "\n", encoding="utf-8")
    assert load_recorded_digest(tmp_path) == DIGEST


@pytest.mark.parametrize("content", ["latest\n", "sha256:abc\n", DIGEST + "\n" + DIGEST + "\n"])
def test_a_malformed_digest_file_is_refused(tmp_path: Path, content: str) -> None:
    (tmp_path / DIGEST_FILE).write_text(content, encoding="utf-8")
    with pytest.raises(PackImageError, match=DIGEST_FILE):
        load_recorded_digest(tmp_path)


def test_a_run_refuses_an_image_that_differs_from_the_recorded_one(tmp_path: Path) -> None:
    (tmp_path / DIGEST_FILE).write_text(DIGEST + "\n", encoding="utf-8")
    require_recorded_image(tmp_path, DIGEST)
    with pytest.raises(ExecutorError, match="differs from the recorded"):
        require_recorded_image(tmp_path, OTHER)


def test_a_run_refuses_to_start_when_no_image_is_recorded(tmp_path: Path) -> None:
    (tmp_path / DIGEST_FILE).write_text("", encoding="utf-8")
    with pytest.raises(ExecutorError, match="utux image build"):
        require_recorded_image(tmp_path, DIGEST)


# The build, with a fake docker


def _fake_docker(tmp_path: Path, image_id: str, exit_status: int = 0) -> Path:
    """A script standing in for docker: it records its arguments and writes
    the image id to the file named by --iidfile."""
    script = tmp_path / "fake-docker"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/arguments"\n'
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = "--iidfile" ]; then shift; '
        f'printf "{image_id}" > "$1"; fi\n'
        "  shift\n"
        "done\n"
        f"exit {exit_status}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _pack(tmp_path: Path) -> Path:
    pack = tmp_path / "image"
    pack.mkdir()
    (pack / "Dockerfile").write_text("FROM synthetic@sha256:" + "e" * 64 + "\n", "utf-8")
    (pack / DIGEST_FILE).write_text("", encoding="utf-8")
    return pack


def test_build_runs_docker_build_and_records_the_image_id(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    docker = _fake_docker(tmp_path, DIGEST)
    assert build_image(pack, docker=str(docker)) == DIGEST
    assert (pack / DIGEST_FILE).read_text(encoding="utf-8") == DIGEST + "\n"
    arguments = (tmp_path / "arguments").read_text(encoding="utf-8").splitlines()
    assert arguments[:2] == ["build", "--pull=false"]
    assert "--iidfile" in arguments
    assert arguments[-1] == str(pack)


def test_a_failed_build_records_nothing(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    docker = _fake_docker(tmp_path, DIGEST, exit_status=1)
    with pytest.raises(PackImageError, match="docker build failed"):
        build_image(pack, docker=str(docker))
    assert (pack / DIGEST_FILE).read_text(encoding="utf-8") == ""


def test_an_image_id_that_is_not_a_digest_is_not_recorded(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    docker = _fake_docker(tmp_path, "not-a-digest")
    with pytest.raises(PackImageError):
        build_image(pack, docker=str(docker))
    assert (pack / DIGEST_FILE).read_text(encoding="utf-8") == ""


def test_a_directory_without_a_dockerfile_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PackImageError, match="Dockerfile"):
        build_image(tmp_path, docker="docker")


def test_the_cli_builds_and_prints_the_digest(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    docker = _fake_docker(tmp_path, DIGEST)
    result = runner.invoke(app, ["image", "build", str(pack), "--docker", str(docker)])
    assert result.exit_code == 0, result.output
    assert DIGEST in result.output
    assert DIGEST_FILE in result.output


def test_the_cli_reports_a_failed_build(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    docker = _fake_docker(tmp_path, DIGEST, exit_status=1)
    result = runner.invoke(app, ["image", "build", str(pack), "--docker", str(docker)])
    assert result.exit_code == 1
    assert "docker build failed" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("document", "start"),
    [("docs/pack-image.md", "## The recorded digest"), ("docs/spec.md", "### Domain packs")],
)
def test_the_digest_examples_of_the_documents_are_valid(
    tmp_path: Path, document: str, start: str
) -> None:
    section = (REPO_ROOT / document).read_text(encoding="utf-8").split(start, 1)[1]
    found = re.search(r"```text\n(.*?)```", section, flags=re.DOTALL)
    assert found is not None
    (tmp_path / DIGEST_FILE).write_text(found.group(1), encoding="utf-8")
    assert load_recorded_digest(tmp_path) == found.group(1).strip()
