"""M0-06b: the approval request and approval response schemas."""

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

from utux.errors import ContractValidationError
from utux.schemas.approval import (
    ApprovalRequest,
    ApprovalResponse,
    Decision,
    check_response_matches_request,
    load_approval_request,
    load_approval_response,
)
from utux.schemas.project_config import Gate

REQUEST = "approval_request"
RESPONSE = "approval_response"

REQUEST_FIELDS = [
    "schema_version",
    "approval_id",
    "gate",
    "artifact_id",
    "content_hash",
    "path",
    "requested_by",
    "requested_at",
]

RESPONSE_FIELDS = [
    "schema_version",
    "approval_id",
    "artifact_id",
    "content_hash",
    "decision",
    "answered_by",
    "answered_at",
    "feedback",
    "edited_content",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated within a table.
INVALID_REQUESTS: list[Row] = [
    ("missing_content_hash.json", "content_hash", "missing"),
    ("missing_artifact_id.json", "artifact_id", "missing"),
    ("unknown_key.json", "summary", "unknown_key"),
    ("unknown_gate.json", "gate", "enum"),
    ("approval_id_malformed.json", "approval_id", "string_pattern_mismatch"),
    ("artifact_id_without_version.json", "artifact_id", "string_pattern_mismatch"),
    ("content_hash_elided.json", "content_hash", "string_pattern_mismatch"),
    ("path_outside_project.json", "path", "not_relative_path"),
    ("requested_by_without_kind.json", "requested_by", "string_pattern_mismatch"),
    ("requested_at_without_z.json", "requested_at", "utc_timestamp"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]

INVALID_RESPONSES: list[Row] = [
    ("missing_content_hash.json", "content_hash", "missing"),
    ("missing_edited_content.json", "edited_content", "missing"),
    ("unknown_key.json", "mood", "unknown_key"),
    ("unknown_decision.json", "decision", "enum"),
    ("answered_by_an_agent.json", "answered_by", "string_pattern_mismatch"),
    ("content_hash_elided.json", "content_hash", "string_pattern_mismatch"),
    ("approval_id_malformed.json", "approval_id", "string_pattern_mismatch"),
    ("answered_at_without_z.json", "answered_at", "utc_timestamp"),
    ("reject_without_feedback.json", "feedback", "feedback_required"),
    ("edit_without_edited_content.json", "edited_content", "edited_content_required"),
    ("approve_with_edited_content.json", "edited_content", "edited_content_not_allowed"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]

OTHER_HASH = "sha256:" + "0" * 64


def _request(**changes: Any) -> ApprovalRequest:
    document = {**read_valid(REQUEST, "method_gate.json"), **changes}
    return ApprovalRequest.from_json(json.dumps(document))


def _response_document(**changes: Any) -> dict[str, Any]:
    return {**read_valid(RESPONSE, "approve.json"), **changes}


def _response(**changes: Any) -> ApprovalResponse:
    return ApprovalResponse.from_json(json.dumps(_response_document(**changes)))


# Request


def test_request_has_the_proposed_fields() -> None:
    assert sorted(ApprovalRequest.model_fields) == sorted(REQUEST_FIELDS)


def test_request_names_the_exact_version_to_approve() -> None:
    request = load_approval_request(valid_paths(REQUEST)[1])
    assert request.approval_id == "a-000007"
    assert request.gate is Gate.METHOD
    assert request.artifact_id == "method-v003"
    assert request.content_hash.startswith("sha256:")
    assert request.path == "method.md"
    assert request.requested_by == "agent:methodologist"
    assert request.requested_at == "2026-11-15T10:05:00Z"


def test_every_request_field_is_required() -> None:
    for field in REQUEST_FIELDS:
        document = read_valid(REQUEST, "method_gate.json")
        del document[field]
        assert problems(ApprovalRequest, document) == [(field, "missing")]


def test_request_gate_is_one_of_the_four_gates() -> None:
    for gate in Gate:
        assert _request(gate=gate.value).gate is gate


# Response


def test_response_has_the_proposed_fields() -> None:
    assert sorted(ApprovalResponse.model_fields) == sorted(RESPONSE_FIELDS)


def test_response_repeats_artifact_id_and_content_hash() -> None:
    response = load_approval_response(valid_paths(RESPONSE)[0])
    assert response.approval_id == "a-000007"
    assert response.artifact_id == "method-v003"
    assert response.content_hash.startswith("sha256:")
    assert response.decision is Decision.APPROVE
    assert response.answered_by == "human:alex"
    assert response.feedback is None
    assert response.edited_content is None


def test_every_response_field_is_required() -> None:
    for field in RESPONSE_FIELDS:
        document = _response_document()
        del document[field]
        assert problems(ApprovalResponse, document) == [(field, "missing")]


def test_decisions_are_approve_reject_and_edit() -> None:
    assert {decision.value for decision in Decision} == {"approve", "reject", "edit"}


def test_reject_needs_feedback() -> None:
    assert problems(ApprovalResponse, _response_document(decision="reject")) == [
        ("feedback", "feedback_required")
    ]
    assert _response(decision="reject", feedback="Synthetic feedback.").feedback is not None


def test_feedback_is_optional_for_approve_and_edit() -> None:
    assert _response(feedback="Synthetic remark.").feedback == "Synthetic remark."
    edited = _response(decision="edit", edited_content="new text", feedback="Synthetic remark.")
    assert edited.feedback == "Synthetic remark."


def test_edit_carries_the_edited_content_and_other_decisions_do_not() -> None:
    assert problems(ApprovalResponse, _response_document(decision="edit")) == [
        ("edited_content", "edited_content_required")
    ]
    for decision in ("approve", "reject"):
        document = _response_document(
            decision=decision, feedback="Synthetic feedback.", edited_content="text"
        )
        assert problems(ApprovalResponse, document) == [
            ("edited_content", "edited_content_not_allowed")
        ]
    assert _response(decision="edit", edited_content="a\nb\n").edited_content == "a\nb\n"


@pytest.mark.parametrize("who", ["agent:planner", "system:utux", "alex", "human:"])
def test_only_a_person_answers_an_approval(who: str) -> None:
    assert problems(ApprovalResponse, _response_document(answered_by=who)) == [
        ("answered_by", "string_pattern_mismatch")
    ]


# An approval binds to one exact version


def test_matching_response_is_accepted() -> None:
    check_response_matches_request(_request(), _response(), "approvals/a-000007.response.json")


def test_response_for_an_edited_file_does_not_carry_over() -> None:
    """The file changed after the request, so its hash differs: the approval does not apply."""
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(
            _request(content_hash=OTHER_HASH), _response(), "approvals/a-000007.response.json"
        )
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("content_hash", "differs_from_request")
    ]
    assert caught.value.source == "approvals/a-000007.response.json"


def test_response_for_another_version_or_request_is_refused() -> None:
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(
            _request(),
            _response(approval_id="a-000008", artifact_id="method-v004", content_hash=OTHER_HASH),
            "response.json",
        )
    # Every difference is reported, each on its own field.
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("approval_id", "differs_from_request"),
        ("artifact_id", "differs_from_request"),
        ("content_hash", "differs_from_request"),
    ]


# Fixtures


@pytest.mark.parametrize("path", valid_paths(REQUEST), ids=lambda p: p.name)
def test_request_round_trip(path: Path) -> None:
    check_round_trip(ApprovalRequest, load_approval_request, path)


@pytest.mark.parametrize("path", valid_paths(RESPONSE), ids=lambda p: p.name)
def test_response_round_trip(path: Path) -> None:
    check_round_trip(ApprovalResponse, load_approval_response, path)


def test_valid_response_fixtures_match_the_valid_request() -> None:
    request = load_approval_request(valid_paths(REQUEST)[1])
    for path in valid_paths(RESPONSE):
        check_response_matches_request(request, load_approval_response(path), str(path))


def test_invalid_fixture_tables() -> None:
    check_table(REQUEST, INVALID_REQUESTS)
    check_table(RESPONSE, INVALID_RESPONSES)


@pytest.mark.parametrize("row", INVALID_REQUESTS, ids=[row[0] for row in INVALID_REQUESTS])
def test_invalid_request_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(REQUEST, load_approval_request, row)


@pytest.mark.parametrize("row", INVALID_RESPONSES, ids=[row[0] for row in INVALID_RESPONSES])
def test_invalid_response_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(RESPONSE, load_approval_response, row)
