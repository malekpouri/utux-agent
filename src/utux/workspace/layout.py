"""The fixed layout of a project directory.

The names here follow the specification, section 7, "Project directory".
Nothing in this module depends on where a project is on disk.
"""

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

GITIGNORE_LINES = (
    ".DS_Store",
    "__pycache__/",
    "*.pyc",
    ".utux/checkpoints.sqlite",
    ".*.tmp",
)
"""The lines of a project's `.gitignore`.

The exclude entries without `.gitkeep`, which git must track so that empty
directories are kept, plus the checkpoint database and the temporary files
of the atomic writer.
"""


def hash_project_directory(directory: Path) -> str:
    """Return the content hash of a directory of project content.

    This is `hash_directory` with the fixed exclude list of the workspace.

    Raises:
        HashingError: As `hash_directory`.
    """
    return hash_directory(directory, exclude=HASH_EXCLUDE)
