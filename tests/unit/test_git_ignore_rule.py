"""M1-03: the rule that says whether git keeps a path out of a project.

`ignored_by_git` reads the very lines `utux init` writes to `.gitignore`, so
the rule and the file cannot drift apart. These tests compare it with git
itself, on paths that git ignores and on paths that it tracks.
"""

import subprocess
from pathlib import Path

import pytest

from utux.workspace.layout import ADR_0009_IGNORE_LINES, GITIGNORE_LINES, ignored_by_git

# (path, ignored by git). Files under inputs/ other than *.md and everything
# under runs/<id>/outputs/ are kept out of git (ADR-0009).
FILES = [
    ("inputs/question.md", False),
    ("inputs/sub/notes.md", False),
    ("inputs/.gitkeep", False),
    ("inputs/data.csv", True),
    ("inputs/sub/raw.bin", True),
    ("inputs/README.MD", True),
    ("runs/r012/manifest.json", False),
    ("runs/r012/log.txt", False),
    ("runs/r012/outputs/model.bin", True),
    ("runs/r012/outputs/sub/table.csv", True),
    ("method.md", False),
    ("code/train.py", False),
    ("code/__pycache__/train.cpython-312.pyc", True),
    (".utux/checkpoints.sqlite", True),
    (".utux/checkpoints.sqlite-wal", True),
    (".utux/checkpoints.sqlite-shm", True),
    (".utux/checkpoints.sqlite-journal", True),
    (".utux/lock", True),
    (".utux/staging/methodology/method.md", True),
    (".utux/settings-snapshot.yaml", False),
    (".utux/meta/method-v003.json", False),
    (".method.md.tmp", True),
    ("results.jsonl", False),
]


def _git_ignored(repository: Path, paths: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=repository,
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.splitlines())


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("\n".join(GITIGNORE_LINES) + "\n", encoding="utf-8")
    for path, _ in FILES:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(b"synthetic\n")
    return tmp_path


def test_the_expected_values_are_what_git_does(repository: Path) -> None:
    ignored = _git_ignored(repository, [path for path, _ in FILES])
    assert ignored == {path for path, expected in FILES if expected}


@pytest.mark.parametrize(("path", "expected"), FILES, ids=[row[0] for row in FILES])
def test_the_rule_agrees_with_git_on_files(path: str, expected: bool) -> None:
    assert ignored_by_git(path) is expected


def test_the_rule_agrees_with_git_on_directories(repository: Path) -> None:
    directories = ["runs/r012/outputs", "inputs/sub", "runs/r012", "code/__pycache__", "code"]
    ignored = _git_ignored(repository, directories)
    assert {d for d in directories if ignored_by_git(d, directory=True)} == ignored
    assert ignored == {"runs/r012/outputs", "code/__pycache__"}


def test_the_lines_of_adr_0009_are_part_of_the_written_lines() -> None:
    assert GITIGNORE_LINES[-len(ADR_0009_IGNORE_LINES) :] == ADR_0009_IGNORE_LINES
