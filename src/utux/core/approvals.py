"""Answering an approval request (`utux approve`, M1-14).

The command writes `approvals/<id>.response.json` under the project lock;
the run takes the answer when it resumes (see `utux.core.workflow`). A
response repeats the version and content hash of its request, so an answer
is refused if the file changed since the request: the person then answers
with `edit`, which names the saved file as the next version of the artifact
and its hash. The run records that version, made by the person, when it
takes the answer.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from utux.core.workflow import APPROVALS_DIRECTORY, EDITED_BY, current_artifact
from utux.errors import ApprovalAnswerError
from utux.schemas.approval import (
    ApprovalKind,
    ApprovalResponse,
    Decision,
    load_approval_request,
)
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_file
from utux.workspace.writer import writing_command

_PERSON = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Answer:
    """What `answer_approval` wrote.

    Attributes:
        response: The response.
        path: Its file, relative to the project.
    """

    response: ApprovalResponse
    path: str


def person_actor(person: str) -> str:
    """The actor of a person id, `human:<id>`.

    Raises:
        ApprovalAnswerError: The id is not lower-case letters, digits, `_`,
            `.` and `-`, or it is `unknown`, which stands for edits made
            outside utux.
    """
    if not _PERSON.match(person):
        raise ApprovalAnswerError(
            f"{person!r} cannot be recorded as the person who answers: give an id of "
            "lower-case letters, digits, _, . and -, with --by"
        )
    actor = f"human:{person}"
    if actor == EDITED_BY:
        raise ApprovalAnswerError(
            f"{EDITED_BY} stands for edits made outside utux; give your own id with --by"
        )
    return actor


def answer_approval(
    project: Path,
    approval_id: str,
    decision: Decision,
    *,
    person: str,
    feedback: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> Answer:
    """Write a person's answer to a request, under the project lock.

    Args:
        project: The project directory.
        approval_id: The request, for example `a-000001`.
        decision: `approve`, `reject` or `edit`.
        person: The person's id; recorded as `human:<id>`.
        feedback: The person's remarks; required for `reject`.
        clock: Returns the current time in UTC.

    Raises:
        ApprovalAnswerError: There is no such request; it is already
            answered; the person id cannot be recorded; `reject` has no
            feedback; `edit` is for a request that is not about a file, or
            the file is unchanged; or the file changed since the request and
            the decision is not `edit`. Nothing is written.
        ProjectLockedError: Another command holds the project lock.
    """
    actor = person_actor(person)
    if feedback is not None and not feedback.strip():
        feedback = None
    with writing_command(project, "approve"):
        directory = project / APPROVALS_DIRECTORY
        request_path = directory / f"{approval_id}.request.json"
        relative = f"{APPROVALS_DIRECTORY}/{approval_id}.response.json"
        if not request_path.is_file():
            raise ApprovalAnswerError(
                f"there is no request {approval_id} in {APPROVALS_DIRECTORY}/"
            )
        if (project / relative).exists():
            raise ApprovalAnswerError(
                f"{approval_id} is already answered ({relative}); an answer is not changed"
            )
        request = load_approval_request(request_path)
        if decision is Decision.REJECT and feedback is None:
            raise ApprovalAnswerError(
                "a rejection needs feedback: say what to change with --feedback"
            )
        edited_id: str | None = None
        edited_hash: str | None = None
        if request.kind is not ApprovalKind.ARTIFACT:
            if decision is Decision.EDIT:
                raise ApprovalAnswerError(
                    f"{approval_id} is a {request.kind.value} pause, not about a file; answer "
                    "it with approve (continue) or reject (stop)"
                )
        else:
            assert request.path is not None
            actual = hash_file(project / request.path)
            changed = actual != request.content_hash
            if decision is Decision.EDIT:
                if not changed:
                    raise ApprovalAnswerError(
                        f"{request.path} is unchanged since {approval_id} was asked; save your "
                        "edit first, or answer with approve"
                    )
                current = current_artifact(project, request.path)
                assert current is not None
                name, version = current.artifact_id.rsplit("-v", 1)
                edited_id, edited_hash = f"{name}-v{int(version) + 1:03d}", actual
            elif changed:
                raise ApprovalAnswerError(
                    f"{request.path} changed since {approval_id} was asked, so a "
                    f"{decision.value} would not be about the version the request names; "
                    "answer with edit to take the file as it is now, or undo the change"
                )
        response = ApprovalResponse(
            schema_version=ApprovalResponse.SCHEMA_VERSION,
            approval_id=request.approval_id,
            kind=request.kind,
            artifact_id=request.artifact_id,
            content_hash=request.content_hash,
            decision=decision,
            answered_by=actor,
            answered_at=clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            feedback=feedback,
            edited_artifact_id=edited_id,
            edited_content_hash=edited_hash,
        )
        atomic_write_text(project / relative, response.to_json())
        return Answer(response=response, path=relative)
