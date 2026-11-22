"""M0-06b: the source record schema."""

import json
from pathlib import Path
from typing import Any

import pytest
from contract_checks import (
    Row,
    check_invalid,
    check_round_trip,
    check_table,
    problems,
    read_valid,
    valid_paths,
)

from utux.schemas.claim_ledger import CheckedText, ExtractionQuality
from utux.schemas.source_record import (
    Redistribution,
    SourceRecord,
    SourceVersion,
    load_source_record,
)

CONTRACT = "source_record"

FIELDS = [
    "schema_version",
    "source_id",
    "url",
    "licence",
    "redistribution",
    "source_version",
    "retrieval_route",
    "retrieved_at",
    "stored_text",
    "text_hash",
    "extraction_method",
    "extraction_tool_version",
    "extraction_quality",
    "storage_permitted",
    "title",
    "authors",
    "year",
    "venue",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID: list[Row] = [
    ("missing_licence.json", "licence", "missing"),
    ("missing_text_hash.json", "text_hash", "missing"),
    ("unknown_key.json", "abstract_text", "unknown_key"),
    ("unknown_redistribution.json", "redistribution", "enum"),
    ("unknown_source_version.json", "source_version", "enum"),
    ("unknown_stored_text.json", "stored_text", "enum"),
    ("unknown_extraction_quality.json", "extraction_quality", "enum"),
    ("url_not_http.json", "url", "string_pattern_mismatch"),
    ("retrieved_at_is_a_date_only.json", "retrieved_at", "utc_timestamp"),
    ("text_hash_elided.json", "text_hash", "string_pattern_mismatch"),
    ("empty_source_id.json", "source_id", "string_too_short"),
    ("extraction_method_is_a_sentence.json", "extraction_method", "string_pattern_mismatch"),
    ("stored_text_without_hash.json", "text_hash", "required_with_text"),
    (
        "stored_text_without_extraction_quality.json",
        "extraction_quality",
        "required_with_text",
    ),
    ("hash_without_stored_text.json", "text_hash", "not_allowed_without_text"),
    (
        "full_text_from_an_index_abstract.json",
        "stored_text",
        "stored_text_exceeds_source_version",
    ),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def _record(**changes: Any) -> dict[str, Any]:
    return {**read_valid(CONTRACT, "full_text_from_publisher.json"), **changes}


def test_record_has_the_proposed_fields() -> None:
    assert sorted(SourceRecord.model_fields) == sorted(FIELDS)


def test_every_field_is_required() -> None:
    for field in FIELDS:
        document = _record()
        del document[field]
        assert problems(SourceRecord, document) == [(field, "missing")]


def test_full_text_record_reads_every_field() -> None:
    record = load_source_record(valid_paths(CONTRACT)[1])
    assert record.source_id == "doi:10.0000/example"
    assert record.url == "https://example.org/paper/10.0000/example"
    assert record.licence == "CC-BY-4.0"
    assert record.redistribution is Redistribution.FULL_TEXT
    assert record.source_version is SourceVersion.PUBLISHER
    assert record.retrieval_route == "openalex"
    assert record.retrieved_at == "2026-11-15T09:12:00Z"
    assert record.stored_text is CheckedText.FULL_TEXT
    assert record.text_hash is not None
    assert record.extraction_method == "publisher_xml"
    assert record.extraction_tool_version == "synthetic-extractor 1.2.0"
    assert record.extraction_quality is ExtractionQuality.CLEAN


def test_closed_sets() -> None:
    # RFC-002, section 2: redistribution of the full text, of the abstract, or of neither.
    assert {value.value for value in Redistribution} == {"full_text", "abstract", "none"}
    # RFC-001, S2: publisher version, preprint version, or abstract from an index.
    assert {value.value for value in SourceVersion} == {"publisher", "preprint", "index_abstract"}


def test_source_without_stored_text_has_no_hash_and_no_extraction() -> None:
    record = load_source_record(valid_paths(CONTRACT)[2])
    assert record.stored_text is None
    assert record.text_hash is None
    assert record.extraction_method is None
    assert record.extraction_tool_version is None
    assert record.extraction_quality is None


def test_stored_text_needs_hash_method_and_quality() -> None:
    document = _record(text_hash=None, extraction_method=None, extraction_quality=None)
    assert problems(SourceRecord, document) == [
        ("text_hash", "required_with_text"),
        ("extraction_method", "required_with_text"),
        ("extraction_quality", "required_with_text"),
    ]


def test_tool_version_may_be_null_when_text_is_stored() -> None:
    record = SourceRecord.from_json(json.dumps(_record(extraction_tool_version=None)))
    assert record.extraction_tool_version is None


def test_no_stored_text_allows_none_of_the_text_fields() -> None:
    document = _record(stored_text=None)
    assert problems(SourceRecord, document) == [
        ("text_hash", "not_allowed_without_text"),
        ("extraction_method", "not_allowed_without_text"),
        ("extraction_tool_version", "not_allowed_without_text"),
        ("extraction_quality", "not_allowed_without_text"),
    ]


@pytest.mark.parametrize(
    "url", ["example.org/paper", "file:///etc/passwd", "javascript:alert(1)", "https://", ""]
)
def test_url_is_http_or_https(url: str) -> None:
    assert [field for field, _ in problems(SourceRecord, _record(url=url))] == ["url"]


@pytest.mark.parametrize("path", valid_paths(CONTRACT), ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    check_round_trip(SourceRecord, load_source_record, path)


def test_invalid_fixture_table() -> None:
    check_table(CONTRACT, INVALID)


@pytest.mark.parametrize("row", INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(CONTRACT, load_source_record, row)


def test_abstract_from_an_index_cannot_have_stored_full_text() -> None:
    document = _record(source_version="index_abstract", stored_text="full_text")
    assert problems(SourceRecord, document) == [
        ("stored_text", "stored_text_exceeds_source_version")
    ]


@pytest.mark.parametrize("stored", ["abstract", None])
def test_abstract_from_an_index_may_store_the_abstract_or_nothing(stored: str | None) -> None:
    changes: dict[str, Any] = {"source_version": "index_abstract", "stored_text": stored}
    if stored is None:
        changes.update(
            text_hash=None,
            extraction_method=None,
            extraction_tool_version=None,
            extraction_quality=None,
        )
    record = SourceRecord.from_json(json.dumps(_record(**changes)))
    assert (record.stored_text.value if record.stored_text else None) == stored


@pytest.mark.parametrize("version", ["publisher", "preprint"])
@pytest.mark.parametrize("stored", ["abstract", "full_text"])
def test_other_versions_may_store_either_text(version: str, stored: str) -> None:
    document = _record(source_version=version, stored_text=stored)
    assert SourceRecord.from_json(json.dumps(document)).source_version.value == version


# M2-03: storage permission and bibliographic metadata


def test_a_source_whose_licence_forbids_storage_holds_no_text() -> None:
    document = _record(storage_permitted=False)
    assert ("stored_text", "text_not_permitted") in problems(SourceRecord, document)
    metadata_only = _record(
        storage_permitted=False,
        stored_text=None,
        text_hash=None,
        extraction_method=None,
        extraction_tool_version=None,
        extraction_quality=None,
    )
    assert SourceRecord.validate_document(metadata_only, "record").stored_text is None


def test_the_bibliographic_metadata_is_read() -> None:
    record = load_source_record(valid_paths(CONTRACT)[1])
    assert record.title == "A synthetic study of method A"
    assert [(a.family, a.given) for a in record.authors] == [("Doe", "Jane"), ("Roe", None)]
    assert (record.year, record.venue) == (2024, "Synthetic Journal")


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"year": 999}, "year"),
        ({"year": "2024"}, "year"),
        ({"title": ""}, "title"),
        ({"authors": [{"family": ""}]}, "authors.0.family"),
        ({"authors": [{"family": "Doe", "given": "J", "orcid": "x"}]}, "authors.0.orcid"),
    ],
)
def test_bibliographic_fields_are_checked(changes: dict[str, Any], field: str) -> None:
    assert field in [name for name, _ in problems(SourceRecord, _record(**changes))]


def test_unknown_metadata_may_be_null_or_empty() -> None:
    record = SourceRecord.validate_document(
        _record(title=None, authors=[], year=None, venue=None), "record"
    )
    assert (record.title, record.authors, record.year, record.venue) == (None, (), None, None)
