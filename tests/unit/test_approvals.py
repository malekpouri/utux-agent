"""M0-06b: the approval request and approval response schemas."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from contract_checks import (
    FIXTURES_ROOT,
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
    ApprovalKind,
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
    "kind",
    "gate",
    "artifact_id",
    "content_hash",
    "path",
    "stage",
    "refused_event_id",
    "execution",
    "requested_by",
    "requested_at",
]

RESPONSE_FIELDS = [
    "schema_version",
    "approval_id",
    "kind",
    "artifact_id",
    "content_hash",
    "decision",
    "answered_by",
    "answered_at",
    "feedback",
    "edited_artifact_id",
    "edited_content_hash",
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
    ("missing_kind.json", "kind", "missing"),
    ("unknown_kind.json", "kind", "enum"),
    ("artifact_kind_without_gate.json", "gate", "required_for_kind"),
    ("artifact_kind_with_refused_event_id.json", "refused_event_id", "not_allowed_for_kind"),
    ("budget_exhausted_with_artifact_id.json", "artifact_id", "not_allowed_for_kind"),
    ("budget_exhausted_without_stage.json", "stage", "required_for_kind"),
    ("refused_event_id_malformed.json", "refused_event_id", "string_pattern_mismatch"),
    ("experiment_plan_without_execution.json", "execution", "required_for_gate"),
    ("method_gate_with_execution.json", "execution", "not_allowed_for_gate"),
]

INVALID_RESPONSES: list[Row] = [
    ("missing_content_hash.json", "content_hash", "missing"),
    ("missing_edited_artifact_id.json", "edited_artifact_id", "missing"),
    ("unknown_key.json", "mood", "unknown_key"),
    ("unknown_decision.json", "decision", "enum"),
    ("answered_by_an_agent.json", "answered_by", "string_pattern_mismatch"),
    ("content_hash_elided.json", "content_hash", "string_pattern_mismatch"),
    ("approval_id_malformed.json", "approval_id", "string_pattern_mismatch"),
    ("answered_at_without_z.json", "answered_at", "utc_timestamp"),
    ("reject_without_feedback.json", "feedback", "feedback_required"),
    ("edit_without_edited_artifact_id.json", "edited_artifact_id", "required_for_edit"),
    ("edit_without_edited_content_hash.json", "edited_content_hash", "required_for_edit"),
    ("approve_with_edited_artifact_id.json", "edited_artifact_id", "not_allowed_unless_edit"),
    ("reject_with_edited_content_hash.json", "edited_content_hash", "not_allowed_unless_edit"),
    ("edited_artifact_id_without_version.json", "edited_artifact_id", "string_pattern_mismatch"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
    ("missing_kind.json", "kind", "missing"),
    ("edit_for_budget_exhausted.json", "decision", "edit_not_allowed_for_kind"),
    ("retry_limit_with_content_hash.json", "content_hash", "not_allowed_for_kind"),
    ("artifact_kind_without_artifact_id.json", "artifact_id", "required_for_kind"),
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
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / "method_gate.json")
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
    plan = read_valid(REQUEST, "experiment_plan_gate.json")["execution"]
    for gate in Gate:
        # Only an experiment-plan request records an execution.
        execution = plan if gate is Gate.EXPERIMENT_PLAN else None
        assert _request(gate=gate.value, execution=execution).gate is gate


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
    assert response.edited_artifact_id is None
    assert response.edited_content_hash is None


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


EDITED = {"edited_artifact_id": "method-v004", "edited_content_hash": "sha256:" + "ab" * 32}


def test_feedback_is_optional_for_approve_and_edit() -> None:
    assert _response(feedback="Synthetic remark.").feedback == "Synthetic remark."
    edited = _response(decision="edit", feedback="Synthetic remark.", **EDITED)
    assert edited.feedback == "Synthetic remark."


def test_response_does_not_carry_the_edited_content() -> None:
    assert "edited_content" not in ApprovalResponse.model_fields
    assert problems(ApprovalResponse, _response_document(edited_content="text")) == [
        ("edited_content", "unknown_key")
    ]


def test_edit_names_the_version_the_person_saved() -> None:
    response = _response(decision="edit", **EDITED)
    assert response.edited_artifact_id == "method-v004"
    assert response.edited_content_hash == EDITED["edited_content_hash"]
    assert problems(ApprovalResponse, _response_document(decision="edit")) == [
        ("edited_artifact_id", "required_for_edit"),
        ("edited_content_hash", "required_for_edit"),
    ]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_other_decisions_name_no_edited_version(decision: str) -> None:
    document = _response_document(decision=decision, feedback="Synthetic feedback.", **EDITED)
    assert problems(ApprovalResponse, document) == [
        ("edited_artifact_id", "not_allowed_unless_edit"),
        ("edited_content_hash", "not_allowed_unless_edit"),
    ]


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
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / "method_gate.json")
    # The responses to the artifact request; those of the other kinds are
    # paired with their own requests below.
    for path in valid_paths(RESPONSE):
        response = load_approval_response(path)
        if response.kind is ApprovalKind.ARTIFACT:
            check_response_matches_request(request, response, str(path))


def test_invalid_fixture_tables() -> None:
    check_table(REQUEST, INVALID_REQUESTS)
    check_table(RESPONSE, INVALID_RESPONSES)


@pytest.mark.parametrize("row", INVALID_REQUESTS, ids=[row[0] for row in INVALID_REQUESTS])
def test_invalid_request_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(REQUEST, load_approval_request, row)


@pytest.mark.parametrize("row", INVALID_RESPONSES, ids=[row[0] for row in INVALID_RESPONSES])
def test_invalid_response_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(RESPONSE, load_approval_response, row)


# An edit names a different version from the one that was shown


def test_edit_response_matches_its_request() -> None:
    check_response_matches_request(_request(), _response(decision="edit", **EDITED), "r.json")


def test_edited_version_must_differ_from_the_requested_one() -> None:
    request = _request()
    response = _response(
        decision="edit",
        edited_artifact_id=request.artifact_id,
        edited_content_hash=request.content_hash,
    )
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(request, response, "response.json")
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("edited_artifact_id", "same_as_request"),
        ("edited_content_hash", "same_as_request"),
    ]


def test_edit_with_unchanged_content_under_a_new_id_is_refused() -> None:
    request = _request()
    response = _response(
        decision="edit", edited_artifact_id="method-v004", edited_content_hash=request.content_hash
    )
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(request, response, "response.json")
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("edited_content_hash", "same_as_request")
    ]


# Kinds (M1-04, ADR-0011)

ARTIFACT_FIELDS = ("gate", "artifact_id", "content_hash", "path")
UNBOUND_FIELDS = ("stage", "refused_event_id")


def test_the_kinds_are_the_three_of_adr_0011() -> None:
    assert [kind.value for kind in ApprovalKind] == ["artifact", "budget_exhausted", "retry_limit"]


@pytest.mark.parametrize("name", ["budget_exhausted.json", "retry_limit.json"])
def test_an_unbound_request_records_the_stage_and_the_refused_call(name: str) -> None:
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / name)
    assert request.kind is not ApprovalKind.ARTIFACT
    assert request.stage is not None
    assert request.refused_event_id is not None
    assert all(getattr(request, field) is None for field in ARTIFACT_FIELDS)


@pytest.mark.parametrize("field", ARTIFACT_FIELDS)
def test_every_artifact_field_is_required_for_kind_artifact(field: str) -> None:
    document = {**read_valid(REQUEST, "method_gate.json"), field: None}
    assert problems(ApprovalRequest, document) == [(field, "required_for_kind")]


@pytest.mark.parametrize("field", UNBOUND_FIELDS)
def test_stage_and_refused_call_are_null_for_kind_artifact(field: str) -> None:
    value = "methodology" if field == "stage" else "e-000001"
    document = {**read_valid(REQUEST, "method_gate.json"), field: value}
    assert problems(ApprovalRequest, document) == [(field, "not_allowed_for_kind")]


@pytest.mark.parametrize("kind", ["budget_exhausted", "retry_limit"])
def test_artifact_fields_are_null_for_the_unbound_kinds(kind: str) -> None:
    document = {
        **read_valid(REQUEST, "method_gate.json"),
        "kind": kind,
        "stage": "experiment",
        "refused_event_id": "e-000042",
    }
    assert problems(ApprovalRequest, document) == [
        (field, "not_allowed_for_kind") for field in ARTIFACT_FIELDS
    ]


@pytest.mark.parametrize("kind", ["budget_exhausted", "retry_limit"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_an_unbound_kind_is_answered_with_approve_or_reject(kind: str, decision: str) -> None:
    document = {
        **read_valid(RESPONSE, "approve_budget_exhausted.json"),
        "kind": kind,
        "decision": decision,
        "feedback": "Synthetic remark." if decision == "reject" else None,
    }
    assert ApprovalResponse.from_json(json.dumps(document)).decision.value == decision


def test_edit_is_refused_for_an_unbound_kind_whatever_else_it_names() -> None:
    document = {
        **read_valid(RESPONSE, "approve_budget_exhausted.json"),
        "decision": "edit",
        "edited_artifact_id": "method-v004",
        "edited_content_hash": OTHER_HASH,
    }
    assert problems(ApprovalResponse, document) == [("decision", "edit_not_allowed_for_kind")]


def test_an_unbound_response_matches_its_request() -> None:
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / "budget_exhausted.json")
    response = load_approval_response(
        FIXTURES_ROOT / RESPONSE / "valid" / "approve_budget_exhausted.json"
    )
    check_response_matches_request(request, response, "a-000009.response.json")


def test_a_response_of_another_kind_does_not_match() -> None:
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / "budget_exhausted.json")
    document = {**read_valid(RESPONSE, "approve_budget_exhausted.json"), "kind": "retry_limit"}
    response = ApprovalResponse.from_json(json.dumps(document))
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(request, response, "a-000009.response.json")
    assert [(p.field, p.code) for p in caught.value.problems] == [("kind", "differs_from_request")]


def test_an_artifact_approval_is_still_bound_to_its_content_hash() -> None:
    request = _request()
    response = _response(content_hash=OTHER_HASH)
    with pytest.raises(ContractValidationError) as caught:
        check_response_matches_request(request, response, "a-000007.response.json")
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("content_hash", "differs_from_request")
    ]


# Examples in the documents (M1 rule 2)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _json_blocks(document: str, start: str, end: str) -> list[str]:
    text = (REPO_ROOT / document).read_text(encoding="utf-8")
    section = text.split(start, 1)[1].split(end, 1)[0]
    return re.findall(r"```json\n(.*?)```", section, flags=re.DOTALL)


def test_the_examples_of_the_documentation_are_valid() -> None:
    blocks = _json_blocks(
        "docs/contracts.md", "## Approval request and response", "## Exporting the schemas"
    )
    assert len(blocks) == 4
    artifact = ApprovalRequest.from_json(blocks[0], source="docs/contracts.md")
    plan = ApprovalRequest.from_json(blocks[1], source="docs/contracts.md")
    budget = ApprovalRequest.from_json(blocks[2], source="docs/contracts.md")
    response = ApprovalResponse.from_json(blocks[3], source="docs/contracts.md")
    assert artifact.kind is ApprovalKind.ARTIFACT
    assert artifact.execution is None
    assert plan.execution is not None
    assert budget.kind is ApprovalKind.BUDGET_EXHAUSTED
    check_response_matches_request(budget, response, "docs/contracts.md")


def test_the_examples_of_the_specification_are_valid() -> None:
    blocks = _json_blocks("docs/spec.md", "### Approvals", "## 8.")
    assert len(blocks) == 3
    plan = ApprovalRequest.from_json(blocks[0], source="docs/spec.md")
    request = ApprovalRequest.from_json(blocks[1], source="docs/spec.md")
    response = ApprovalResponse.from_json(blocks[2], source="docs/spec.md")
    assert plan.execution is not None
    assert request.kind is ApprovalKind.BUDGET_EXHAUSTED
    check_response_matches_request(request, response, "docs/spec.md")


# The execution an experiment-plan request approves (M1-12 review)


def test_an_experiment_plan_request_records_the_execution_it_approves() -> None:
    request = load_approval_request(FIXTURES_ROOT / REQUEST / "valid" / "experiment_plan_gate.json")
    assert request.execution is not None
    assert request.execution.image_digest == "sha256:" + "a" * 64
    assert request.execution.command == ("python", "code/main.py")
    assert request.execution.read_only_paths == ("code", "inputs")
    assert request.execution.limits.memory_mb == 4096
    assert request.execution.limits.timeout_seconds == 3600.0


def test_the_execution_record_holds_every_field() -> None:
    document = read_valid(REQUEST, "experiment_plan_gate.json")
    del document["execution"]["limits"]["timeout_seconds"]
    assert problems(ApprovalRequest, document) == [("execution.limits.timeout_seconds", "missing")]
