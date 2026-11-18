"""Schemas of an approval request and of its response.

The core writes `approvals/<id>.request.json` and pauses. A person answers
through the CLI, or any later interface, which writes
`approvals/<id>.response.json` (specification, section 7, "Approvals").

An approval binds to one exact version. The request names the artifact
version and the hash of its content, and the response repeats both. If the
file is edited after the request, its hash changes, and an approval given for
the old content does not carry over.

For an edit, the person changes the file itself. The response names the
version they saved and approve; it does not carry the content.

A request has a kind (ADR-0011). Only a request of kind `artifact` is about
an artifact and bound to its content hash. A budget or retry cap that is
reached pauses the run with a request of kind `budget_exhausted` or
`retry_limit`, which records the stage and the event of the refused call
instead, and is answered with `approve` (continue) or `reject` (stop).
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, model_validator
from pydantic_core import InitErrorDetails

from utux.errors import ContractValidationError, Problem
from utux.schemas.base import ContractDocument, field_problem, raise_field_problems
from utux.schemas.common import (
    Actor,
    ArtifactId,
    EventId,
    NonEmptyText,
    RelativePath,
    Sha256Hash,
    Stage,
    UtcTimestamp,
)
from utux.schemas.json_io import read_json
from utux.schemas.project_config import Gate

ApprovalId = Annotated[str, Field(pattern=r"^a-[0-9]{6,}$", strict=True)]
"""An approval id: `a-` and at least six digits, for example `a-000007`."""


class ApprovalKind(StrEnum):
    """What a request asks about (ADR-0011)."""

    ARTIFACT = "artifact"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RETRY_LIMIT = "retry_limit"


def _kind_problems(
    document: ContractDocument,
    kind: ApprovalKind,
    bound: tuple[str, ...],
    unbound: tuple[str, ...],
) -> list[InitErrorDetails]:
    """Problems of fields that must be given for one kind and null for the others."""
    required, null = (bound, unbound) if kind is ApprovalKind.ARTIFACT else (unbound, bound)
    problems = [
        field_problem("required_for_kind", f"must not be null for kind {kind.value}", name)
        for name in required
        if getattr(document, name) is None
    ]
    problems += [
        field_problem("not_allowed_for_kind", f"must be null for kind {kind.value}", name)
        for name in null
        if getattr(document, name) is not None
    ]
    # Report in the order of the fields, not grouped by rule.
    order = {name: index for index, name in enumerate(type(document).model_fields)}
    return sorted(problems, key=lambda problem: order[str(problem["loc"][0])])


class Decision(StrEnum):
    """What the person decided."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ApprovalRequest(ContractDocument):
    """A question to a person. Every field is required; some are null by kind.

    Attributes:
        approval_id: Id of the approval; the response carries the same id.
        kind: What the request is about.
        gate: The gate that asks. Kind `artifact` only, else null.
        artifact_id: The artifact version to approve. Kind `artifact` only.
        content_hash: Hash of the content to approve. Kind `artifact` only.
        path: The file inside the project that holds the content. Kind
            `artifact` only.
        stage: The stage that was paused. Kinds `budget_exhausted` and
            `retry_limit` only, else null.
        refused_event_id: The event of the refused call, which the run
            repeats after `approve`. Kinds `budget_exhausted` and
            `retry_limit` only, else null.
        requested_by: Who asks.
        requested_at: When the request was written.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    approval_id: ApprovalId
    kind: ApprovalKind
    gate: Gate | None
    artifact_id: ArtifactId | None
    content_hash: Sha256Hash | None
    path: RelativePath | None
    stage: Stage | None
    refused_event_id: EventId | None
    requested_by: Actor
    requested_at: UtcTimestamp

    @model_validator(mode="after")
    def _fields_follow_the_kind(self) -> Self:
        problems = _kind_problems(
            self,
            self.kind,
            bound=("gate", "artifact_id", "content_hash", "path"),
            unbound=("stage", "refused_event_id"),
        )
        raise_field_problems(type(self).__name__, problems)
        return self


class ApprovalResponse(ContractDocument):
    """A person's answer to a request. Every field is required; some may be null.

    Attributes:
        approval_id: The id of the request this answers.
        kind: The kind of the request, repeated.
        artifact_id: The artifact version the person saw, as in the request.
            Null for a kind other than `artifact`.
        content_hash: The hash of the content the person saw, as in the
            request. Null for a kind other than `artifact`.
        decision: `approve`, `reject` or `edit`; `edit` for kind `artifact`
            only.
        answered_by: The person, as `human:<id>`.
        answered_at: When the answer was given.
        feedback: The person's remarks. Required for `reject`, else optional.
        edited_artifact_id: The artifact version the person saved and
            approves. Given exactly when the decision is `edit`.
        edited_content_hash: Hash of the content of that version. Given
            exactly when the decision is `edit`.

    For an edit, the person changes the file itself. The response does not
    carry the content; it only names the version that was saved.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    approval_id: ApprovalId
    kind: ApprovalKind
    artifact_id: ArtifactId | None
    content_hash: Sha256Hash | None
    decision: Decision
    answered_by: Annotated[str, Field(pattern=r"^human:[a-z0-9][a-z0-9_.-]*$", strict=True)]
    answered_at: UtcTimestamp
    feedback: NonEmptyText | None
    edited_artifact_id: ArtifactId | None
    edited_content_hash: Sha256Hash | None

    @model_validator(mode="after")
    def _fields_follow_the_decision(self) -> Self:
        problems = _kind_problems(
            self, self.kind, bound=("artifact_id", "content_hash"), unbound=()
        )
        if self.decision is Decision.EDIT and self.kind is not ApprovalKind.ARTIFACT:
            # Only an artifact can be edited; the edit fields are then not checked,
            # so that the one mistake is reported once.
            problems.append(
                field_problem(
                    "edit_not_allowed_for_kind",
                    f"a request of kind {self.kind.value} is answered with approve or reject",
                    "decision",
                )
            )
            raise_field_problems(type(self).__name__, problems)
            return self
        if self.decision is Decision.REJECT and self.feedback is None:
            problems.append(
                field_problem("feedback_required", "a rejection needs feedback", "feedback")
            )
        for name in ("edited_artifact_id", "edited_content_hash"):
            value = getattr(self, name)
            if self.decision is Decision.EDIT and value is None:
                problems.append(
                    field_problem(
                        "required_for_edit", "must not be null when the decision is edit", name
                    )
                )
            if self.decision is not Decision.EDIT and value is not None:
                problems.append(
                    field_problem(
                        "not_allowed_unless_edit",
                        f"must be null when the decision is {self.decision.value}",
                        name,
                    )
                )
        raise_field_problems(type(self).__name__, problems)
        return self


def check_response_matches_request(
    request: ApprovalRequest, response: ApprovalResponse, source: str
) -> None:
    """Check that a response answers this request for this exact content.

    Args:
        request: The request.
        response: The response to check.
        source: The file name of the response, for the error message.

    Raises:
        ContractValidationError: If the approval id, the kind, the artifact
            id or the content hash of the response differs from the request
            (the last two are null for the kinds that are not about an
            artifact, so only an artifact approval is bound to a hash), or if an
            edit names the same artifact version or the same content as the
            request. Every problem is reported, on its own field.
    """
    problems = [
        Problem(
            name,
            f"{getattr(response, name)} differs from the request, "
            f"which has {getattr(request, name)}",
            "differs_from_request",
        )
        for name in ("approval_id", "kind", "artifact_id", "content_hash")
        if getattr(response, name) != getattr(request, name)
    ]
    # An edit produces a new version with new content.
    problems += [
        Problem(edited, f"an edit must name a different {what} from the request", "same_as_request")
        for edited, requested, what in (
            ("edited_artifact_id", "artifact_id", "artifact version"),
            ("edited_content_hash", "content_hash", "content"),
        )
        if getattr(response, edited) is not None
        and getattr(response, edited) == getattr(request, requested)
    ]
    if problems:
        raise ContractValidationError(source, tuple(problems))


def load_approval_request(path: Path) -> ApprovalRequest:
    """Read and validate an approval request file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            request. The error names the path as it was given.
    """
    return ApprovalRequest.validate_document(read_json(path), str(path))


def load_approval_response(path: Path) -> ApprovalResponse:
    """Read and validate an approval response file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            response. The error names the path as it was given.
    """
    return ApprovalResponse.validate_document(read_json(path), str(path))
