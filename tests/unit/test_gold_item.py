"""M0-13a: the gold item schema (RFC-002, section 4).

Every fixture is synthetic; see `tests/fixtures/gold_item/README.md`. The
labels in them exercise the schema and are not annotation.
"""

import json
from pathlib import Path

import pytest

from utux.errors import ContractValidationError
from utux.evalkit.gold import (
    Domain,
    ErrorClass,
    GoldItem,
    GoldSplit,
    GoldStatus,
    Origin,
    load_gold_item,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gold_item"
VALID = sorted((FIXTURES / "valid").glob("*.json"))

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("synthetic_unknown_split.json", "split", "enum"),
    ("synthetic_unknown_domain.json", "domain", "enum"),
    ("synthetic_unknown_origin.json", "origin", "enum"),
    ("synthetic_item_id_malformed.json", "item_id", "string_pattern_mismatch"),
    ("synthetic_gold_version_malformed.json", "gold_version", "string_pattern_mismatch"),
    ("synthetic_missing_text_unit.json", "text_unit", "missing"),
    ("synthetic_unknown_key.json", "note", "unknown_key"),
    ("synthetic_no_claims.json", "claims", "too_short"),
    ("synthetic_status_unverified.json", "claims.0.status", "enum"),
    ("synthetic_unknown_kind.json", "claims.0.kind", "enum"),
    ("synthetic_expert_would_review_not_boolean.json", "claims.0.expert_would_review", "bool_type"),
    ("synthetic_claim_id_of_another_item.json", "claims.0.claim_id", "claim_id_mismatch"),
    ("synthetic_claim_without_pairs.json", "claims.0.pairs", "too_short"),
    ("synthetic_span_beyond_text_unit.json", "claims.0.span", "span_out_of_range"),
    ("synthetic_span_end_before_start.json", "claims.0.span", "span_not_increasing"),
    ("synthetic_duplicate_claim_id.json", "claims.1.claim_id", "duplicate_id"),
    ("synthetic_pair_id_of_another_claim.json", "claims.0.pairs.0.pair_id", "pair_id_mismatch"),
    ("synthetic_unknown_agreement_label.json", "claims.0.pairs.0.agreement_label", "enum"),
    ("synthetic_unknown_scope_flag.json", "claims.0.pairs.0.scope_flags.0", "enum"),
    (
        "synthetic_duplicate_scope_flag.json",
        "claims.0.pairs.0.scope_flags.1",
        "duplicate_scope_flag",
    ),
    (
        "synthetic_text_hash_not_sha256.json",
        "claims.0.pairs.0.text_hash",
        "string_pattern_mismatch",
    ),
    ("synthetic_unknown_checked_text.json", "claims.0.pairs.0.checked_text", "enum"),
    (
        "synthetic_evidence_offsets_end_before_start.json",
        "claims.0.pairs.0.evidence_spans.0.offsets",
        "offsets_not_increasing",
    ),
    ("synthetic_one_annotator.json", "annotation.annotators", "too_short"),
    ("synthetic_same_annotator_twice.json", "annotation.annotators.1", "duplicate_annotator"),
    (
        "synthetic_annotator_id_is_a_name.json",
        "annotation.annotators.0",
        "string_pattern_mismatch",
    ),
    (
        "synthetic_adjudicated_without_adjudicator.json",
        "annotation.adjudicator",
        "adjudicator_required",
    ),
    (
        "synthetic_adjudicator_is_an_annotator.json",
        "annotation.adjudicator",
        "adjudicator_is_annotator",
    ),
    (
        "synthetic_adjudicator_without_adjudication.json",
        "annotation.adjudicator",
        "adjudicator_not_allowed",
    ),
    ("synthetic_raw_labels_missing_an_annotator.json", "annotation.raw_labels.a92", "missing"),
    (
        "synthetic_raw_labels_of_another_annotator.json",
        "annotation.raw_labels.a99",
        "unknown_annotator",
    ),
    ("synthetic_unknown_raw_status.json", "annotation.raw_labels.a91.status", "enum"),
    (
        "synthetic_disagreement_not_adjudicated.json",
        "annotation.adjudicated",
        "adjudication_required",
    ),
    ("synthetic_perturbed_without_hidden.json", "hidden", "hidden_required"),
    ("synthetic_natural_with_hidden.json", "hidden", "hidden_not_allowed"),
    ("synthetic_perturbed_from_itself.json", "hidden.source_item", "self_reference"),
    ("synthetic_unknown_error_class.json", "hidden.error_class", "enum"),
    ("synthetic_confirmed_by_a_name.json", "hidden.confirmed_by", "string_pattern_mismatch"),
    ("synthetic_malformed_json.json", "<document>", "invalid_json"),
    ("synthetic_not_an_object.json", "<document>", "not_a_mapping"),
    ("synthetic_newer_schema_version.json", "schema_version", "schema_version_newer"),
]


def _document(name: str = "synthetic_perturbed_item.json") -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _problems(document: object) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        GoldItem.validate_document(document, "item.json")
    return [(problem.field, problem.code) for problem in caught.value.problems]


# Valid fixtures


def test_every_fixture_is_named_synthetic() -> None:
    names = [path.name for path in FIXTURES.rglob("*.json")]
    assert names
    assert all(name.startswith("synthetic_") for name in names)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    item = load_gold_item(path)
    line = item.to_json_line()
    again = GoldItem.from_json(line)
    assert again == item
    assert again.to_json_line() == line
    assert line.count("\n") == 1
    assert line.endswith("\n")
    assert json.loads(line) == json.loads(path.read_text(encoding="utf-8"))


def test_perturbed_fixture_reads_every_field() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_perturbed_item.json")
    assert item.item_id == "G9001"
    assert item.gold_version == "0.0"
    assert item.split is GoldSplit.DEV
    assert item.domain is Domain.ML
    assert item.origin is Origin.PERTURBED
    assert item.hard_case is None
    (claim,) = item.claims
    assert claim.claim_id == "G9001-c1"
    # The claim text without its final full stop: 78 characters.
    assert claim.span == (0, 78)
    assert item.text_unit[claim.span[0] : claim.span[1]] == claim.text[:-1]
    assert claim.status is GoldStatus.PARTIALLY_SUPPORTED
    (pair,) = claim.pairs
    assert pair.pair_id == "G9001-c1-s1"
    assert pair.source_group == "sg-synthetic-b"
    assert pair.evidence_spans[0].offsets == (10, 60)
    assert item.annotation.annotators == ("a91", "a92")
    assert item.annotation.adjudicator == "a90"
    assert item.hidden is not None
    assert item.hidden.source_item == "G9000"
    assert item.hidden.error_class is ErrorClass.SINGLE_ERROR


def test_multi_source_claim_has_one_pair_per_source() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_multi_source_item.json")
    (claim,) = item.claims
    assert [pair.pair_id for pair in claim.pairs] == ["G9003-c1-s1", "G9003-c1-s2"]
    assert [pair.source_group for pair in claim.pairs] == ["sg-synthetic-c", "sg-synthetic-d"]
    assert item.domain is Domain.BIOMEDICINE
    assert item.origin is Origin.SYSTEM_GENERATED
    assert item.annotation.ambiguous is True
    assert item.hidden is None


def test_natural_item_without_disagreement_needs_no_adjudicator() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_natural_item.json")
    assert item.annotation.adjudicated is False
    assert item.annotation.adjudicator is None
    assert item.hard_case == "abstract_vs_full_text"


def test_reference_statuses_are_the_four_scientific_statuses() -> None:
    # RFC-002, section 3: unverified is never a reference label.
    assert [status.value for status in GoldStatus] == [
        "verified",
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
    ]


# Invalid fixtures


def test_invalid_fixtures_have_distinct_reasons() -> None:
    reasons = [(field, code) for _, field, code in INVALID]
    assert len(set(reasons)) == len(reasons)


def test_every_invalid_fixture_is_listed() -> None:
    on_disk = sorted(path.name for path in (FIXTURES / "invalid").glob("*.json"))
    assert on_disk == sorted(name for name, _, _ in INVALID)


@pytest.mark.parametrize(("name", "field", "code"), INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(name: str, field: str, code: str) -> None:
    path = FIXTURES / "invalid" / name
    with pytest.raises(ContractValidationError) as caught:
        load_gold_item(path)
    error = caught.value
    assert [(problem.field, problem.code) for problem in error.problems] == [(field, code)]
    assert error.source == str(path)


# Rules between fields


def test_span_may_end_at_the_end_of_the_text_unit() -> None:
    document = _document()
    unit = document["text_unit"]
    assert isinstance(unit, str)
    claims = document["claims"]
    assert isinstance(claims, list)
    claims[0]["span"] = [0, len(unit)]
    assert GoldItem.validate_document(document, "item.json").claims[0].span == (0, len(unit))
    claims[0]["span"] = [0, len(unit) + 1]
    assert _problems(document) == [("claims.0.span", "span_out_of_range")]


def test_two_pairs_of_one_claim_need_distinct_ids() -> None:
    document = _document("synthetic_multi_source_item.json")
    claims = document["claims"]
    assert isinstance(claims, list)
    claims[0]["pairs"][1]["pair_id"] = "G9003-c1-s1"
    assert _problems(document) == [("claims.0.pairs.1.pair_id", "duplicate_id")]


def test_three_annotators_are_too_many() -> None:
    document = _document()
    annotation = document["annotation"]
    assert isinstance(annotation, dict)
    annotation["annotators"] = ["a91", "a92", "a93"]
    assert _problems(document) == [("annotation.annotators", "too_long")]


def test_ambiguous_item_is_valid_with_disputed_labels() -> None:
    document = _document()
    annotation = document["annotation"]
    assert isinstance(annotation, dict)
    annotation["ambiguous"] = True
    assert GoldItem.validate_document(document, "item.json").annotation.ambiguous is True


def test_hidden_record_of_a_system_generated_item_is_not_allowed() -> None:
    document = _document()
    document["origin"] = "system_generated"
    assert _problems(document) == [("hidden", "hidden_not_allowed")]


def test_hard_case_is_a_code_or_null() -> None:
    document = _document()
    document["hard_case"] = "Not a code"
    assert _problems(document) == [("hard_case", "string_pattern_mismatch")]


def test_secondary_errors_are_distinct_codes() -> None:
    document = _document()
    hidden = document["hidden"]
    assert isinstance(hidden, dict)
    hidden["secondary_errors"] = ["magnitude_mismatch", "magnitude_mismatch"]
    assert _problems(document) == [("hidden.secondary_errors.1", "duplicate_error")]
