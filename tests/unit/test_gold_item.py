"""M0-13a: the gold item schema (RFC-002, section 4).

Every fixture is synthetic; see `tests/fixtures/gold_item/README.md`. The
labels in them exercise the schema and are not annotation.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError
from utux.evalkit.gold import (
    Domain,
    ErrorClass,
    GenerationRecord,
    GoldItem,
    GoldSplit,
    GoldStatus,
    HardCase,
    Origin,
    PerturbationRecord,
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
    ("synthetic_unknown_hard_case.json", "hard_case", "enum"),
    ("synthetic_item_id_malformed.json", "item_id", "string_pattern_mismatch"),
    ("synthetic_gold_version_malformed.json", "gold_version", "string_pattern_mismatch"),
    ("synthetic_missing_text_unit.json", "text_unit", "missing"),
    ("synthetic_unknown_key.json", "note", "unknown_key"),
    ("synthetic_no_claims.json", "claims", "too_short"),
    ("synthetic_status_unverified.json", "claims.0.status", "enum"),
    ("synthetic_unknown_kind.json", "claims.0.kind", "enum"),
    ("synthetic_expert_would_review_not_boolean.json", "claims.0.expert_would_review", "bool_type"),
    ("synthetic_ambiguous_not_boolean.json", "claims.0.ambiguous", "bool_type"),
    ("synthetic_claim_id_of_another_item.json", "claims.0.claim_id", "claim_id_mismatch"),
    ("synthetic_claim_without_pairs.json", "claims.0.pairs", "too_short"),
    ("synthetic_claim_without_pairs_not_insufficient.json", "claims.1.pairs", "too_short"),
    (
        "synthetic_raw_status_of_a_claim_without_pairs.json",
        "claims.1.raw.a92.status",
        "raw_status_without_pairs",
    ),
    (
        "synthetic_claim_adjudicated_without_reason.json",
        "claims.0.adjudication_reason",
        "adjudication_reason_required",
    ),
    (
        "synthetic_pair_reason_without_adjudication.json",
        "claims.0.pairs.0.adjudication_reason",
        "adjudication_reason_not_allowed",
    ),
    (
        "synthetic_extraction_adjudicated_without_reason.json",
        "annotation.claim_extraction.adjudication_reason",
        "adjudication_reason_required",
    ),
    ("synthetic_empty_claim_note.json", "claims.0.raw.a91.note", "string_too_short"),
    ("synthetic_pair_raw_without_note.json", "claims.0.pairs.0.raw.a91.note", "missing"),
    (
        "synthetic_extracted_claim_without_citations.json",
        "annotation.claim_extraction.raw.a91.0.citations",
        "missing",
    ),
    (
        "synthetic_duplicate_citation.json",
        "annotation.claim_extraction.raw.a91.0.citations.1",
        "duplicate_citation",
    ),
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
    ("synthetic_annotator_id_is_a_name.json", "annotation.annotators.0", "string_pattern_mismatch"),
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
    (
        "synthetic_extraction_raw_missing_an_annotator.json",
        "annotation.claim_extraction.raw.a92",
        "missing",
    ),
    (
        "synthetic_extracted_span_beyond_text_unit.json",
        "annotation.claim_extraction.raw.a91.0.span",
        "span_out_of_range",
    ),
    (
        "synthetic_extraction_disagreement_not_adjudicated.json",
        "annotation.claim_extraction.adjudicated",
        "adjudication_required",
    ),
    ("synthetic_claims_differ_from_agreed_extraction.json", "claims", "differs_from_raw"),
    ("synthetic_claim_raw_missing_an_annotator.json", "claims.0.raw.a92", "missing"),
    ("synthetic_unknown_raw_status.json", "claims.0.raw.a91.status", "enum"),
    (
        "synthetic_claim_disagreement_not_adjudicated.json",
        "claims.0.adjudicated",
        "adjudication_required",
    ),
    ("synthetic_status_differs_from_agreed_raw.json", "claims.0.status", "differs_from_raw"),
    (
        "synthetic_pair_raw_of_another_annotator.json",
        "claims.0.pairs.0.raw.a99",
        "unknown_annotator",
    ),
    (
        "synthetic_pair_disagreement_not_adjudicated.json",
        "claims.0.pairs.0.adjudicated",
        "adjudication_required",
    ),
    (
        "synthetic_scope_flags_differ_from_agreed_raw.json",
        "claims.0.pairs.0.scope_flags",
        "differs_from_raw",
    ),
    ("synthetic_perturbed_without_hidden.json", "hidden", "hidden_required"),
    ("synthetic_natural_with_hidden.json", "hidden", "hidden_not_allowed"),
    ("synthetic_perturbed_from_itself.json", "hidden.source_item", "self_reference"),
    ("synthetic_unknown_error_class.json", "hidden.error_class", "enum"),
    ("synthetic_confirmed_by_a_name.json", "hidden.confirmed_by", "string_pattern_mismatch"),
    ("synthetic_generated_by_not_a_code.json", "hidden.generated_by", "string_pattern_mismatch"),
    ("synthetic_malformed_json.json", "<document>", "invalid_json"),
    ("synthetic_not_an_object.json", "<document>", "not_a_mapping"),
    ("synthetic_newer_schema_version.json", "schema_version", "schema_version_newer"),
]


def _document(name: str = "synthetic_perturbed_item.json") -> dict[str, Any]:
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
    assert claim.raw["a91"].status is GoldStatus.PARTIALLY_SUPPORTED
    assert claim.raw["a92"].status is GoldStatus.VERIFIED
    assert claim.adjudicated is True
    assert claim.ambiguous is False
    (pair,) = claim.pairs
    assert pair.pair_id == "G9001-c1-s1"
    assert pair.source_group == "sg-synthetic-b"
    assert pair.evidence_spans[0].offsets == (10, 60)
    assert pair.raw["a92"].scope_flags == ()
    assert pair.adjudicated is True
    annotation = item.annotation
    assert annotation.annotators == ("a91", "a92")
    assert annotation.adjudicator == "a90"
    assert len(annotation.claim_extraction.raw["a91"]) == 1
    assert len(annotation.claim_extraction.raw["a92"]) == 2
    assert annotation.claim_extraction.adjudicated is True
    assert isinstance(item.hidden, PerturbationRecord)
    assert item.hidden.source_item == "G9000"
    assert item.hidden.error_class is ErrorClass.SINGLE_ERROR


def test_multi_source_item_has_one_pair_per_source_and_an_ambiguous_claim() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_multi_source_item.json")
    first, second = item.claims
    assert [pair.pair_id for pair in first.pairs] == ["G9003-c1-s1", "G9003-c1-s2"]
    assert [pair.source_group for pair in first.pairs] == ["sg-synthetic-c", "sg-synthetic-d"]
    assert first.ambiguous is False
    assert second.ambiguous is True
    assert item.domain is Domain.BIOMEDICINE
    assert item.origin is Origin.SYSTEM_GENERATED
    assert item.hidden == GenerationRecord(generated_by="synthetic-system-config-1")


def test_natural_item_without_disagreement_needs_no_adjudicator_and_has_no_hidden() -> None:
    path = FIXTURES / "valid" / "synthetic_natural_item.json"
    item = load_gold_item(path)
    assert item.annotation.adjudicator is None
    assert item.hard_case is HardCase.ABSTRACT_VS_FULL_TEXT
    assert item.hidden is None
    assert "hidden" not in json.loads(path.read_text(encoding="utf-8"))
    assert "hidden" not in json.loads(item.to_json_line())


def test_reference_statuses_are_the_four_scientific_statuses() -> None:
    # RFC-002, section 3: unverified is never a reference label.
    assert [status.value for status in GoldStatus] == [
        "verified",
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
    ]


def test_hard_case_codes_are_those_of_rfc_002_section_3() -> None:
    assert [code.value for code in HardCase] == [
        "abstract_vs_full_text",
        "number_wrong_context",
        "conflict_within_source",
        "true_but_not_in_source",
        "attributed_prior_work",
        "heavy_paraphrase",
        "negation_or_hedge",
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


def _claim(document: dict[str, Any], index: int = 0) -> dict[str, Any]:
    claims = document["claims"]
    assert isinstance(claims, list)
    claim = claims[index]
    assert isinstance(claim, dict)
    return claim


def _annotation(document: dict[str, Any]) -> dict[str, Any]:
    annotation = document["annotation"]
    assert isinstance(annotation, dict)
    return annotation


def test_span_may_end_at_the_end_of_the_text_unit() -> None:
    document = _document()
    unit = document["text_unit"]
    assert isinstance(unit, str)
    _claim(document)["span"] = [0, len(unit)]
    assert GoldItem.validate_document(document, "item.json").claims[0].span == (0, len(unit))
    _claim(document)["span"] = [0, len(unit) + 1]
    assert _problems(document) == [("claims.0.span", "span_out_of_range")]


def test_two_pairs_of_one_claim_need_distinct_ids() -> None:
    document = _document("synthetic_multi_source_item.json")
    _claim(document)["pairs"][1]["pair_id"] = "G9003-c1-s1"
    assert _problems(document) == [("claims.0.pairs.1.pair_id", "duplicate_id")]


def test_three_annotators_are_too_many() -> None:
    document = _document()
    _annotation(document)["annotators"] = ["a91", "a92", "a93"]
    assert _problems(document) == [("annotation.annotators", "too_long")]


def test_adjudicated_may_be_true_where_the_raw_entries_agree() -> None:
    document = _document("synthetic_natural_item.json")
    _claim(document)["adjudicated"] = True
    _claim(document)["adjudication_reason"] = "Synthetic adjudication reason."
    _annotation(document)["adjudicator"] = "a90"
    assert GoldItem.validate_document(document, "item.json").claims[0].adjudicated is True


def test_adjudicated_values_may_differ_from_both_raw_entries() -> None:
    # The adjudicator sets the reference value; it need not be either raw one.
    document = _document()
    _claim(document)["status"] = "contradicted"
    assert GoldItem.validate_document(document, "item.json").claims[0].status is (
        GoldStatus.CONTRADICTED
    )


def test_pair_raw_entries_are_compared_as_sets() -> None:
    document = _document("synthetic_multi_source_item.json")
    pair = _claim(document)["pairs"][1]
    pair["scope_flags"] = ["magnitude_mismatch", "direction_mismatch"]
    pair["raw"]["a91"]["scope_flags"] = ["direction_mismatch", "magnitude_mismatch"]
    pair["raw"]["a92"]["scope_flags"] = ["magnitude_mismatch", "direction_mismatch"]
    for entry in (pair, pair["raw"]["a91"], pair["raw"]["a92"]):
        entry["evidence_spans"] = [
            {"passage_id": "p001", "offsets": [1, 5]},
            {"passage_id": "p002", "offsets": [7, 9]},
        ]
    pair["raw"]["a92"]["evidence_spans"].reverse()
    item = GoldItem.validate_document(document, "item.json")
    assert item.claims[0].pairs[1].adjudicated is False


def test_claim_lists_are_compared_as_sets() -> None:
    document = _document("synthetic_multi_source_item.json")
    _annotation(document)["claim_extraction"]["raw"]["a92"].reverse()
    item = GoldItem.validate_document(document, "item.json")
    assert item.annotation.claim_extraction.adjudicated is False


def test_review_flag_differing_from_agreed_raw_entries() -> None:
    document = _document("synthetic_natural_item.json")
    _claim(document)["expert_would_review"] = True
    assert _problems(document) == [("claims.0.expert_would_review", "differs_from_raw")]


def test_ambiguous_claim_is_valid_with_disputed_labels() -> None:
    document = _document()
    _claim(document)["ambiguous"] = True
    assert GoldItem.validate_document(document, "item.json").claims[0].ambiguous is True


def test_natural_item_with_a_null_hidden_record_is_rejected() -> None:
    # The record is absent for a natural item, not null.
    document = _document("synthetic_natural_item.json")
    document["hidden"] = None
    assert _problems(document) == [("hidden", "hidden_not_allowed")]


def test_system_generated_item_needs_generated_by() -> None:
    document = _document("synthetic_multi_source_item.json")
    del document["hidden"]
    assert _problems(document) == [("hidden", "hidden_required")]


def test_system_generated_item_takes_no_perturbation_record() -> None:
    document = _document("synthetic_multi_source_item.json")
    perturbed = _document()
    document["hidden"] = perturbed["hidden"]
    problems = _problems(document)
    assert ("hidden.generated_by", "missing") in problems
    assert ("hidden.source_item", "unknown_key") in problems


def test_hard_case_is_a_code_or_null() -> None:
    document = _document()
    document["hard_case"] = "negation_or_hedge"
    assert GoldItem.validate_document(document, "item.json").hard_case is (
        HardCase.NEGATION_OR_HEDGE
    )


def test_secondary_errors_are_distinct_codes() -> None:
    document = _document()
    hidden = document["hidden"]
    assert isinstance(hidden, dict)
    hidden["secondary_errors"] = ["magnitude_mismatch", "magnitude_mismatch"]
    assert _problems(document) == [("hidden.secondary_errors.1", "duplicate_error")]


def test_a_claim_that_cites_no_source_has_no_pairs() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_claim_without_a_source.json")
    claim = item.claims[1]
    assert claim.pairs == ()
    assert claim.status is GoldStatus.INSUFFICIENT_EVIDENCE
    assert {raw.status for raw in claim.raw.values()} == {GoldStatus.INSUFFICIENT_EVIDENCE}


def test_notes_and_adjudication_reasons_are_read() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_perturbed_item.json")
    claim = item.claims[0]
    assert claim.adjudication_reason == "Synthetic adjudication reason."
    assert claim.raw["a91"].note is None
    assert claim.pairs[0].raw["a92"].note == "Synthetic note."
    assert claim.pairs[0].adjudication_reason == "Synthetic adjudication reason."
    extraction = item.annotation.claim_extraction
    assert extraction.adjudication_reason == "Synthetic adjudication reason."


def test_a_claim_without_pairs_may_be_adjudicated_on_its_review_flag() -> None:
    document = _document("synthetic_claim_without_a_source.json")
    claim = _claim(document, 1)
    claim["raw"]["a92"]["expert_would_review"] = True
    claim["adjudicated"] = True
    claim["adjudication_reason"] = "Synthetic adjudication reason."
    _annotation(document)["adjudicator"] = "a90"
    assert GoldItem.validate_document(document, "item.json").claims[1].pairs == ()


def test_extracted_claims_carry_their_citations() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_multi_source_item.json")
    first, second = item.annotation.claim_extraction.raw["a91"]
    assert first.citations == ("synthetic:sg-synthetic-c-paper", "synthetic:sg-synthetic-d-paper")
    assert second.citations == ("synthetic:sg-synthetic-c-paper",)


def test_a_claim_without_a_source_is_extracted_without_citations() -> None:
    item = load_gold_item(FIXTURES / "valid" / "synthetic_claim_without_a_source.json")
    assert item.annotation.claim_extraction.raw["a91"][1].citations == ()


def test_agreed_extraction_must_match_the_reference_citations() -> None:
    # Both annotators list the claim with another source than its pair cites,
    # and nothing was adjudicated: the reference claims differ from the list.
    document = _document("synthetic_natural_item.json")
    for listed in _annotation(document)["claim_extraction"]["raw"].values():
        listed[0]["citations"] = ["synthetic:another-paper"]
    assert _problems(document) == [("claims", "differs_from_raw")]


def test_extraction_lists_that_differ_only_in_citations_need_adjudication() -> None:
    document = _document("synthetic_natural_item.json")
    _annotation(document)["claim_extraction"]["raw"]["a92"][0]["citations"] = [
        "synthetic:another-paper"
    ]
    assert _problems(document) == [
        ("annotation.claim_extraction.adjudicated", "adjudication_required")
    ]


def test_citations_are_compared_as_sets() -> None:
    document = _document("synthetic_multi_source_item.json")
    _annotation(document)["claim_extraction"]["raw"]["a92"][0]["citations"].reverse()
    item = GoldItem.validate_document(document, "item.json")
    assert item.annotation.claim_extraction.adjudicated is False


# PR #48 review: the split may wait for the freeze, and each annotator's kind is kept


def test_an_item_may_have_no_split_until_the_release_is_frozen() -> None:
    document = _document("synthetic_natural_item.json")
    document["split"] = None
    assert GoldItem.validate_document(document, "item.json").split is None


def test_a_listed_claim_has_the_annotators_kind() -> None:
    document = _document("synthetic_natural_item.json")
    del _annotation(document)["claim_extraction"]["raw"]["a91"][0]["kind"]
    assert ("annotation.claim_extraction.raw.a91.0.kind", "missing") in _problems(document)


def test_a_kind_both_annotators_gave_is_the_reference_kind_unless_adjudicated() -> None:
    document = _document("synthetic_natural_item.json")
    for listed in _annotation(document)["claim_extraction"]["raw"].values():
        listed[0]["kind"] = "background"
    assert ("annotation.claim_extraction", "differs_from_raw") in _problems(document)
