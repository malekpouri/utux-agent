"""M1-06: listing the files a run wrote, with their hashes."""

import hashlib
from pathlib import Path

import pytest

from utux.errors import HashingError
from utux.workspace.outputs import collect_output_files


def _hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def test_every_file_is_listed_with_its_relative_path_hash_and_size(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "metrics.json").write_bytes(b"{}\n")
    (tmp_path / "sub" / "figure.png").write_bytes(b"\x89PNG synthetic")
    files = collect_output_files(tmp_path)
    assert [(f.path, f.content_hash, f.size_bytes) for f in files] == [
        ("metrics.json", _hash(b"{}\n"), 3),
        ("sub/figure.png", _hash(b"\x89PNG synthetic"), 14),
    ]


def test_a_missing_or_empty_directory_has_no_files(tmp_path: Path) -> None:
    assert collect_output_files(tmp_path / "missing") == ()
    assert collect_output_files(tmp_path) == ()


def test_a_symbolic_link_is_refused(tmp_path: Path) -> None:
    (tmp_path / "secret").write_bytes(b"synthetic")
    output = tmp_path / "out"
    output.mkdir()
    (output / "link").symlink_to(tmp_path / "secret")
    with pytest.raises(HashingError):
        collect_output_files(output)
