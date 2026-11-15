"""M0-01: the package layout of AGENTS.md section 4 exists and is importable."""

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PACKAGES = [
    "cli",
    "schemas",
    "workspace",
    "events",
    "interfaces",
    "providers",
    "budget",
    "evalkit",
    "core",
    "verification",
]

DIRECTORIES = [
    "docs/rfc",
    "docs/adr",
    "docs/plan",
    "docs/eval",
    "packs/generic",
    "tests/unit",
    "tests/integration",
    "tests/conformance",
    "tests/fixtures",
]

FILES = [
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_is_importable(name: str) -> None:
    module = importlib.import_module(f"utux.{name}")
    assert module.__doc__, f"utux.{name} needs a docstring stating its purpose"


@pytest.mark.parametrize("relative", DIRECTORIES)
def test_directory_exists(relative: str) -> None:
    assert (REPO_ROOT / relative).is_dir()


@pytest.mark.parametrize("relative", FILES)
def test_file_exists(relative: str) -> None:
    assert (REPO_ROOT / relative).is_file()


def test_licence_is_apache_2() -> None:
    text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0" in text
