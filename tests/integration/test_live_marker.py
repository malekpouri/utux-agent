"""M0-01: the `live` marker is registered and deselected by default.

Each test runs pytest in a subprocess against a throwaway test file, using
this repository's own pytest configuration, so the assertion is about the
configuration that `uv run pytest` really uses.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SAMPLE = """\
import pytest


def test_offline() -> None:
    pass


@pytest.mark.live
def test_needs_network() -> None:
    pass
"""


def _run_pytest(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    sample = tmp_path / "test_sample.py"
    sample.write_text(SAMPLE, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(REPO_ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            "-v",
            *extra,
            str(sample),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )


def test_live_tests_are_deselected_by_default(tmp_path: Path) -> None:
    result = _run_pytest(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_offline PASSED" in result.stdout
    assert "test_needs_network" not in result.stdout
    assert "1 passed, 1 deselected" in result.stdout


def test_live_tests_run_when_selected(tmp_path: Path) -> None:
    result = _run_pytest(tmp_path, "-m", "live")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_needs_network PASSED" in result.stdout
    assert "1 passed, 1 deselected" in result.stdout


def test_live_marker_is_registered(tmp_path: Path) -> None:
    # Unknown markers are errors under --strict-markers, so a clean run with
    # the marker in use shows that it is registered.
    result = _run_pytest(tmp_path, "--strict-markers", "--markers")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "@pytest.mark.live:" in result.stdout
