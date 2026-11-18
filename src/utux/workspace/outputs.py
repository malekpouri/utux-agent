"""The files a run wrote into its output directory.

Executors call `collect_output_files` after a run, so that every executor
lists outputs the same way: every regular file below the directory, by its
path relative to the directory, with its content hash and size, in path
order. A symbolic link is refused, so that a run cannot make the listing
point at a file outside its output directory.
"""

import os
from pathlib import Path

from utux.errors import HashingError
from utux.interfaces.executor import OutputFile
from utux.workspace.hashing import hash_file


def collect_output_files(directory: Path) -> tuple[OutputFile, ...]:
    """List the files below an output directory with their hashes.

    A directory that does not exist has no files.

    Raises:
        HashingError: A symbolic link or a special file is below the
            directory, or a file cannot be read.
    """
    if not directory.exists():
        return ()
    found: list[OutputFile] = []
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current) / name
            if path.is_symlink():
                raise HashingError(f"cannot list {path}: symbolic links are not allowed")
        for name in files:
            path = Path(current) / name
            if not path.is_file():
                raise HashingError(f"cannot list {path}: not a regular file")
            found.append(
                OutputFile(
                    path=path.relative_to(directory).as_posix(),
                    content_hash=hash_file(path),
                    size_bytes=path.stat().st_size,
                )
            )
    return tuple(sorted(found, key=lambda file: file.path))
