"""The machine-wide cache of API responses and source texts (task M2-03).

It lives in the platform's user cache directory, `UTUX_CACHE_DIR` if set,
and is shared across projects (specification, section 9). Everything is
kept by content hash, and checked against it when read: an entry that does
not match is removed and counts as a miss. A response is found by its
request, which maps to the hash of the response.

**It never holds keys.** A request or a body that contains the value of an
environment variable whose name ends in `KEY`, `TOKEN`, `SECRET` or
`PASSWORD` is refused, and the error names the variable, never the value.
Requests are built from URLs and parameters without credentials.

`clear` takes a lock on the cache, `.lock` in its directory, and refuses
while another process holds it.
"""

import hashlib
import os
import re
import sys
from pathlib import Path

from utux.errors import CacheError
from utux.workspace.atomic import atomic_write_bytes
from utux.workspace.hashing import hash_bytes

CACHE_ENVIRONMENT = "UTUX_CACHE_DIR"
LOCK_FILE = ".lock"
_AREAS = ("texts", "responses", "requests")
_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$")
# Shorter values, such as "1" or "true", are settings, not secrets.
_SECRET_MIN_LENGTH = 8


def cache_directory(platform: str = sys.platform) -> Path:
    """The cache directory: `UTUX_CACHE_DIR`, else the platform's user cache."""
    chosen = os.environ.get(CACHE_ENVIRONMENT)
    if chosen:
        return Path(chosen)
    home = Path(os.environ.get("HOME") or Path.home())
    if platform == "darwin":
        return home / "Library" / "Caches" / "utux"
    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "utux" / "Cache"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else home / ".cache") / "utux"


def _secret_in(*parts: bytes) -> str | None:
    """The name of a secret variable whose value appears in the parts, or None."""
    for name, value in sorted(os.environ.items()):
        if _SECRET_NAME.search(name.upper()) and len(value) >= _SECRET_MIN_LENGTH:
            needle = value.encode("utf-8")
            if any(needle in part for part in parts):
                return name
    return None


class ContentCache:
    """A cache of texts and responses kept by content hash in one directory."""

    def __init__(self, directory: Path) -> None:
        """Use the cache in `directory`; it is created on the first write."""
        self.directory = directory

    def _path(self, area: str, digest: str) -> Path:
        hexdigest = digest.removeprefix("sha256:")
        return self.directory / area / hexdigest[:2] / hexdigest

    def _refuse_secrets(self, *parts: bytes) -> None:
        name = _secret_in(*parts)
        if name is not None:
            raise CacheError(
                f"the data holds the value of {name}; the cache never holds keys, so nothing "
                "is stored"
            )

    def _put(self, area: str, data: bytes) -> str:
        digest = hash_bytes(data)
        path = self._path(area, digest)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(path, data)
        return digest

    def _get(self, area: str, digest: str) -> bytes | None:
        path = self._path(area, digest)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        if hash_bytes(data) != digest:
            path.unlink(missing_ok=True)
            return None
        return data

    def put_text(self, data: bytes) -> str:
        """Keep a source text; return its content hash.

        Raises:
            CacheError: The text holds the value of a secret variable.
        """
        self._refuse_secrets(data)
        return self._put("texts", data)

    def get_text(self, digest: str) -> bytes | None:
        """A kept text by its content hash, or None."""
        return self._get("texts", digest)

    def put_response(self, request: str, body: bytes) -> str:
        """Keep an API response, found later by its request; return its content hash.

        Raises:
            CacheError: The request or the body holds the value of a secret
                variable.
        """
        key = request.encode("utf-8")
        self._refuse_secrets(key, body)
        digest = self._put("responses", body)
        entry = self._path("requests", hashlib.sha256(key).hexdigest())
        entry.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(entry, digest.encode("ascii"))
        return digest

    def get_response(self, request: str) -> bytes | None:
        """The response kept for a request, or None."""
        entry = self._path("requests", hashlib.sha256(request.encode("utf-8")).hexdigest())
        try:
            digest = entry.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return None
        return self._get("responses", digest)

    def clear(self) -> int:
        """Remove every entry, under the cache's lock; return how many were removed.

        Raises:
            CacheError: Another process holds the lock.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / LOCK_FILE
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            holder = lock.read_text(encoding="utf-8").strip() if lock.exists() else "unknown"
            raise CacheError(
                f"the cache {self.directory} is locked by process {holder}; wait for it, or "
                f"remove {lock} if no utux command is running"
            ) from None
        try:
            os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            os.close(fd)
            removed = 0
            for area in _AREAS:
                for path in sorted((self.directory / area).rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                        removed += 1
                    elif path.is_dir():
                        path.rmdir()
            return removed
        finally:
            lock.unlink(missing_ok=True)
