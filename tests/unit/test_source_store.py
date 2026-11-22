"""M2-03: the source store in `sources/`.

Every source here is synthetic.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from utux.sources.store import (
    NO_TEXT,
    read_source,
    source_file_stem,
    source_text,
    stored_passages,
    write_source,
)

from utux.errors import SourceStoreError
from utux.schemas.claim_ledger import CheckedText
from utux.schemas.source_record import SourceRecord
from utux.sources.passages import split_passages
from utux.workspace.hashing import hash_bytes
from utux.workspace.validation import validate_project

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEXT = "We compare A and B. A beats B on dataset X. A is slow."


def _record(**changes: Any) -> SourceRecord:
    document = json.loads(
        (FIXTURES / "source_record" / "valid" / "abstract_from_index.json").read_text("utf-8")
    )
    document.update(source_id="doi:10.0000/Synthetic", text_hash=hash_bytes(TEXT.encode()))
    document.update(changes)
    return SourceRecord.validate_document(document, "record")


def _metadata_only() -> SourceRecord:
    return _record(
        storage_permitted=False,
        stored_text=None,
        text_hash=None,
        extraction_method=None,
        extraction_tool_version=None,
        extraction_quality=None,
    )


@pytest.mark.parametrize(
    ("source_id", "stem"),
    [
        # sha256("doi:10.0000/example") begins with c13671bc.
        ("doi:10.0000/example", "doi-10-0000-example-c13671bc"),
        ("arXiv:2101.00001v2", "arxiv-2101-00001v2-"),
        ("pmid:00000000", "pmid-00000000-"),
    ],
)
def test_the_file_name_is_the_slug_and_the_hash_of_the_source_id(source_id: str, stem: str) -> None:
    found = source_file_stem(source_id)
    assert found.startswith(stem)
    slug, digest = found.rsplit("-", 1)
    assert len(digest) == 8
    assert all(c.isdigit() or "a" <= c <= "f" for c in digest)
    assert slug == "".join(c if "a" <= c <= "z" or c.isdigit() else "-" for c in source_id.lower())


def test_a_long_source_id_is_cut_to_sixty_characters() -> None:
    stem = source_file_stem("doi:10.0000/" + "x" * 200)
    slug, _ = stem.rsplit("-", 1)
    assert len(slug) == 60


def test_two_ids_with_one_slug_get_two_names() -> None:
    assert source_file_stem("doi:10.0000/A") != source_file_stem("doi:10.0000/a")


def test_a_source_is_written_text_first_and_read_back(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    record = _record()
    write_source(tmp_path, record, TEXT)
    stem = source_file_stem(record.source_id)
    assert (tmp_path / "sources" / f"{stem}.txt").read_text(encoding="utf-8") == TEXT
    stored = read_source(tmp_path, record.source_id)
    assert stored.record == record
    assert stored.text == TEXT
    # Passages are computed, never stored.
    assert sorted(p.name for p in (tmp_path / "sources").iterdir()) == [
        f"{stem}.json",
        f"{stem}.txt",
    ]
    assert stored_passages(tmp_path, record.source_id) == split_passages(TEXT, CheckedText.ABSTRACT)


def test_a_text_whose_hash_is_not_the_records_is_refused(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    with pytest.raises(SourceStoreError, match="hash"):
        write_source(tmp_path, _record(), TEXT + " Changed.")
    assert not list((tmp_path / "sources").iterdir())


def test_a_source_that_may_not_be_stored_takes_no_text(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    with pytest.raises(SourceStoreError, match="licence"):
        write_source(tmp_path, _metadata_only(), TEXT)
    write_source(tmp_path, _metadata_only(), None)
    found = source_text(tmp_path, "doi:10.0000/Synthetic")
    assert (found.text, found.reason) == (None, NO_TEXT)
    assert stored_passages(tmp_path, "doi:10.0000/Synthetic") == ()


def test_a_record_with_text_needs_its_text(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    with pytest.raises(SourceStoreError, match="text"):
        write_source(tmp_path, _record(), None)


def test_a_text_changed_on_disk_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    record = _record()
    write_source(tmp_path, record, TEXT)
    stem = source_file_stem(record.source_id)
    (tmp_path / "sources" / f"{stem}.txt").write_text(TEXT + " Edited.", encoding="utf-8")
    with pytest.raises(SourceStoreError, match="hash"):
        read_source(tmp_path, record.source_id)


def test_an_unknown_source_is_reported(tmp_path: Path) -> None:
    (tmp_path / "sources").mkdir()
    with pytest.raises(SourceStoreError, match=r"doi:10\.0000/none"):
        read_source(tmp_path, "doi:10.0000/none")


# utux validate


def _project(tmp_path: Path) -> Path:
    import shutil

    project = tmp_path / "p"
    shutil.copytree(FIXTURES / "projects" / "valid_full", project)
    return project


def _codes(project: Path) -> list[tuple[str, str]]:
    return [(p.file, p.code) for p in validate_project(project).problems]


def test_validate_checks_the_file_name_of_a_record(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (record_file,) = (project / "sources").glob("*.json")
    record_file.rename(project / "sources" / "renamed.json")
    assert ("sources/renamed.json", "name_mismatch") in _codes(project)


def test_validate_checks_the_stored_text_against_its_hash(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (text_file,) = (project / "sources").glob("*.txt")
    text_file.write_text("Synthetic text changed by hand.", encoding="utf-8")
    assert (f"sources/{text_file.name}", "text_hash_mismatch") in _codes(project)


def test_validate_reports_a_missing_text_and_a_text_without_record(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (text_file,) = (project / "sources").glob("*.txt")
    text_file.rename(project / "sources" / "orphan.txt")
    codes = _codes(project)
    assert ("sources/orphan.txt", "text_without_record") in codes
    (record_file,) = (project / "sources").glob("*.json")
    assert (f"sources/{record_file.name}", "missing_text") in codes
