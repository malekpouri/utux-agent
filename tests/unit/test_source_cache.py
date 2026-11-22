"""M2-03: the machine-wide cache of API responses and source texts.

Every response and text here is synthetic; no network is used.
"""

import os
from pathlib import Path

import pytest

from utux.errors import CacheError
from utux.sources.cache import ContentCache, cache_directory
from utux.workspace.hashing import hash_bytes


def test_the_cache_directory_follows_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UTUX_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/synthetic/cache")
    assert cache_directory("linux") == Path("/synthetic/cache/utux")
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", "/synthetic/home")
    assert cache_directory("linux") == Path("/synthetic/home/.cache/utux")
    assert cache_directory("darwin") == Path("/synthetic/home/Library/Caches/utux")
    monkeypatch.setenv("UTUX_CACHE_DIR", "/synthetic/elsewhere")
    assert cache_directory("linux") == Path("/synthetic/elsewhere")


def test_a_text_is_kept_by_its_content_hash(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    data = b"Synthetic source text."
    digest = cache.put_text(data)
    assert digest == hash_bytes(data)
    assert cache.get_text(digest) == data
    assert cache.get_text(hash_bytes(b"other")) is None


def test_a_response_is_found_by_its_request(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    request = "openalex works W0000000000 select=title,abstract_inverted_index"
    assert cache.get_response(request) is None
    cache.put_response(request, b'{"synthetic": true}')
    assert cache.get_response(request) == b'{"synthetic": true}'
    # Another process of another project finds it too.
    assert ContentCache(tmp_path).get_response(request) == b'{"synthetic": true}'


def test_a_corrupted_entry_is_a_miss_and_is_removed(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    digest = cache.put_text(b"Synthetic source text.")
    (path,) = [p for p in tmp_path.rglob("*") if p.is_file() and digest[7:] in p.name]
    path.write_bytes(b"tampered")
    assert cache.get_text(digest) is None
    assert not path.exists()


def test_the_cache_never_holds_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "synthetic-secret-0123456789"
    monkeypatch.setenv("SYNTHETIC_API_KEY", secret)
    cache = ContentCache(tmp_path)
    with pytest.raises(CacheError, match="SYNTHETIC_API_KEY"):
        cache.put_response(f"works?api_key={secret}", b"{}")
    with pytest.raises(CacheError, match="SYNTHETIC_API_KEY"):
        cache.put_response("works", f'{{"echo": "{secret}"}}'.encode())
    with pytest.raises(CacheError):
        cache.put_text(secret.encode())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    assert secret not in "".join(os.listdir(tmp_path))


def test_clear_removes_every_entry_under_the_cache_lock(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    cache.put_text(b"one")
    cache.put_response("request", b"two")
    assert cache.clear() == 3  # a text, a response and its request entry
    assert cache.get_response("request") is None
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_clear_refuses_while_the_cache_is_locked(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    cache.put_text(b"one")
    (tmp_path / ".lock").write_text(f"{os.getpid()}\n", encoding="utf-8")
    with pytest.raises(CacheError, match="lock"):
        cache.clear()
    assert cache.get_text(hash_bytes(b"one")) == b"one"
