"""Content hashes of files and directories.

Every hash is written as `sha256:` followed by 64 lower-case hexadecimal
digits, the form used by `content_hash` in artifact metadata.

The hash of a file is the SHA-256 of its bytes. Nothing is translated, so the
result is the same on every platform.

The hash of a directory is the SHA-256 of one entry per regular file below
it. An entry is the path of the file relative to the directory, with `/` as
separator, normalised to Unicode NFC and encoded as UTF-8, then a zero byte,
then the 64 hexadecimal digits of the file's SHA-256, then a newline. Entries
are sorted by the bytes of the path, so the order in which the file system
lists files has no effect. Directories that contain no file do not
contribute. Symbolic links and special files are refused, so that a hash
never depends on content outside the directory.

File names are normalised because one name can be stored in two Unicode
forms, depending on the platform. Two files whose names are the same after
normalisation are refused.

Nothing is excluded by default. A caller may pass patterns in `exclude`. A
pattern is a shell-style glob (`*`, `?`, `[...]`) that must match the whole
normalised relative path of a file or directory; `*` also matches `/`, and
matching is case-sensitive. An excluded directory is left out with everything
below it and is not read. For project content, `utux.workspace.layout`
supplies the fixed list through `hash_project_directory`.

A change to this format changes every directory hash, so it requires a new
`schema_version` of the artifact metadata sidecar.
"""

import hashlib
import os
import unicodedata
from collections.abc import Iterator, Sequence
from fnmatch import fnmatchcase
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


def hash_directory(directory: Path, exclude: Sequence[str] = ()) -> str:
    """Return the content hash of all files below a directory.

    Args:
        directory: The directory to hash.
        exclude: Patterns for files and directories to leave out. Nothing is
            left out by default. See the module docstring for how a pattern
            is matched.

    Raises:
        HashingError: If the path is not a directory, or if it contains a
            symbolic link, a special file, a file that cannot be read, a file
            name that is not valid Unicode, or two files whose names are the
            same after Unicode normalisation.
    """
    if directory.is_symlink() or not directory.is_dir():
        raise HashingError(f"cannot hash {directory}: not a directory")
    patterns = tuple(unicodedata.normalize("NFC", pattern) for pattern in exclude)
    files: dict[bytes, Path] = {}
    for path in _iter_files(directory, patterns):
        name = _encoded_name(path, directory)
        other = files.get(name)
        if other is not None:
            # ascii() shows the two Unicode forms as different text.
            first, second = sorted(
                ascii(found.relative_to(directory).as_posix()) for found in (other, path)
            )
            raise HashingError(
                f"cannot hash {directory}: {first} and {second} "
                "are the same file name after Unicode normalisation"
            )
        files[name] = path
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name + b"\0" + _file_hex(files[name]).encode("ascii") + b"\n")
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


def _normalised_name(path: Path, directory: Path) -> str:
    return unicodedata.normalize("NFC", path.relative_to(directory).as_posix())


def _encoded_name(path: Path, directory: Path) -> bytes:
    try:
        return _normalised_name(path, directory).encode("utf-8")
    except UnicodeEncodeError as error:
        raise HashingError(f"cannot hash {path!r}: the file name is not valid Unicode") from error


def _iter_files(directory: Path, exclude: tuple[str, ...]) -> Iterator[Path]:
    """Yield every regular file below a directory, in no particular order.

    An excluded entry is skipped before anything else is asked about it, so
    an excluded directory is never read.
    """
    yield from _walk(directory, directory, exclude)


def _walk(root: Path, current: Path, exclude: tuple[str, ...]) -> Iterator[Path]:
    try:
        with os.scandir(current) as listing:
            entries = list(listing)
    except OSError as error:
        raise HashingError(f"cannot hash {current}: {error.strerror}") from error
    for entry in entries:
        path = Path(entry.path)
        name = _normalised_name(path, root)
        if any(fnmatchcase(name, pattern) for pattern in exclude):
            continue
        if entry.is_symlink():
            raise HashingError(f"cannot hash {path}: symbolic links are not allowed")
        if entry.is_dir(follow_symlinks=False):
            yield from _walk(root, path, exclude)
        elif entry.is_file(follow_symlinks=False):
            yield path
        else:
            raise HashingError(f"cannot hash {path}: not a regular file")
