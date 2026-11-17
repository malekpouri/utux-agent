"""M0-07: the atomic file writer."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from utux.errors import AtomicWriteError, UtuxError
from utux.workspace.atomic import atomic_write_bytes, atomic_write_text

OLD = "old content\n"
NEW = "new content that is longer than the old one\n" * 50


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def test_writes_a_new_file(tmp_path: Path) -> None:
    target = tmp_path / "claims.jsonl"
    atomic_write_text(target, NEW)
    assert target.read_text(encoding="utf-8") == NEW
    assert _names(tmp_path) == ["claims.jsonl"]


def test_replaces_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")
    atomic_write_text(target, NEW)
    assert target.read_text(encoding="utf-8") == NEW
    assert _names(tmp_path) == ["utux.yaml"]


def test_writes_bytes_unchanged_and_text_as_utf_8(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "data.bin", b"\x00\xff\r\n")
    assert (tmp_path / "data.bin").read_bytes() == b"\x00\xff\r\n"
    atomic_write_text(tmp_path / "text.md", "café\n")
    assert (tmp_path / "text.md").read_bytes() == "café\n".encode()


def test_empty_content_gives_an_empty_file(tmp_path: Path) -> None:
    atomic_write_text(tmp_path / "results.jsonl", "")
    assert (tmp_path / "results.jsonl").read_bytes() == b""


def test_temporary_file_is_in_the_same_directory_and_is_renamed_over_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")
    seen: list[tuple[Path, str, str]] = []
    real_replace = os.replace

    def spy(source: Any, destination: Any) -> None:
        # At the moment of the rename the temporary file is complete and the
        # target still holds the old content.
        seen.append(
            (
                Path(source),
                Path(source).read_text(encoding="utf-8"),
                target.read_text(encoding="utf-8"),
            )
        )
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", spy)
    atomic_write_text(target, NEW)
    ((temporary, temporary_content, target_content),) = seen
    assert temporary.parent == tmp_path
    assert temporary != target
    assert temporary_content == NEW
    assert target_content == OLD


def test_temporary_file_is_flushed_to_disk_before_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (steps.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(
        os, "replace", lambda a, b: (steps.append("replace"), real_replace(a, b))[1]
    )
    atomic_write_text(tmp_path / "utux.yaml", NEW)
    assert steps[:2] == ["fsync", "replace"]


def test_target_is_never_opened_for_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")
    opened: list[str] = []
    real_open = os.open

    def spy(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & (os.O_WRONLY | os.O_RDWR):
            opened.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    atomic_write_text(target, NEW)
    assert opened
    assert str(target) not in opened


# Interrupted writes


def _assert_untouched(tmp_path: Path, target: Path) -> None:
    assert target.read_text(encoding="utf-8") == OLD
    # No partial file and no temporary file is left behind.
    assert _names(tmp_path) == [target.name]


def test_failure_at_the_rename_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")

    def fail(source: Any, destination: Any) -> None:
        raise OSError(5, "synthetic failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(AtomicWriteError, match=r"utux\.yaml"):
        atomic_write_text(target, NEW)
    _assert_untouched(tmp_path, target)
    assert issubclass(AtomicWriteError, UtuxError)


def test_failure_in_the_middle_of_writing_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")
    real_write = os.write
    calls = 0

    def half_then_fail(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Half of the content reaches the temporary file.
            return real_write(fd, bytes(data)[: len(data) // 2])
        raise OSError(28, "synthetic: no space left on device")

    monkeypatch.setattr(os, "write", half_then_fail)
    with pytest.raises(AtomicWriteError):
        atomic_write_text(target, NEW)
    assert calls == 2
    _assert_untouched(tmp_path, target)


def test_interrupt_before_the_rename_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A person pressing Ctrl-C is not an OSError; the target must still be intact."""
    target = tmp_path / "utux.yaml"
    target.write_text(OLD, encoding="utf-8")

    def interrupt(fd: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "fsync", interrupt)
    with pytest.raises(KeyboardInterrupt):
        atomic_write_text(target, NEW)
    _assert_untouched(tmp_path, target)


def test_failed_first_write_leaves_no_file_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(source: Any, destination: Any) -> None:
        raise OSError(5, "synthetic failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(AtomicWriteError):
        atomic_write_text(tmp_path / "claims.jsonl", NEW)
    assert _names(tmp_path) == []


def test_short_writes_are_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: real_write(fd, bytes(data)[:7]))
    atomic_write_text(tmp_path / "utux.yaml", NEW)
    assert (tmp_path / "utux.yaml").read_text(encoding="utf-8") == NEW


# Other failures


def test_missing_directory_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(AtomicWriteError, match="no-such-directory"):
        atomic_write_text(tmp_path / "no-such-directory" / "utux.yaml", NEW)
    assert _names(tmp_path) == []


def test_target_that_is_a_directory_is_a_typed_error(tmp_path: Path) -> None:
    (tmp_path / "paper").mkdir()
    with pytest.raises(AtomicWriteError):
        atomic_write_text(tmp_path / "paper", NEW)
    assert _names(tmp_path) == ["paper"]


def test_new_file_has_ordinary_permissions(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        atomic_write_text(tmp_path / "utux.yaml", NEW)
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "utux.yaml").stat().st_mode) == 0o644
