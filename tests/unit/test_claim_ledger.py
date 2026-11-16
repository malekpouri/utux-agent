"""M0-06a: the claim ledger entry schema (RFC-001, section 6)."""

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError
from utux.schemas.claim_ledger import (
    FLAG_SEVERITY,
    AgreementLabel,
    CheckedText,
    ClaimKind,
    ClaimLedgerEntry,
    ClaimStatus,
    ClaimType,
    Confidence,
    ExtractionQuality,
    Reason,
    ScopeFlag,
    Severity,
    SourceLabel,
    load_claim_ledger_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "claim_ledger"
VALID = sorted((FIXTURES / "valid").glob("*.json"))
RFC_001 = (REPO_ROOT / "docs" / "rfc" / "RFC-001.md").read_text(encoding="utf-8")
SPEC = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")

# SHA-256 of b"synthetic fixture content\n", computed with sha256sum.
SYNTHETIC_HASH = "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"

# The fields of RFC-001, section 6, plus schema_version.
LEDGER_FIELDS = [
    "schema_version",
    "id",
    "type",
    "kind",
    "text",
    "span",
    "status",
    "confidence",
    "needs_human",
    "reasons",
    "evidence",
    "verified_by",
    "check_id",
    "trace",
    "claim_hash",
    "checked_at",
    "human",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("missing_status.json", "status", "missing"),
    ("missing_needs_human.json", "needs_human", "missing"),
    ("unknown_key.json", "scope_notes", "unknown_key"),
    ("unknown_status.json", "status", "enum"),
    ("numeric_confidence.json", "confidence", "enum"),
    ("unknown_type.json", "type", "enum"),
    ("unknown_kind.json", "kind", "enum"),
    ("unknown_reason.json", "reasons.1", "enum"),
    ("high_confidence_not_verified.json", "confidence", "confidence_requires_verified"),
    ("verified_literature_without_evidence.json", "evidence", "evidence_required"),
    (
        "literature_with_result_record_evidence.json",
        "evidence.1.evidence_type",
        "evidence_type_mismatch",
    ),
    ("result_with_source_evidence.json", "evidence.0.evidence_type", "evidence_type_mismatch"),
    (
        "derived_with_result_record_evidence.json",
        "evidence.2.evidence_type",
        "evidence_type_mismatch",
    ),
    ("derived_from_itself.json", "evidence.1.id", "self_reference"),
    ("unknown_evidence_type.json", "evidence.0.evidence_type", "enum"),
    ("evidence_without_type.json", "evidence.0.evidence_type", "missing"),
    ("evidence_without_extraction_quality.json", "evidence.0.extraction_quality", "missing"),
    ("unknown_primary_label.json", "evidence.0.primary_label", "enum"),
    ("unknown_secondary_label.json", "evidence.0.secondary_label", "enum"),
    ("unknown_checked_text.json", "evidence.0.checked_text", "enum"),
    ("unknown_extraction_quality.json", "evidence.0.extraction_quality", "enum"),
    ("unknown_scope_flag.json", "evidence.0.scope_flags.0.flag", "enum"),
    ("unknown_severity.json", "evidence.0.scope_flags.0.severity", "enum"),
    (
        "severity_not_the_one_of_the_flag.json",
        "evidence.0.scope_flags.0.severity",
        "severity_mismatch",
    ),
    ("offsets_end_before_start.json", "evidence.0.offsets", "offsets_not_increasing"),
    ("span_end_before_start.json", "span.end", "span_end_not_after_start"),
    ("span_file_outside_project.json", "span.file", "not_relative_path"),
    ("trace_is_absolute_path.json", "trace", "not_relative_path"),
    ("claim_hash_elided.json", "claim_hash", "string_pattern_mismatch"),
    ("claim_id_malformed.json", "id", "string_pattern_mismatch"),
    ("verified_by_without_version.json", "verified_by.0", "string_pattern_mismatch"),
    ("checked_at_without_z.json", "checked_at", "utc_timestamp"),
    ("human_decision_unknown.json", "human.decision", "enum"),
    ("human_reviewer_is_an_agent.json", "human.reviewer", "string_pattern_mismatch"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def _fixture(name: str) -> dict[str, Any]:
    document = json.loads((FIXTURES / "valid" / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _literature(**changes: Any) -> dict[str, Any]:
    """A synthetic literature claim, `partially_supported` with one source entry."""
    return {**_fixture("literature_partially_supported.json"), **changes}


def _verified(**changes: Any) -> dict[str, Any]:
    return {**_fixture("literature_verified.json"), **changes}


def _source_entry(**changes: Any) -> dict[str, Any]:
    entry = copy.deepcopy(_fixture("literature_verified.json")["evidence"][0])
    return {**entry, **changes}


def _validate(document: dict[str, Any]) -> ClaimLedgerEntry:
    return ClaimLedgerEntry.from_json(json.dumps(document), source="claims.jsonl:1")


def _problems(document: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        _validate(document)
    return [(p.field, p.code) for p in caught.value.problems]


def _json_example(document: str, heading: str) -> str:
    section = document.split(heading, 1)[1]
    match = re.search(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert match is not None
    return match.group(1)


# The examples of the documents


def test_rfc_001_example_validates() -> None:
    """The ledger example of RFC-001, section 6, is a valid entry.

    The example elides the claim hash as "sha256:...". That placeholder is
    the one thing replaced here, with a synthetic digest; everything else is
    validated as written in the RFC.
    """
    example = _json_example(RFC_001, "## 6. Claim ledger record")
    assert example.count('"sha256:..."') == 1
    assert sorted(json.loads(example)) == sorted(LEDGER_FIELDS)
    entry = ClaimLedgerEntry.from_json(
        example.replace('"sha256:..."', f'"{SYNTHETIC_HASH}"'), source="docs/rfc/RFC-001.md"
    )
    assert entry.id == "C031"
    assert entry.type is ClaimType.LITERATURE
    assert entry.kind is ClaimKind.FINDING
    assert entry.status is ClaimStatus.PARTIALLY_SUPPORTED
    assert entry.confidence is Confidence.LOW
    assert entry.needs_human is False
    assert entry.reasons == (Reason.OVERGENERALISATION,)
    assert entry.span.file == "literature.md"
    assert (entry.span.start, entry.span.end) == (2140, 2198)
    assert entry.verified_by == ("support_check@1",)
    assert entry.check_id == "k-000218"
    assert entry.trace == "verification/C031/k-000218.json"
    assert entry.checked_at == "2026-11-15T11:02:40Z"
    assert entry.human is None
    (evidence,) = entry.evidence
    assert evidence.evidence_type == "source"
    assert evidence.source_id == "doi:10.0000/example"
    assert evidence.passage_id == "p014"
    assert evidence.offsets == (5321, 5467)
    assert evidence.quote == "A exceeded B by 1.8 points on dataset X"
    assert evidence.checked_text is CheckedText.ABSTRACT
    assert evidence.extraction_quality is ExtractionQuality.CLEAN
    assert evidence.primary_label is SourceLabel.ENTAILS
    assert evidence.secondary_label is SourceLabel.ENTAILS
    (flag,) = evidence.scope_flags
    assert flag.flag is ScopeFlag.OVERGENERALISATION
    assert flag.severity is Severity.MAJOR
    assert flag.claim_slot == "image classification"
    assert flag.evidence_slot == "dataset X"


def test_specification_example_validates() -> None:
    """The ledger example of docs/spec.md, section 7, is a valid entry.

    As above, only the elided "sha256:..." is replaced.
    """
    example = _json_example(SPEC, "### Claim ledger")
    assert example.count('"sha256:..."') == 1
    assert sorted(json.loads(example)) == sorted(LEDGER_FIELDS)
    entry = ClaimLedgerEntry.from_json(
        example.replace('"sha256:..."', f'"{SYNTHETIC_HASH}"'), source="docs/spec.md"
    )
    assert entry.id == "C017"
    assert entry.type is ClaimType.RESULT
    assert entry.status is ClaimStatus.VERIFIED
    assert entry.confidence is Confidence.HIGH
    (evidence,) = entry.evidence
    assert evidence.evidence_type == "result_record"
    assert evidence.id == "R0042"


# Fields


def test_entry_has_exactly_the_fields_of_rfc_001() -> None:
    assert sorted(ClaimLedgerEntry.model_fields) == sorted(LEDGER_FIELDS)


def test_every_field_is_required() -> None:
    for field in LEDGER_FIELDS:
        document = _literature()
        del document[field]
        assert _problems(document) == [(field, "missing")]


@pytest.mark.parametrize("field", ["scope_notes", "used_in", "checked_text"])
def test_fields_dropped_from_the_old_specification_example_are_rejected(field: str) -> None:
    assert _problems(_literature(**{field: None})) == [(field, "unknown_key")]


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    entry = load_claim_ledger_entry(path)
    line = entry.to_json_line()
    again = ClaimLedgerEntry.from_json(line)
    assert again == entry
    assert again.to_json_line() == line
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert json.loads(line) == json.loads(path.read_text(encoding="utf-8"))


def test_there_are_valid_fixtures_for_every_claim_type() -> None:
    types = {load_claim_ledger_entry(path).type for path in VALID}
    assert types == set(ClaimType)


def test_unverified_claim_that_was_never_checked() -> None:
    entry = load_claim_ledger_entry(FIXTURES / "valid" / "unverified_not_yet_checked.json")
    assert entry.status is ClaimStatus.UNVERIFIED
    assert entry.evidence == ()
    assert entry.check_id is None
    assert entry.trace is None
    assert entry.checked_at is None


def test_human_review_is_kept_beside_the_machine_verdict() -> None:
    entry = load_claim_ledger_entry(
        FIXTURES / "valid" / "conflicting_source_reviewed_by_human.json"
    )
    assert entry.human is not None
    assert entry.human.reviewer == "human:alex"
    assert entry.human.decision is ClaimStatus.INSUFFICIENT_EVIDENCE
    assert entry.human.reviewed_at == "2026-11-15T12:30:00Z"
    assert entry.verified_by == ("support_check@1", "human:alex")
    assert entry.needs_human is True


# Closed enumerations, taken from RFC-001


def _first_column(table_heading: str) -> list[str]:
    """Return the back-quoted names in the first column of an RFC-001 table."""
    table = RFC_001.split(table_heading, 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^\| `([a-z_]+)` \|", table, flags=re.MULTILINE)


def test_statuses_are_the_four_scientific_ones_plus_unverified() -> None:
    assert [status.value for status in ClaimStatus] == _first_column("| Status | Use in the")
    assert {status.value for status in ClaimStatus} == {
        "verified",
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
        "unverified",
    }


def test_confidence_is_ordinal_with_three_levels() -> None:
    assert [level.value for level in Confidence] == _first_column("| Level | Conditions |")
    assert {level.value for level in Confidence} == {"high", "medium", "low"}


def test_passage_level_labels_are_the_four_of_rfc_001() -> None:
    assert [label.value for label in AgreementLabel] == _first_column("| Label | Meaning |")
    assert {label.value for label in AgreementLabel} == {
        "entails",
        "partial",
        "neutral",
        "contradicts",
    }


def test_source_level_labels_are_the_four_plus_conflicting() -> None:
    assert {label.value for label in SourceLabel} == {
        *(label.value for label in AgreementLabel),
        "conflicting",
    }


def test_scope_flags_and_their_severities_are_the_table_of_rfc_001() -> None:
    table = RFC_001.split("| Flag | Raised when | Severity |", 1)[1].split("\n\n", 1)[0]
    rows = re.findall(r"^\| `([a-z_]+)` \| .* \| (Critical|Major|Minor) \|$", table, re.MULTILINE)
    assert len(rows) == 7
    assert [flag.value for flag in ScopeFlag] == [name for name, _ in rows]
    assert {flag.value: severity.value for flag, severity in FLAG_SEVERITY.items()} == {
        name: severity.lower() for name, severity in rows
    }
    assert {severity.value for severity in Severity} == {"critical", "major", "minor"}


def test_reasons_are_the_scope_flags_and_the_causes_listed_in_rfc_001() -> None:
    row = re.search(r"^\| `reasons` \| (.*) \|$", RFC_001, flags=re.MULTILINE)
    assert row is not None
    listed = set(re.findall(r"`([a-z_]+)`", row.group(1)))
    assert listed == {
        "no_source",
        "no_text",
        "no_evidence_found",
        "assessor_disagreement",
        "conflict_within_source",
        "conflict_across_sources",
        "citation_not_supporting",
        "second_assessor_unavailable",
    }
    # RFC-001, section 6: "degraded_source_text joins the list of reasons".
    assert "`degraded_source_text` joins the list of reasons" in RFC_001
    expected = {flag.value for flag in ScopeFlag} | listed | {"degraded_source_text"}
    assert {reason.value for reason in Reason} == expected
    assert len(Reason) == 16


def test_claim_types_kinds_checked_text_and_extraction_quality() -> None:
    assert {kind.value for kind in ClaimType} == {"literature", "result", "derived"}
    assert {kind.value for kind in ClaimKind} == {
        "finding",
        "quantitative",
        "method",
        "definition",
        "background",
    }
    assert {text.value for text in CheckedText} == {"abstract", "full_text"}
    assert [q.value for q in ExtractionQuality] == _first_column("| Extraction quality |")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "supported"),
        ("status", "VERIFIED"),
        ("confidence", "very_high"),
        ("confidence", 0.9),
        ("type", "opinion"),
        ("kind", "claim"),
    ],
)
def test_value_outside_a_closed_set_is_rejected(field: str, value: object) -> None:
    assert [name for name, _ in _problems(_literature(**{field: value}))] == [field]


@pytest.mark.parametrize("label", [label.value for label in SourceLabel])
def test_both_labels_accept_every_source_level_label(label: str) -> None:
    document = _literature(evidence=[_source_entry(primary_label=label, secondary_label=label)])
    (evidence,) = _validate(document).evidence
    assert evidence.evidence_type == "source"
    assert evidence.primary_label.value == label
    assert evidence.secondary_label is not None
    assert evidence.secondary_label.value == label


def test_secondary_label_may_be_null_but_primary_may_not() -> None:
    document = _literature(evidence=[_source_entry(secondary_label=None)])
    (evidence,) = _validate(document).evidence
    assert evidence.evidence_type == "source"
    assert evidence.secondary_label is None
    document = _literature(evidence=[_source_entry(primary_label=None)])
    assert [field for field, _ in _problems(document)] == ["evidence.0.primary_label"]


# Confidence and status


@pytest.mark.parametrize("confidence", ["high", "medium"])
@pytest.mark.parametrize(
    "status", ["partially_supported", "contradicted", "insufficient_evidence", "unverified"]
)
def test_high_and_medium_confidence_require_verified(confidence: str, status: str) -> None:
    document = _literature(status=status, confidence=confidence)
    assert _problems(document) == [("confidence", "confidence_requires_verified")]


@pytest.mark.parametrize("claim", ["literature_verified.json", "result_verified.json"])
@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_verified_claim_may_have_any_confidence(claim: str, confidence: str) -> None:
    document = {**_fixture(claim), "confidence": confidence}
    assert _validate(document).confidence.value == confidence


@pytest.mark.parametrize(
    "status", ["partially_supported", "contradicted", "insufficient_evidence", "unverified"]
)
def test_low_confidence_goes_with_every_status(status: str) -> None:
    assert _validate(_literature(status=status, confidence="low")).status.value == status


# Evidence


def test_verified_literature_claim_needs_evidence() -> None:
    assert _problems(_verified(evidence=[])) == [("evidence", "evidence_required")]


@pytest.mark.parametrize("fixture", ["result_verified.json", "derived_verified.json"])
def test_verified_result_and_derived_claims_need_evidence_too(fixture: str) -> None:
    document = {**_fixture(fixture), "evidence": []}
    assert _problems(document) == [("evidence", "evidence_required")]


def test_claim_that_is_not_verified_may_have_no_evidence() -> None:
    document = _literature(status="insufficient_evidence", reasons=["no_text"], evidence=[])
    assert _validate(document).evidence == ()


RESULT_ENTRY = {"evidence_type": "result_record", "id": "R0042"}
CLAIM_ENTRY = {"evidence_type": "claim", "id": "C017"}


@pytest.mark.parametrize(
    ("fixture", "wrong"),
    [
        ("literature_verified.json", RESULT_ENTRY),
        ("literature_verified.json", CLAIM_ENTRY),
        ("result_verified.json", CLAIM_ENTRY),
        ("result_verified.json", None),  # a source entry
        ("derived_verified.json", RESULT_ENTRY),
        ("derived_verified.json", None),
    ],
)
def test_each_claim_type_takes_only_its_own_evidence(
    fixture: str, wrong: dict[str, str] | None
) -> None:
    document = _fixture(fixture)
    right = document["evidence"][0]
    other = wrong if wrong is not None else _source_entry()
    # One problem per offending entry, on its own position.
    document["evidence"] = [other, right, other]
    assert _problems(document) == [
        ("evidence.0.evidence_type", "evidence_type_mismatch"),
        ("evidence.2.evidence_type", "evidence_type_mismatch"),
    ]


def test_evidence_type_mismatch_reason_names_both_types() -> None:
    document = {**_fixture("result_verified.json"), "evidence": [_source_entry()]}
    with pytest.raises(ContractValidationError) as caught:
        _validate(document)
    reason = caught.value.problems[0].reason
    assert "result" in reason
    assert "result_record" in reason


@pytest.mark.parametrize("value", ["rumour", "", None, 3])
def test_unknown_evidence_type_is_rejected(value: object) -> None:
    document = _literature(evidence=[_source_entry(evidence_type=value)])
    assert [field for field, _ in _problems(document)] == ["evidence.0.evidence_type"]


def test_problem_inside_an_evidence_entry_is_reported_on_its_exact_path() -> None:
    document = _literature(
        evidence=[_source_entry(), _source_entry(quote="", checked_text="summary")]
    )
    assert sorted(_problems(document)) == [
        ("evidence.1.checked_text", "enum"),
        ("evidence.1.quote", "string_too_short"),
    ]


def test_evidence_entry_rejects_keys_of_another_entry_type() -> None:
    document = {
        **_fixture("result_verified.json"),
        "evidence": [{"evidence_type": "result_record", "id": "R0042", "quote": "text"}],
    }
    assert _problems(document) == [("evidence.0.quote", "unknown_key")]


@pytest.mark.parametrize("identifier", ["C017", "42", "r0042", "R42x"])
def test_result_record_evidence_needs_a_result_id(identifier: str) -> None:
    document = {
        **_fixture("result_verified.json"),
        "evidence": [{"evidence_type": "result_record", "id": identifier}],
    }
    assert _problems(document) == [("evidence.0.id", "string_pattern_mismatch")]


def test_derived_claim_cannot_follow_from_itself() -> None:
    document = _fixture("derived_verified.json")
    document["evidence"] = [
        {"evidence_type": "claim", "id": "C040"},
        {"evidence_type": "claim", "id": "C017"},
        {"evidence_type": "claim", "id": "C040"},
    ]
    assert _problems(document) == [
        ("evidence.0.id", "self_reference"),
        ("evidence.2.id", "self_reference"),
    ]


def test_scope_flag_severity_must_be_the_one_rfc_001_gives_the_flag() -> None:
    for flag, severity in FLAG_SEVERITY.items():
        for candidate in Severity:
            entry = _source_entry(
                scope_flags=[
                    {
                        "flag": flag.value,
                        "severity": candidate.value,
                        "claim_slot": "synthetic claim slot",
                        "evidence_slot": "synthetic evidence slot",
                    }
                ]
            )
            document = _literature(evidence=[entry])
            if candidate is severity:
                _validate(document)
            else:
                assert _problems(document) == [
                    ("evidence.0.scope_flags.0.severity", "severity_mismatch")
                ]


@pytest.mark.parametrize("offsets", [[10, 10], [10, 5], [-1, 5], [1], [1, 2, 3], [1.5, 2]])
def test_offsets_are_a_start_and_a_later_end(offsets: list[float]) -> None:
    document = _literature(evidence=[_source_entry(offsets=offsets)])
    fields = {
        field.rsplit(".", 1)[0] if field[-1].isdigit() else field
        for field, _ in _problems(document)
    }
    assert fields == {"evidence.0.offsets"}


# Span, paths and identifiers


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.md", "a/../../b.md", "a\\b.md", "", "a//b.md", "./a.md", "a/"],
)
@pytest.mark.parametrize("field", ["trace", "span.file"])
def test_paths_stay_inside_the_project(field: str, path: str) -> None:
    document = _literature()
    if field == "trace":
        document["trace"] = path
    else:
        document["span"] = {"file": path, "start": 1, "end": 2}
    assert _problems(document) == [(field, "not_relative_path")]


def test_span_end_comes_after_start() -> None:
    document = _literature(span={"file": "literature.md", "start": 5, "end": 5})
    assert _problems(document) == [("span.end", "span_end_not_after_start")]


@pytest.mark.parametrize("value", ["c031", "C31", "C0031x", "31", "R0042"])
def test_claim_id_is_c_and_at_least_three_digits(value: str) -> None:
    assert _problems(_literature(id=value)) == [("id", "string_pattern_mismatch")]


@pytest.mark.parametrize(
    "value", ["support_check@1", "numeric_check@12", "human:alex", "human:a.b-c_1"]
)
def test_verified_by_is_a_versioned_check_or_a_person(value: str) -> None:
    assert _validate(_literature(verified_by=[value])).verified_by == (value,)


@pytest.mark.parametrize(
    "value", ["support_check", "support_check@", "Support@1", "agent:x", "@1", "human:"]
)
def test_verified_by_rejects_other_forms(value: str) -> None:
    assert _problems(_literature(verified_by=[value])) == [
        ("verified_by.0", "string_pattern_mismatch")
    ]


@pytest.mark.parametrize("value", ["218", "k-218", "K-000218", "e-000218"])
def test_check_id_is_k_and_at_least_six_digits(value: str) -> None:
    assert _problems(_literature(check_id=value)) == [("check_id", "string_pattern_mismatch")]


# Invalid fixtures


def test_at_least_five_invalid_fixtures_with_distinct_reasons() -> None:
    reasons = [(field, code) for _, field, code in INVALID]
    assert len(INVALID) >= 5
    assert len(set(reasons)) == len(reasons)


def test_every_invalid_fixture_is_listed() -> None:
    on_disk = sorted(path.name for path in (FIXTURES / "invalid").glob("*.json"))
    assert on_disk == sorted(name for name, _, _ in INVALID)


@pytest.mark.parametrize(("name", "field", "code"), INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(name: str, field: str, code: str) -> None:
    path = FIXTURES / "invalid" / name
    with pytest.raises(ContractValidationError) as caught:
        load_claim_ledger_entry(path)
    error = caught.value
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    assert error.source == str(path)
    assert str(error) == f"{path}: {field}: {error.problems[0].reason}"
