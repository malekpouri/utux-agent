"""M0-15c: the citation existence items of gold v0, on a synthetic search; no network.

Real references come from SciFact titles found by OpenAlex title search,
accepted only when exactly one result has the identical normalised title
(maintainer, PR #59 review). Each real reference also gives one altered copy
whose expected reason follows from the alteration.
"""

import json
from pathlib import Path

import pytest
from utux.evalkit.existence_items import (
    Construction,
    ExistenceItem,
    RealReference,
    build_existence_items,
    find_real_references,
    scifact_titles,
)

from utux.errors import ContractValidationError, LiteratureUnavailableError
from utux.interfaces.literature_source import WorkMetadata
from utux.schemas.source_record import Author
from utux.verification.existence import check_reference


def _work(
    n: int, title: str, author: str | None = "Jane Doe", year: int | None = 2020
) -> WorkMetadata:
    return WorkMetadata(
        identifier=f"doi:10.0000/synthetic-{n}",
        title=title,
        authors=(Author(display_name=author),) if author else (),
        year=year,
    )


class _Search:
    """A synthetic OpenAlex search: results by query, or an error."""

    def __init__(self, results: dict[str, object]) -> None:
        self.results = results
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        self.queries.append((query, limit))
        found = self.results[query]
        if isinstance(found, Exception):
            raise found
        assert isinstance(found, tuple)
        return found


TITLES = {
    "1": "A Synthetic Method Comparison",
    "2": "Synthetic title two",
    "3": "Synthetic title three",
    "4": "Synthetic title four",
    "5": "Synthetic title five",
    "6": "Synthetic title six",
    "7": "Another synthetic study of mice",
    "8": "A third synthetic survey of clinics",
}

SEARCH = _Search(
    {
        TITLES["1"]: (_work(1, "A synthetic method comparison."), _work(9, "Unrelated")),
        TITLES["2"]: (_work(2, "Synthetic title two"), _work(22, "Synthetic Title: Two")),
        TITLES["3"]: (_work(3, "Synthetic title three, revisited"),),
        TITLES["4"]: (_work(4, "Synthetic title four", year=None),),
        TITLES["5"]: (_work(5, "Synthetic title five", author=None),),
        TITLES["6"]: LiteratureUnavailableError("synthetic outage"),
        TITLES["7"]: (_work(7, "Another synthetic study of mice", author="Ann Roe", year=2015),),
        TITLES["8"]: (_work(8, "A third synthetic survey of clinics", author="Li Wu", year=2011),),
    }
)


def _records() -> tuple[RealReference, ...]:
    records, _ = find_real_references(TITLES, SEARCH)
    return records


def test_only_exactly_one_identical_normalised_title_is_accepted() -> None:
    records, dropped = find_real_references(TITLES, SEARCH)
    assert [r.doc_id for r in records] == ["1", "7", "8"]
    assert dropped == {
        "ambiguous_title": 1,
        "no_identical_title": 1,
        "missing_year": 1,
        "missing_author": 1,
        "search_failed": 1,
    }
    first = records[0]
    assert (first.identifier, first.title, first.year) == (
        "doi:10.0000/synthetic-1",
        "A Synthetic Method Comparison",
        2020,
    )
    assert first.first_author_display == "Jane Doe"
    # The cited family name is the display name's last word: a construction rule.
    assert first.first_author_family == "Doe"


def test_each_real_reference_gives_one_real_item_and_one_altered_copy() -> None:
    records = _records()
    items = build_existence_items(records, seed=4)
    assert len(items) == 2 * len(records)
    real = [i for i in items if i.construction is Construction.REAL]
    altered = [i for i in items if i.construction is not Construction.REAL]
    assert len(real) == len(altered) == 3
    assert {i.construction for i in altered} == {
        Construction.TITLE_ALTERED,
        Construction.AUTHOR_ALTERED,
        Construction.YEAR_ALTERED,
    }
    for item in real:
        assert (item.expected_exists, item.expected_reasons, item.source_item) == (True, (), None)
    for item in altered:
        assert item.expected_exists is False
        assert item.source_item in {r.item_id for r in real}


def test_the_expected_reasons_are_what_the_existence_check_gives() -> None:
    records = {r.identifier: r for r in _records()}
    for item in build_existence_items(tuple(records.values()), seed=4):
        record = records[item.reference.identifier]
        work = WorkMetadata(
            identifier=record.identifier,
            title=record.title,
            authors=(Author(display_name=record.first_author_display),),
            year=record.year,
        )
        result = check_reference(item.reference.as_reference(), work)
        assert [r.value for r in result.reasons] == list(item.expected_reasons)


def test_a_real_item_and_its_altered_copy_share_a_split_and_the_build_is_fixed() -> None:
    items = build_existence_items(_records(), seed=4)
    assert items == build_existence_items(_records(), seed=4)
    by_id = {i.item_id: i for i in items}
    for item in items:
        assert item.split is not None
        if item.source_item is not None:
            assert item.split is by_id[item.source_item].split
    assert all(i.provenance.licence == "CC BY-NC 2.0" for i in items)


def test_titles_come_from_the_scifact_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "data" / "corpus.jsonl"
    corpus.parent.mkdir()
    rows = [{"doc_id": 1, "title": " A title ", "abstract": [], "structured": False}]
    corpus.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert scifact_titles(tmp_path, ["1", "2"]) == {"1": "A title"}


def test_an_item_whose_parts_disagree_is_refused() -> None:
    (item, *_) = build_existence_items(_records(), seed=4)
    document = json.loads(item.to_json())
    document["expected_exists"] = not document["expected_exists"]
    with pytest.raises(ContractValidationError):
        ExistenceItem.validate_document(document, "synthetic")
