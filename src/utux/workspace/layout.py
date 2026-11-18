"""The fixed layout of a project directory.

The names here follow the specification, section 7, "Project directory".
Nothing in this module depends on where a project is on disk.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from utux.workspace.hashing import hash_directory

CONFIG_FILE = "utux.yaml"
EVENT_LOG_FILE = "events.jsonl"
CLAIM_LEDGER_FILE = "claims.jsonl"
RESULTS_FILE = "results.jsonl"
GITIGNORE_FILE = ".gitignore"
GITKEEP_FILE = ".gitkeep"

PROJECT_DIRECTORIES = (
    "inputs",
    "sources",
    "code",
    "runs",
    "figures",
    "paper",
    "approvals",
    ".utux/meta",
)
"""The directories that exist after `utux init`. Each starts with a `.gitkeep`."""

HASH_EXCLUDE_ENTRIES = (".gitkeep", ".DS_Store", "__pycache__/", "*.pyc")
"""What a directory hash of project content leaves out, as documented.

These are files that tools create beside the content and that say nothing
about it. The list is fixed: changing it changes directory hashes, which
needs a new `schema_version` of the artifact metadata sidecar.
"""

HASH_EXCLUDE = (
    ".gitkeep",
    "*/.gitkeep",
    ".DS_Store",
    "*/.DS_Store",
    "__pycache__",
    "*/__pycache__",
    "*.pyc",
)
"""`HASH_EXCLUDE_ENTRIES` as patterns for `hash_directory`, at every depth.

A pattern of `hash_directory` must match the whole relative path, and `*`
also matches `/`, so a plain name needs one pattern for the top level and
one for below it.
"""

ADR_0009_IGNORE_LINES = (
    "inputs/**",
    "!inputs/**/",
    "!inputs/**/*.md",
    "!inputs/.gitkeep",
    "runs/*/outputs/",
)
"""The ignore lines of ADR-0009: large files stay out of git.

Every file under `inputs/` except `*.md` files, and everything under
`runs/<run_id>/outputs/`. The directories under `inputs/` are taken back so
that git still looks for `*.md` files in them, and `inputs/.gitkeep` is taken
back so that the directory is in the first commit.
"""

GITIGNORE_LINES = (
    ".DS_Store",
    "__pycache__/",
    "*.pyc",
    ".utux/checkpoints.sqlite*",
    ".utux/lock",
    ".*.tmp",
    *ADR_0009_IGNORE_LINES,
)
"""The lines of a project's `.gitignore`.

The exclude entries without `.gitkeep`, which git must track so that empty
directories are kept, plus the checkpoint database with SQLite's `-wal`,
`-shm` and `-journal` files beside it, the project lock, the temporary files
of the atomic writer, and the lines of ADR-0009. `ignored_by_git` reads these
same lines, so what `utux validate` treats as kept out of git is what
`utux init` writes.
"""


def _pattern_regex(pattern: str) -> str:
    # Translates the subset of gitignore syntax used in GITIGNORE_LINES: "*",
    # "?", a leading "**/", a "/**/" in the middle and a trailing "/**".
    out: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".+")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        elif pattern[index] in "[]\\":
            raise ValueError(f"unsupported gitignore syntax in {pattern!r}")
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return "".join(out)


@dataclass(frozen=True)
class _IgnoreRule:
    regex: re.Pattern[str]
    negated: bool
    directory_only: bool
    anchored: bool


def _rules(lines: tuple[str, ...]) -> tuple[_IgnoreRule, ...]:
    rules: list[_IgnoreRule] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        anchored = "/" in pattern
        pattern = pattern.lstrip("/")
        regex = re.compile(_pattern_regex(pattern))
        rules.append(_IgnoreRule(regex, negated, directory_only, anchored))
    return tuple(rules)


_GITIGNORE_RULES = _rules(GITIGNORE_LINES)


def _excluded(relative: str, directory: bool) -> bool:
    # As git: the last rule that matches decides.
    excluded = False
    name = relative.rsplit("/", 1)[-1]
    for rule in _GITIGNORE_RULES:
        if rule.directory_only and not directory:
            continue
        if rule.regex.fullmatch(relative if rule.anchored else name):
            excluded = not rule.negated
    return excluded


def ignored_by_git(relative: str, *, directory: bool = False) -> bool:
    """Whether the project's `.gitignore` keeps a path out of git.

    It applies `GITIGNORE_LINES`, the lines `utux init` writes, as git does:
    the last matching line decides, and nothing below an excluded directory
    can be taken back.

    Args:
        relative: A path relative to the project directory, with `/`.
        directory: Whether the path is a directory.
    """
    parts = relative.split("/")
    for depth in range(1, len(parts)):
        if _excluded("/".join(parts[:depth]), directory=True):
            return True
    return _excluded(relative, directory)


def hash_project_directory(directory: Path) -> str:
    """Return the content hash of a directory of project content.

    This is `hash_directory` with the fixed exclude list of the workspace.

    Raises:
        HashingError: As `hash_directory`.
    """
    return hash_directory(directory, exclude=HASH_EXCLUDE)
