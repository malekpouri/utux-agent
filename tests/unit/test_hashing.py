"""M0-04: content hashes of files and directories.

Expected digests in this module were computed with the `sha256sum` command,
not with the code under test, and are written out in full.
"""

import random
from collections.abc import Iterator
from pathlib import Path

import pytest

from utux.errors import HashingError, UtuxError
from utux.workspace import hashing
from utux.workspace.hashing import hash_bytes, hash_directory, hash_file

# printf 'utux\n' | sha256sum
UTUX_HASH = "sha256:418c433eb52e5838993c37b93bb1d9cf6fbee1070b8c5e0a41fcf4aa53275ad8"
# printf '' | sha256sum
EMPTY_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
# printf 'alpha\n' | sha256sum and printf 'beta\n' | sha256sum
ALPHA_HEX = "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060"
BETA_HEX = "f2c82decdd7181cf98945929a62598db7e6b477e11f6e0eb0ae97020eff151ad"
# printf 'a.txt\0%s\nsub/b.txt\0%s\n' $ALPHA_HEX $BETA_HEX | sha256sum
TREE_HASH = "sha256:a3338c328701eec0ab2aadb60025f8bc97d9a3009b823432554cc1f2aebb5435"


def _tree(root: Path, order: list[str]) -> Path:
    content = {"a.txt": b"alpha\n", "sub/b.txt": b"beta\n"}
    root.mkdir()
    for name in order:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content[name])
    return root


# Files


def test_hash_of_fixed_bytes_is_the_written_out_value() -> None:
    assert hash_bytes(b"utux\n") == UTUX_HASH
    assert hash_bytes(b"") == EMPTY_HASH


def test_hash_of_a_file_is_the_written_out_value(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"utux\n")
    assert hash_file(path) == UTUX_HASH
    # Stable across calls.
    assert hash_file(path) == UTUX_HASH


def test_file_hash_does_not_depend_on_name_or_location(tmp_path: Path) -> None:
    (tmp_path / "deep" / "er").mkdir(parents=True)
    first = tmp_path / "one.txt"
    second = tmp_path / "deep" / "er" / "two.dat"
    first.write_bytes(b"utux\n")
    second.write_bytes(b"utux\n")
    assert hash_file(first) == hash_file(second) == UTUX_HASH


def test_file_is_hashed_as_bytes_without_newline_translation(tmp_path: Path) -> None:
    unix = tmp_path / "unix.txt"
    windows = tmp_path / "windows.txt"
    unix.write_bytes(b"utux\n")
    windows.write_bytes(b"utux\r\n")
    assert hash_file(unix) == UTUX_HASH
    assert hash_file(windows) != UTUX_HASH


def test_large_file_is_hashed_in_pieces(tmp_path: Path) -> None:
    data = b"0123456789abcdef" * 200_000  # larger than one read
    path = tmp_path / "large.bin"
    path.write_bytes(data)
    assert hash_file(path) == hash_bytes(data)


def test_missing_file_is_a_typed_error_naming_the_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.bin"
    with pytest.raises(HashingError, match="missing.bin"):
        hash_file(path)
    assert issubclass(HashingError, UtuxError)


def test_hash_file_refuses_a_directory(tmp_path: Path) -> None:
    with pytest.raises(HashingError):
        hash_file(tmp_path)


# Directories


def test_directory_hash_is_the_written_out_value(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree", ["a.txt", "sub/b.txt"])
    assert hash_directory(root) == TREE_HASH


def test_directory_hash_is_independent_of_creation_order(tmp_path: Path) -> None:
    first = _tree(tmp_path / "first", ["a.txt", "sub/b.txt"])
    second = _tree(tmp_path / "second", ["sub/b.txt", "a.txt"])
    assert hash_directory(first) == hash_directory(second) == TREE_HASH


def test_directory_hash_is_independent_of_listing_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file system may list entries in any order; the hash must not change."""
    root = tmp_path / "many"
    root.mkdir()
    for index in range(20):
        folder = root / f"d{index % 4}"
        folder.mkdir(exist_ok=True)
        (folder / f"f{index:02d}.txt").write_bytes(f"content {index}\n".encode())
    expected = hash_directory(root)

    real = hashing._iter_files
    orders: list[list[Path]] = []

    def shuffled(directory: Path, seed: int) -> Iterator[Path]:
        files = list(real(directory))
        random.Random(seed).shuffle(files)
        orders.append(files)
        return iter(files)

    for seed in range(5):
        monkeypatch.setattr(hashing, "_iter_files", lambda d, s=seed: shuffled(d, s))
        assert hash_directory(root) == expected
    # The listing orders really differed.
    assert len({tuple(order) for order in orders}) > 1


def test_directory_hash_does_not_depend_on_where_the_directory_is(tmp_path: Path) -> None:
    first = _tree(tmp_path / "here", ["a.txt", "sub/b.txt"])
    (tmp_path / "far" / "away").mkdir(parents=True)
    second = _tree(tmp_path / "far" / "away" / "there", ["a.txt", "sub/b.txt"])
    assert hash_directory(first) == hash_directory(second)


def test_directory_hash_changes_with_content_name_and_placement(tmp_path: Path) -> None:
    changed_content = _tree(tmp_path / "content", ["a.txt", "sub/b.txt"])
    (changed_content / "a.txt").write_bytes(b"alpha!\n")
    renamed = _tree(tmp_path / "renamed", ["a.txt", "sub/b.txt"])
    (renamed / "a.txt").rename(renamed / "c.txt")
    moved = _tree(tmp_path / "moved", ["a.txt", "sub/b.txt"])
    (moved / "sub" / "b.txt").rename(moved / "b.txt")
    hashes = {hash_directory(path) for path in (changed_content, renamed, moved)}
    assert len(hashes) == 3
    assert TREE_HASH not in hashes


def test_content_cannot_be_moved_between_file_name_and_file_content(tmp_path: Path) -> None:
    """Two different trees must not produce the same input to the digest."""
    first = tmp_path / "first"
    first.mkdir()
    (first / "ab").write_bytes(b"c")
    second = tmp_path / "second"
    second.mkdir()
    (second / "a").write_bytes(b"bc")
    assert hash_directory(first) != hash_directory(second)


def test_empty_directory_has_the_hash_of_no_entries(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    assert hash_directory(root) == EMPTY_HASH


def test_empty_subdirectories_do_not_change_the_hash(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree", ["a.txt", "sub/b.txt"])
    (root / "nothing" / "here").mkdir(parents=True)
    assert hash_directory(root) == TREE_HASH


def test_symbolic_link_inside_a_directory_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree", ["a.txt", "sub/b.txt"])
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not part of the tree\n")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(HashingError, match="link.txt"):
        hash_directory(root)


def test_symbolic_link_to_a_directory_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree", ["a.txt", "sub/b.txt"])
    (root / "loop").symlink_to(root, target_is_directory=True)
    with pytest.raises(HashingError, match="loop"):
        hash_directory(root)


def test_hash_directory_refuses_a_file_and_a_missing_path(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(b"x")
    with pytest.raises(HashingError):
        hash_directory(path)
    with pytest.raises(HashingError):
        hash_directory(tmp_path / "missing")
