"""M0-07: creating a project with `init_project`."""

import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, ProjectInitError, UtuxError
from utux.events.log import EventLog
from utux.schemas.event import EventStatus, EventType
from utux.schemas.project_config import DataPolicy, OversightMode, load_project_config
from utux.workspace import project as project_module
from utux.workspace.hashing import hash_directory
from utux.workspace.layout import (
    GITIGNORE_LINES,
    HASH_EXCLUDE,
    HASH_EXCLUDE_ENTRIES,
    PROJECT_DIRECTORIES,
    hash_project_directory,
)
from utux.workspace.project import init_project

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = datetime(2026, 11, 15, 9, 0, 0, 125_000, tzinfo=UTC)

# What `utux init` creates, written out. `.git/` is listed separately.
EXPECTED_FILES = [
    ".gitignore",
    ".utux/meta/.gitkeep",
    "approvals/.gitkeep",
    "claims.jsonl",
    "code/.gitkeep",
    "events.jsonl",
    "figures/.gitkeep",
    "inputs/.gitkeep",
    "paper/.gitkeep",
    "results.jsonl",
    "runs/.gitkeep",
    "sources/.gitkeep",
    "utux.yaml",
]


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give git a synthetic identity that does not depend on the machine."""
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    return config


def _init(directory: Path, **changes: Any) -> Path:
    options: dict[str, Any] = {
        "budget_usd": 20.0,
        "data_policy": DataPolicy.LOCAL_ONLY,
        "clock": lambda: FIXED_TIME,
    }
    return init_project(directory, **{**options, **changes})


def _files(directory: Path) -> list[str]:
    return sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(directory).parts
    )


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=directory, capture_output=True, text=True, check=True
    )
    return result.stdout


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes() if path.is_file() else b"<dir>"
        for path in sorted(directory.rglob("*"))
    }


# The tree


def test_created_tree_is_the_expected_listing(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    assert project == tmp_path / "my-project"
    assert _files(project) == EXPECTED_FILES
    assert (project / ".git").is_dir()


def test_created_tree_matches_the_paths_marked_init_in_the_specification(tmp_path: Path) -> None:
    """The listing is compared with docs/spec.md, section 7, "Project directory"."""
    spec = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    tree = spec.split("### Project directory", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    marked = dict(re.findall(r"^  (\S+)\s+# \[(init|later)\]", tree, flags=re.MULTILINE))
    assert len(marked) == len(tree.strip().splitlines()) - 1  # every line but the root is marked
    project = _init(tmp_path / "my-project")
    for path, when in marked.items():
        exists = (project / path).exists()
        assert exists == (when == "init"), f"{path} is marked {when}"
    # Nothing was created that the specification does not list, apart from
    # the .gitkeep files it describes and the git repository.
    listed_files = {
        path for path, when in marked.items() if when == "init" and not path.endswith("/")
    }
    listed_directories = {
        path.rstrip("/") for path, when in marked.items() if when == "init" and path.endswith("/")
    }
    assert listed_directories == set(PROJECT_DIRECTORIES)
    assert set(_files(project)) == listed_files | {f"{d}/.gitkeep" for d in listed_directories}


def test_every_directory_holds_only_a_gitkeep(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    for directory in PROJECT_DIRECTORIES:
        assert [path.name for path in (project / directory).iterdir()] == [".gitkeep"]
        assert (project / directory / ".gitkeep").read_bytes() == b""


def test_claims_and_results_start_empty(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    assert (project / "claims.jsonl").read_bytes() == b""
    assert (project / "results.jsonl").read_bytes() == b""


def test_existing_empty_directory_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    assert _files(_init(target)) == EXPECTED_FILES


def test_missing_parent_directories_are_created(tmp_path: Path) -> None:
    assert _files(_init(tmp_path / "a" / "b" / "project")) == EXPECTED_FILES


# utux.yaml


def test_utux_yaml_is_valid_and_holds_the_given_options(tmp_path: Path) -> None:
    project = _init(tmp_path / "p", budget_usd=12.5, data_policy=DataPolicy.EXTERNAL_ALLOWED)
    config = load_project_config(project / "utux.yaml")
    assert config.schema_version == 1
    assert config.budget.total_usd == 12.5
    assert config.data_policy is DataPolicy.EXTERNAL_ALLOWED
    # Everything else is the documented default.
    assert config.profile == "default"
    assert config.domain_pack == "generic"
    assert config.oversight.mode is OversightMode.GUIDED
    assert config.verification.enabled is True
    assert config.budget.per_stage_usd == {}


@pytest.mark.parametrize("budget", [0, -5.0, float("inf"), float("nan")])
def test_invalid_budget_is_refused_and_nothing_is_created(tmp_path: Path, budget: float) -> None:
    with pytest.raises(ContractValidationError) as caught:
        _init(tmp_path / "p", budget_usd=budget)
    assert [p.field for p in caught.value.problems] == ["budget.total_usd"]
    assert not (tmp_path / "p").exists()


# The first event


def test_first_event_is_project_created_with_a_valid_schema(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    # Reading through the log validates the line against the event schema.
    (event,) = list(EventLog(project / "events.jsonl"))
    assert event.event_id == "e-000001"
    assert event.type is EventType.PROJECT_CREATED
    assert event.actor == "system:utux"
    assert event.status is EventStatus.OK
    assert event.status_reason is None
    assert event.ts == "2026-11-15T09:00:00.125Z"
    assert event.stage is None
    assert event.parent_id is None
    assert event.data == {}
    assert event.artifacts == ()


# Git


def test_project_is_a_git_repository_with_one_commit_of_the_whole_tree(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    assert _git(project, "rev-list", "--count", "HEAD").strip() == "1"
    assert sorted(_git(project, "ls-files").splitlines()) == EXPECTED_FILES
    assert _git(project, "status", "--porcelain") == ""
    assert _git(project, "branch", "--show-current").strip() == "main"
    assert _git(project, "log", "-1", "--format=%an <%ae>").strip() == (
        "Synthetic Person <person@example.org>"
    )
    assert "M0" not in _git(project, "log", "-1", "--format=%s")


def test_gitignore_holds_the_documented_lines(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line and not line.startswith("#")] == list(GITIGNORE_LINES)


def test_gitignore_really_ignores_what_it_names(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    (project / ".utux" / "checkpoints.sqlite").write_bytes(b"x")
    (project / "code" / "__pycache__").mkdir()
    (project / "code" / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
    (project / "code" / "stray.pyc").write_bytes(b"x")
    (project / "paper" / ".DS_Store").write_bytes(b"x")
    (project / ".utux.yaml.0123abcd.tmp").write_bytes(b"x")
    assert _git(project, "status", "--porcelain") == ""
    (project / "code" / "train.py").write_text("print(1)\n", encoding="utf-8")
    assert _git(project, "status", "--porcelain").strip() == "?? code/train.py"


# Refusals: nothing is changed


def test_non_empty_directory_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    target = tmp_path / "busy"
    (target / "sub").mkdir(parents=True)
    (target / "notes.txt").write_text("keep me\n", encoding="utf-8")
    before = _snapshot(target)
    with pytest.raises(ProjectInitError) as caught:
        _init(target)
    assert "not empty" in str(caught.value)
    assert str(target) in str(caught.value)
    assert _snapshot(target) == before
    assert issubclass(ProjectInitError, UtuxError)


def test_directory_with_only_a_hidden_file_is_not_empty(tmp_path: Path) -> None:
    target = tmp_path / "hidden"
    target.mkdir()
    (target / ".keep").write_bytes(b"")
    with pytest.raises(ProjectInitError):
        _init(target)
    assert _snapshot(target) == {".keep": b""}


def test_existing_project_is_not_initialised_twice(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    before = _snapshot(project)
    with pytest.raises(ProjectInitError):
        _init(project)
    assert _snapshot(project) == before


def test_target_that_is_a_file_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ProjectInitError):
        _init(target)
    assert target.read_text(encoding="utf-8") == "x"


def test_without_git_nothing_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ProjectInitError, match="git"):
        _init(tmp_path / "p")
    assert not (tmp_path / "p").exists()


@pytest.mark.parametrize(
    "config",
    [
        "",
        "[user]\n\tname = Synthetic Person\n",
        "[user]\n\temail = person@example.org\n",
        '[user]\n\tname = ""\n\temail = person@example.org\n',
    ],
)
def test_without_a_git_identity_nothing_is_created(
    tmp_path: Path, git_identity: Path, config: str
) -> None:
    git_identity.write_text(config, encoding="utf-8")
    existing = tmp_path / "existing"
    existing.mkdir()
    for target in (tmp_path / "new", existing):
        with pytest.raises(ProjectInitError) as caught:
            _init(target)
        message = str(caught.value)
        # The two exact commands that set the identity.
        assert 'git config --global user.name "Your Name"' in message
        assert 'git config --global user.email "you@example.org"' in message
    assert not (tmp_path / "new").exists()
    assert list(existing.iterdir()) == []


def test_identity_of_a_surrounding_repository_does_not_count(
    tmp_path: Path, git_identity: Path
) -> None:
    """The new project is its own repository and does not see an outer repository's settings."""
    git_identity.write_text("", encoding="utf-8")
    outer = tmp_path / "outer"
    outer.mkdir()
    _git(outer, "init", "-q")
    _git(outer, "config", "user.name", "Outer Person")
    _git(outer, "config", "user.email", "outer@example.org")
    with pytest.raises(ProjectInitError):
        _init(outer / "project")
    assert not (outer / "project").exists()


@pytest.mark.parametrize("existed", [False, True])
def test_failure_part_way_removes_what_was_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existed: bool
) -> None:
    target = tmp_path / "p"
    if existed:
        target.mkdir()
    real = project_module._run_git

    def fail_on_commit(directory: Path, *arguments: str) -> str:
        if arguments[0] == "commit" or "commit" in arguments:
            raise ProjectInitError("synthetic failure of git commit")
        return real(directory, *arguments)

    monkeypatch.setattr(project_module, "_run_git", fail_on_commit)
    with pytest.raises(ProjectInitError, match="synthetic failure"):
        _init(target)
    if existed:
        assert list(target.iterdir()) == []
    else:
        assert not target.exists()


# No machine-specific paths


def test_project_contains_no_machine_specific_absolute_paths(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    needles = {str(tmp_path), str(project), str(Path.home()), str(REPO_ROOT)}
    checked = 0
    for path in project.rglob("*"):
        relative = path.relative_to(project).parts
        # Git's own object store is compressed; its plain-text files are checked.
        if not path.is_file() or relative[:2] == (".git", "objects"):
            continue
        content = path.read_bytes().decode("utf-8", errors="replace")
        checked += 1
        for needle in needles:
            assert needle not in content, f"{path.relative_to(project)} contains {needle}"
    assert checked >= len(EXPECTED_FILES) + 2  # the project files, and .git/config and HEAD
    assert not any(line.startswith("/") for line in _git(project, "ls-files").splitlines())


def test_two_projects_made_alike_have_the_same_files(tmp_path: Path) -> None:
    """Nothing depends on where the project is: the files are identical byte for byte."""
    first = _init(tmp_path / "here" / "one")
    second = _init(tmp_path / "there" / "far" / "two")
    assert {name: (first / name).read_bytes() for name in _files(first)} == {
        name: (second / name).read_bytes() for name in _files(second)
    }


# The exclude list for directory hashes


def test_hash_exclude_entries_are_the_documented_four() -> None:
    assert HASH_EXCLUDE_ENTRIES == (".gitkeep", ".DS_Store", "__pycache__/", "*.pyc")


def test_gitignore_is_the_exclude_list_without_gitkeep_plus_two_lines() -> None:
    # .gitkeep must stay tracked by git, or the empty directories would be lost.
    assert GITIGNORE_LINES == (
        ".DS_Store",
        "__pycache__/",
        "*.pyc",
        ".utux/checkpoints.sqlite",
        ".*.tmp",
    )


def test_project_hash_ignores_the_excluded_entries_at_every_depth(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    (clean / "sub").mkdir(parents=True)
    (clean / "a.py").write_bytes(b"alpha\n")
    (clean / "sub" / "b.py").write_bytes(b"beta\n")
    noisy = tmp_path / "noisy"
    shutil.copytree(clean, noisy)
    for folder in (noisy, noisy / "sub"):
        (folder / ".gitkeep").write_bytes(b"")
        (folder / ".DS_Store").write_bytes(b"x")
        (folder / "stray.pyc").write_bytes(b"x")
        (folder / "__pycache__").mkdir()
        (folder / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
        (folder / "__pycache__" / "other.txt").write_bytes(b"x")
    assert hash_project_directory(noisy) == hash_project_directory(clean)
    assert hash_project_directory(clean) == hash_directory(clean)
    assert hash_directory(noisy) != hash_directory(clean)
    assert hash_project_directory(noisy) == hash_directory(noisy, exclude=HASH_EXCLUDE)


def test_project_hash_excludes_nothing_else(tmp_path: Path) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / "a.py").write_bytes(b"alpha\n")
    before = hash_project_directory(root)
    for name in (".gitignore", "notes.pyc.txt", "gitkeep", "__pycache__.py", ".hidden"):
        (root / name).write_bytes(b"x")
        after = hash_project_directory(root)
        assert after != before, name
        before = after


def test_hash_of_a_fresh_project_directory_is_that_of_an_empty_directory(tmp_path: Path) -> None:
    project = _init(tmp_path / "my-project")
    empty = tmp_path / "empty"
    empty.mkdir()
    for directory in ("code", "paper", "figures"):
        assert hash_project_directory(project / directory) == hash_directory(empty)
