"""Schemas of an approval request and of its response.

The core writes `approvals/<id>.request.json` and pauses. A person answers
through the CLI, or any later interface, which writes
`approvals/<id>.response.json` (specification, section 7, "Approvals").

An approval binds to one exact version. The request names the artifact
version and the hash of its content, and the response repeats both. If the
file is edited after the request, its hash changes, and an approval given for
the old content does not carry over.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import Field, StrictStr, model_validator

from utux.errors import ContractValidationError, Problem
from utux.schemas.base import ContractDocument, field_problem, raise_field_problems
from utux.schemas.common import (
    Actor,
    ArtifactId,
    NonEmptyText,
    RelativePath,
    Sha256Hash,
    UtcTimestamp,
)
from utux.schemas.json_io import read_json
from utux.schemas.project_config import Gate

ApprovalId = Annotated[str, Field(pattern=r"^a-[0-9]{6,}$", strict=True)]
"""An approval id: `a-` and at least six digits, for example `a-000007`."""


class Decision(StrEnum):
    """What the person decided."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ApprovalRequest(ContractDocument):
    """A question to a person at a gate. Every field is required.

    Attributes:
        approval_id: Id of the approval; the response carries the same id.
        gate: The gate that asks.
        artifact_id: The artifact version to approve.
        content_hash: Hash of the content to approve.
        path: The file inside the project that holds the content.
        requested_by: Who asks.
        requested_at: When the request was written.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    approval_id: ApprovalId
    gate: Gate
    artifact_id: ArtifactId
    content_hash: Sha256Hash
    path: RelativePath
    requested_by: Actor
    requested_at: UtcTimestamp


class ApprovalResponse(ContractDocument):
    """A person's answer to a request. Every field is required; two may be null.

    Attributes:
        approval_id: The id of the request this answers.
        artifact_id: The artifact version the person saw, as in the request.
        content_hash: The hash of the content the person saw, as in the
            request.
        decision: `approve`, `reject` or `edit`.
        answered_by: The person, as `human:<id>`.
        answered_at: When the answer was given.
        feedback: The person's remarks. Required for `reject`, else optional.
        edited_content: The edited text. Given exactly when the decision is
            `edit`.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    approval_id: ApprovalId
    artifact_id: ArtifactId
    content_hash: Sha256Hash
    decision: Decision
    answered_by: Annotated[str, Field(pattern=r"^human:[a-z0-9][a-z0-9_.-]*$", strict=True)]
    answered_at: UtcTimestamp
    feedback: NonEmptyText | None
    edited_content: StrictStr | None

    @model_validator(mode="after")
    def _fields_follow_the_decision(self) -> Self:
        problems = []
        if self.decision is Decision.REJECT and self.feedback is None:
            problems.append(
                field_problem("feedback_required", "a rejection needs feedback", "feedback")
            )
        if self.decision is Decision.EDIT and self.edited_content is None:
            problems.append(
                field_problem(
                    "edited_content_required",
                    "the decision edit needs the edited content",
                    "edited_content",
                )
            )
        if self.decision is not Decision.EDIT and self.edited_content is not None:
            problems.append(
                field_problem(
                    "edited_content_not_allowed",
                    f"must be null when the decision is {self.decision.value}",
                    "edited_content",
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
        ContractValidationError: If the approval id, the artifact id or the
            content hash of the response differs from the request. Every
            difference is reported, on its own field.
    """
    problems = tuple(
        Problem(
            name,
            f"{getattr(response, name)} differs from the request, "
            f"which has {getattr(request, name)}",
            "differs_from_request",
        )
        for name in ("approval_id", "artifact_id", "content_hash")
        if getattr(response, name) != getattr(request, name)
    )
    if problems:
        raise ContractValidationError(source, problems)


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
