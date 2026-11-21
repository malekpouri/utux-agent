"""Stage commits, and the test commit that comes before a run (ADR-0010).

Commits follow the user's git configuration, signing included; utux never
switches signing off. Before a run, `check_commits` makes a test commit in a
temporary repository with the project's configuration and no terminal:
standard input closed, `GIT_TERMINAL_PROMPT=0`, and a 10-second timeout. A
signing program that waits for a passphrase therefore fails the check
instead of stalling a run later.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utux.errors import CommitError

COMMIT_CHECK_FAILED = "commit_check_failed"
COMMIT_CHECK_TIMEOUT = "commit_check_timeout"
CHECK_TIMEOUT_SECONDS = 10.0
_STAGE_COMMIT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class CommitCheck:
    """The outcome of the test commit.

    Attributes:
        ok: Whether the test commit was made.
        reason: Why not, as a code (`commit_check_failed` or
            `commit_check_timeout`), or None.
    """

    ok: bool
    reason: str | None


def _environment() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _local_settings(project: Path) -> list[str]:
    """The project's own git settings, as `-c name=value` arguments."""
    listed = subprocess.run(
        ["git", "-C", str(project), "config", "--local", "--list"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env=_environment(),
    )
    arguments: list[str] = []
    for line in listed.stdout.splitlines():
        name = line.split("=", 1)[0]
        # Settings of the repository itself are not copied.
        if name.startswith("core.") or name.startswith("remote.") or name.startswith("branch."):
            continue
        arguments += ["-c", line]
    return arguments


def check_commits(project: Path, *, timeout_seconds: float = CHECK_TIMEOUT_SECONDS) -> CommitCheck:
    """Make a test commit with the project's configuration, without a terminal.

    The project itself is not touched.
    """
    settings = _local_settings(project)
    with tempfile.TemporaryDirectory() as scratch:
        try:
            subprocess.run(
                ["git", "init", "--quiet", scratch],
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                env=_environment(),
                timeout=timeout_seconds,
            )
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    scratch,
                    *settings,
                    "commit",
                    "--quiet",
                    "--allow-empty",
                    "-m",
                    "utux commit check",
                ],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                env=_environment(),
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CommitCheck(False, COMMIT_CHECK_TIMEOUT)
        except subprocess.CalledProcessError:
            return CommitCheck(False, COMMIT_CHECK_FAILED)
    if commit.returncode != 0:
        return CommitCheck(False, COMMIT_CHECK_FAILED)
    return CommitCheck(True, None)


def _git(project: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), *arguments],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=_environment(),
            timeout=_STAGE_COMMIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CommitError(f"git {arguments[0]} did not finish") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise CommitError(f"git {arguments[0]} failed: {detail}")
    return result.stdout


def commit_stage(project: Path, message: str) -> str:
    """Commit every change of the project and return the commit's id.

    Raises:
        CommitError: git failed, for example because signing failed.
    """
    _git(project, "add", "--all")
    _git(project, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(project, "rev-parse", "HEAD").strip()


def head_commit(project: Path) -> tuple[str, bool]:
    """The project's current commit and whether the working tree has changes.

    Raises:
        CommitError: The project has no commit, or git failed.
    """
    commit = _git(project, "rev-parse", "HEAD").strip()
    dirty = _git(project, "status", "--porcelain") != ""
    return commit, dirty
