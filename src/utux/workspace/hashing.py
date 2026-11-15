"""Content hashes of files and directories.

Every hash is written as `sha256:` followed by 64 lower-case hexadecimal
digits, the form used by `content_hash` in artifact metadata.

The hash of a file is the SHA-256 of its bytes. Nothing is translated, so the
result is the same on every platform.

The hash of a directory is the SHA-256 of one entry per regular file below
it. An entry is the path of the file relative to the directory, with `/` as
separator and encoded as UTF-8, then a zero byte, then the 64 hexadecimal
digits of the file's SHA-256, then a newline. Entries are sorted by the bytes
of the path, so the order in which the file system lists files has no effect.
Directories that contain no file do not contribute. Symbolic links and
special files are refused, so that a hash never depends on content outside
the directory.
"""

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

from utux.errors import HashingError

_PREFIX = "sha256:"
_CHUNK_BYTES = 1024 * 1024


def hash_bytes(data: bytes) -> str:
    """Return the content hash of a byte string."""
    return _PREFIX + hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """Return the content hash of a file, read in pieces.

    Raises:
        HashingError: If the path cannot be read as a file.
    """
    return _PREFIX + _file_hex(path)


def hash_directory(directory: Path) -> str:
    """Return the content hash of all files below a directory.

    Raises:
        HashingError: If the path is not a directory, or if it contains a
            symbolic link, a special file, a file that cannot be read or a
            file name that is not valid Unicode.
    """
    if directory.is_symlink() or not directory.is_dir():
        raise HashingError(f"cannot hash {directory}: not a directory")
    entries = sorted((_relative_name(path, directory), path) for path in _iter_files(directory))
    digest = hashlib.sha256()
    for name, path in entries:
        digest.update(name + b"\0" + _file_hex(path).encode("ascii") + b"\n")
    return _PREFIX + digest.hexdigest()


def _file_hex(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise HashingError(f"cannot hash {path}: {error.strerror}") from error
    return digest.hexdigest()


def _relative_name(path: Path, directory: Path) -> bytes:
    name = path.relative_to(directory).as_posix()
    try:
        return name.encode("utf-8")
    except UnicodeEncodeError as error:
        raise HashingError(f"cannot hash {path!r}: the file name is not valid Unicode") from error


def _iter_files(directory: Path) -> Iterator[Path]:
    """Yield every regular file below a directory, in no particular order."""
    try:
        with os.scandir(directory) as listing:
            entries = list(listing)
    except OSError as error:
        raise HashingError(f"cannot hash {directory}: {error.strerror}") from error
    for entry in entries:
        path = Path(entry.path)
        if entry.is_symlink():
            raise HashingError(f"cannot hash {path}: symbolic links are not allowed")
        if entry.is_dir(follow_symlinks=False):
            yield from _iter_files(path)
        elif entry.is_file(follow_symlinks=False):
            yield path
        else:
            raise HashingError(f"cannot hash {path}: not a regular file")
