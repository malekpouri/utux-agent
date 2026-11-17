"""The atomic file writer.

Every contract file that is replaced as a whole is written through this
module. The content goes to a temporary file in the same directory, is
forced to disk, and is then renamed over the target. A reader, or a process
that starts after a crash, sees either the complete old file or the complete
new one, never a part of either.

`events.jsonl` is the exception: it is only ever appended to, by
`utux.events.log`.
"""

import contextlib
import os
import secrets
from pathlib import Path

from utux.errors import AtomicWriteError


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a file with the given text, encoded as UTF-8.

    Raises:
        AtomicWriteError: If the file cannot be written. The target is then
            unchanged, and no temporary file is left.
    """
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace a file with the given bytes.

    The directory of the file must exist. The target itself is never opened
    for writing.

    Raises:
        AtomicWriteError: If the file cannot be written. The target is then
            unchanged, and no temporary file is left.
    """
    # Same directory, so the rename never crosses a file system. The name
    # starts with a dot and ends in .tmp; project .gitignore files ignore it.
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except OSError as error:
        raise AtomicWriteError(f"cannot write {path}: {error.strerror}") from error
    replaced = False
    try:
        try:
            remaining = memoryview(data)
            while remaining:
                remaining = remaining[os.write(fd, remaining) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        replaced = True
        _sync_directory(path.parent)
    except OSError as error:
        raise AtomicWriteError(f"cannot write {path}: {error.strerror}") from error
    finally:
        # Also runs for an interrupt, which is not an OSError.
        if not replaced:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)


def _sync_directory(directory: Path) -> None:
    """Force the rename itself to disk."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
