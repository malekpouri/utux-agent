"""Schema of one event, a line of `events.jsonl`.

The fields are those of the specification, section 7, "Event log". The log
is the public interface for dashboards and audit, so a stored event states
every field, with null where a field does not apply.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import Field, ValidationError, ValidationInfo, field_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.common import (
    Actor,
    ArtifactId,
    Count,
    EventId,
    FlatObject,
    Identifier,
    NonEmptyText,
    NonNegativeUsd,
    Scalar,
    Sha256Hash,
    Stage,
    Tier,
    UtcTimestamp,
)
from utux.schemas.json_io import parse_json, read_json


class EventType(StrEnum):
    """What happened."""

    PROJECT_CREATED = "project_created"
    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    CODE_EXECUTION = "code_execution"
    VERIFICATION_RESULT = "verification_result"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_ANSWERED = "approval_answered"
    BUDGET_WARNING = "budget_warning"
    SETTING_CHANGED = "setting_changed"
    ERROR = "error"
    LOG_REPAIRED = "log_repaired"


class EventStatus(StrEnum):
    """How what the event records ended.

    `REFUSED` means that utux itself declined the action, for example a call
    to an external provider under the data policy `local_only`.
    """

    OK = "ok"
    ERROR = "error"
    REFUSED = "refused"


# The keys of `data` for each event type. A type that is not listed accepts
# only an empty object, until the task that emits it defines its keys.
_DATA_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.PROJECT_CREATED: ("utux_version",),
    EventType.SETTING_CHANGED: ("key", "old_value", "new_value"),
}

# Keys of `data` whose value must be non-empty text.
_TEXT_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.PROJECT_CREATED: ("utux_version",),
    EventType.SETTING_CHANGED: ("key",),
}


def _check_status_reason(value: str | None, info: ValidationInfo) -> str | None:
    status = info.data.get("status")
    if status is None:
        # The status is invalid and is reported on its own field.
        return value
    if status is EventStatus.OK and value is not None:
        raise PydanticCustomError("status_reason_not_allowed", "must be null when the status is ok")
    if status is not EventStatus.OK and value is None:
        raise PydanticCustomError(
            "status_reason_required",
            "a status of {status} needs a reason code",
            {"status": status.value},
        )
    return value


def _check_model(value: str | None, info: ValidationInfo) -> str | None:
    if value is None and info.data.get("type") is EventType.MODEL_CALL:
        raise PydanticCustomError("model_required", "a model_call event must name its model")
    return value


def _check_data_keys(value: dict[str, Scalar], info: ValidationInfo) -> dict[str, Scalar]:
    kind = info.data.get("type")
    if kind is None:
        # The type is invalid and is reported on its own field.
        return value
    expected = _DATA_KEYS.get(kind, ())
    errors: list[InitErrorDetails] = [
        {"type": "missing", "loc": (key,), "input": None} for key in expected if key not in value
    ]
    errors += [
        {"type": "extra_forbidden", "loc": (key,), "input": None}
        for key in value
        if key not in expected
    ]
    for key in _TEXT_KEYS.get(kind, ()):
        if key in value:
            text = value[key]
            if not isinstance(text, str) or not text:
                errors.append({"type": "string_type", "loc": (key,), "input": None})
    if errors:
        raise ValidationError.from_exception_data("data", errors)
    return value


EventData = FlatObject
"""The `data` object: flat, with scalar values only."""


def event_number(event_id: str) -> int:
    """Return the number in an event id, for example 913 for `e-000913`."""
    return int(event_id.removeprefix("e-"))


def format_event_id(number: int) -> str:
    """Return the event id for a number, for example `e-000913` for 913."""
    return f"e-{number:06d}"


class NewEvent(ContractPart):
    """An event before it is stored.

    It has every field of `Event` except the three that the event log sets:
    `schema_version`, `event_id` and `ts`. Only `actor`, `type` and `status`
    must be given; a field that does not apply is left as None. The rules
    between fields are checked when the log stores the event.
    """

    actor: Actor
    type: EventType
    status: EventStatus
    status_reason: Identifier | None = None
    run_id: NonEmptyText | None = None
    request_id: NonEmptyText | None = None
    parent_id: EventId | None = None
    stage: Stage | None = None
    model: NonEmptyText | None = None
    prompt_version: NonEmptyText | None = None
    tool_version: NonEmptyText | None = None
    input_hash: Sha256Hash | None = None
    output_hash: Sha256Hash | None = None
    tokens_in: Count | None = None
    tokens_out: Count | None = None
    cost_usd: NonNegativeUsd | None = None
    duration_ms: Count | None = None
    retry_reason: Identifier | None = None
    escalated_from: Tier | None = None
    data: EventData = Field(default_factory=dict)
    artifacts: tuple[ArtifactId, ...] = ()


class Event(ContractDocument):
    """One stored event. Every field is required; many may be null.

    Attributes:
        event_id: Id of the event, unique and increasing within a project.
        run_id: The run the event belongs to, if any.
        request_id: The request the event belongs to, if any.
        parent_id: The earlier event that caused this one, if any.
        ts: When the event was recorded, in UTC.
        actor: Who acted.
        stage: The pipeline stage, if the event belongs to one.
        type: What happened.
        model: The model id. Required for a model call.
        prompt_version: The prompt version, for a model call.
        tool_version: The tool version, for a tool call.
        input_hash: Hash of what was sent. The content itself is not stored.
        output_hash: Hash of what came back.
        tokens_in: Input tokens.
        tokens_out: Output tokens.
        cost_usd: Cost in US dollars, or null when it is not known. A cost is
            never guessed, and zero is a known cost.
        duration_ms: How long it took, in milliseconds.
        status: `ok`, `error`, or `refused` when utux itself declined the
            action.
        status_reason: A stable machine code that explains a status other
            than `ok`, such as `model_timeout`. Null exactly when the status
            is `ok`. No free-text error message is stored in an event.
        retry_reason: A machine code for why a call was repeated.
        escalated_from: The tier a call was moved up from.
        data: Details that are specific to the event type: a flat object of
            scalar values with defined keys per type, empty when the type
            defines none. Message content and source text never go here.
        artifacts: The artifact versions the event produced or concerns.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    event_id: EventId
    run_id: NonEmptyText | None
    request_id: NonEmptyText | None
    parent_id: EventId | None
    ts: UtcTimestamp
    actor: Actor
    stage: Stage | None
    type: EventType
    model: NonEmptyText | None
    prompt_version: NonEmptyText | None
    tool_version: NonEmptyText | None
    input_hash: Sha256Hash | None
    output_hash: Sha256Hash | None
    tokens_in: Count | None
    tokens_out: Count | None
    cost_usd: NonNegativeUsd | None
    duration_ms: Count | None
    status: EventStatus
    status_reason: Identifier | None
    retry_reason: Identifier | None
    escalated_from: Tier | None
    data: EventData
    artifacts: tuple[ArtifactId, ...]

    _status_reason_matches_status = field_validator("status_reason")(_check_status_reason)
    _model_call_names_its_model = field_validator("model")(_check_model)
    _data_has_the_keys_of_its_type = field_validator("data")(_check_data_keys)

    @field_validator("parent_id")
    @classmethod
    def _parent_is_an_earlier_event(cls, value: str | None, info: ValidationInfo) -> str | None:
        event_id = info.data.get("event_id")
        if value is None or event_id is None:
            # No parent, or the event id is invalid and reported on its own field.
            return value
        if value == event_id:
            raise PydanticCustomError("self_reference", "an event cannot be its own parent")
        if event_number(value) > event_number(event_id):
            raise PydanticCustomError(
                "parent_not_earlier",
                "the parent {parent} is not an earlier event than {event}",
                {"parent": value, "event": event_id},
            )
        return value

    @classmethod
    def from_json(cls, text: str, source: str = "event") -> Self:
        """Parse and validate the JSON text of one event.

        Args:
            text: The JSON text, with or without a final newline.
            source: The file name to use in error messages.

        Raises:
            ContractValidationError: If the text is not a valid event.
        """
        return cls.validate_document(parse_json(text, source), source)

    def to_json_line(self) -> str:
        """Return the event as one line of JSON that ends with a newline.

        JSON escapes line breaks inside text, so the result is always
        exactly one line.
        """
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


def load_event(path: Path) -> Event:
    """Read and validate a file that holds one event as a JSON document.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            event. The error names the path as it was given.
    """
    return Event.validate_document(read_json(path), str(path))
