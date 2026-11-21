"""M1-10: the test commit of ADR-0010 and stage commits.

Signing programs are synthetic shell scripts set through a synthetic git
configuration; no real key or signing program is used.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from utux.workspace.commits import (
    COMMIT_CHECK_FAILED,
    COMMIT_CHECK_TIMEOUT,
    check_commits,
    commit_stage,
)


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
    return project


def _sign_with(project: Path, program: Path) -> None:
    subprocess.run(["git", "-C", str(project), "config", "commit.gpgsign", "true"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "gpg.program", str(program)], check=True)


def test_commits_work_with_an_ordinary_configuration(project: Path) -> None:
    check = check_commits(project)
    assert (check.ok, check.reason) == (True, None)


def test_a_signing_program_that_fails_makes_the_check_fail(project: Path, tmp_path: Path) -> None:
    _sign_with(project, _script(tmp_path / "sign", "exit 1\n"))
    check = check_commits(project)
    assert (check.ok, check.reason) == (False, COMMIT_CHECK_FAILED)


def test_a_signing_program_that_waits_times_out(project: Path, tmp_path: Path) -> None:
    _sign_with(project, _script(tmp_path / "sign", "sleep 30\n"))
    check = check_commits(project, timeout_seconds=1.0)
    assert (check.ok, check.reason) == (False, COMMIT_CHECK_TIMEOUT)


def test_the_check_cannot_prompt(project: Path, tmp_path: Path) -> None:
    # The signing program records what it sees, then fails. Its own standard
    # input is the data to sign, which git pipes to it; what must be closed
    # is git's standard input, which the program finds as its parent's.
    seen = tmp_path / "seen"
    _sign_with(
        project,
        _script(
            tmp_path / "sign",
            f'echo "prompt=$GIT_TERMINAL_PROMPT" > "{seen}"\n'
            f'echo "git_stdin=$(readlink /proc/$PPID/fd/0)" >> "{seen}"\n'
            "exit 1\n",
        ),
    )
    check_commits(project)
    assert seen.read_text(encoding="utf-8").split() == ["prompt=0", "git_stdin=/dev/null"]


def test_the_check_does_not_touch_the_project(project: Path) -> None:
    check_commits(project)
    log = subprocess.run(
        ["git", "-C", str(project), "rev-list", "--all", "--count"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.strip() == "0"


def test_a_stage_commit_records_every_change(project: Path) -> None:
    (project / "method.md").write_text("synthetic\n", encoding="utf-8")
    commit = commit_stage(project, "utux: methodology (e-000004)")
    assert len(commit) == 40
    status = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""
    subject = subprocess.run(
        ["git", "-C", str(project), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert subject.stdout.strip() == "utux: methodology (e-000004)"


def test_stage_commits_never_disable_signing(project: Path, tmp_path: Path) -> None:
    _sign_with(project, _script(tmp_path / "sign", "exit 1\n"))
    (project / "method.md").write_text("synthetic\n", encoding="utf-8")
    with pytest.raises(Exception, match="commit"):
        commit_stage(project, "utux: methodology (e-000004)")
    assert os.environ.get("GIT_CONFIG_GLOBAL")
