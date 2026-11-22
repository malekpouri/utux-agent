"""Schema of one event, a line of `events.jsonl`.

The fields are those of the specification, section 7, "Event log". The log
is the public interface for dashboards and audit, so a stored event states
every field, with null where a field does not apply.
"""

import json
import math
import re
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
    LimitKind,
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
    RUN_STARTED = "run_started"
    RUN_RESUMED = "run_resumed"
    RUN_RESTARTED = "run_restarted"
    ROUTE_BACK = "route_back"
    LOCK_REMOVED = "lock_removed"


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
    EventType.LOG_REPAIRED: ("fragment_file", "fragment_hash", "fragment_bytes"),
    EventType.MODEL_CALL: ("provider", "is_external"),
    EventType.BUDGET_WARNING: ("spent_usd", "total_usd"),
    EventType.STAGE_START: ("node",),
    EventType.STAGE_END: ("node",),
    EventType.RUN_STARTED: ("mode", "commits", "commit_check_reason"),
    EventType.RUN_RESTARTED: ("changed_path", "expected_hash", "actual_hash"),
    EventType.APPROVAL_REQUESTED: ("approval_id", "kind", "gate"),
    EventType.APPROVAL_ANSWERED: ("approval_id", "decision", "feedback"),
    EventType.ROUTE_BACK: ("from_stage", "to_stage", "finding", "attempt", "cap"),
    EventType.LOCK_REMOVED: ("pid", "host", "command", "started_at"),
    EventType.CODE_EXECUTION: ("execution_run_id", "image_digest", "exit_status", "stopped_by"),
    EventType.ERROR: ("trace",),
}

# Keys of `data` whose value must be non-empty text.
_TEXT_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.PROJECT_CREATED: ("utux_version",),
    EventType.SETTING_CHANGED: ("key",),
    EventType.LOG_REPAIRED: ("fragment_file", "fragment_hash"),
    EventType.MODEL_CALL: ("provider",),
    EventType.STAGE_START: ("node",),
    EventType.STAGE_END: ("node",),
    EventType.RUN_STARTED: ("mode",),
    EventType.RUN_RESTARTED: ("changed_path",),
    EventType.APPROVAL_REQUESTED: ("approval_id", "kind"),
    EventType.APPROVAL_ANSWERED: ("approval_id", "decision"),
    EventType.ROUTE_BACK: ("from_stage", "to_stage"),
    EventType.LOCK_REMOVED: ("host", "command", "started_at"),
    EventType.CODE_EXECUTION: ("execution_run_id", "image_digest"),
}

# Keys of `data` whose value must be true or false.
_BOOLEAN_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.MODEL_CALL: ("is_external",),
    EventType.RUN_STARTED: ("commits",),
}

# Keys of `data` whose value must be a content hash.
_HASH_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.LOG_REPAIRED: ("fragment_hash",),
    EventType.CODE_EXECUTION: ("image_digest",),
}

# Keys of `data` whose value must be an execution run id, `r` and at least three digits.
_EXECUTION_RUN_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.CODE_EXECUTION: ("execution_run_id",),
}

_EXECUTION_RUN = re.compile(r"^r[0-9]{3,}$")

# Keys of `data` whose value must be a whole number (an exit status) or null.
_OPTIONAL_INTEGER_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.CODE_EXECUTION: ("exit_status",),
}

# Keys of `data` whose value must be a limit that stops a run, or null.
_OPTIONAL_LIMIT_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.CODE_EXECUTION: ("stopped_by",),
}

# Keys of `data` whose value must be a content hash or null.
_OPTIONAL_HASH_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.RUN_RESTARTED: ("expected_hash", "actual_hash"),
}

# Keys of `data` whose value must be non-empty text or null.
_OPTIONAL_TEXT_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.APPROVAL_ANSWERED: ("feedback",),
    EventType.ERROR: ("trace",),
}

# Keys of `data` whose value must be a stable code, as `status_reason`, or null.
_OPTIONAL_CODE_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.RUN_STARTED: ("commit_check_reason",),
    EventType.APPROVAL_REQUESTED: ("gate",),
}

_CODE = re.compile(r"^[a-z][a-z0-9_]*$")

# Keys of `data` whose value must be a whole number of zero or more.
_COUNT_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.LOG_REPAIRED: ("fragment_bytes",),
    EventType.ROUTE_BACK: ("attempt", "cap"),
    EventType.LOCK_REMOVED: ("pid",),
}

# Keys of `data` whose value must be a stable code: lower-case letters, digits and _.
_CODE_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.ROUTE_BACK: ("finding",),
}

# Keys of `data` whose value must be an amount in US dollars: a number of
# zero or more.
_USD_KEYS: dict[EventType, tuple[str, ...]] = {
    EventType.BUDGET_WARNING: ("spent_usd", "total_usd"),
}

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


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
            elif key in _HASH_KEYS.get(kind, ()) and not _SHA256.match(text):
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "string_pattern_mismatch",
                            "must be sha256: and 64 lower-case hexadecimal digits",
                        ),
                        "loc": (key,),
                        "input": None,
                    }
                )
    for key in _OPTIONAL_HASH_KEYS.get(kind, ()):
        if key in value and value[key] is not None:
            hashed = value[key]
            if not isinstance(hashed, str) or not _SHA256.match(hashed):
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "string_pattern_mismatch",
                            "must be null or sha256: and 64 lower-case hexadecimal digits",
                        ),
                        "loc": (key,),
                        "input": None,
                    }
                )
    for key in _OPTIONAL_TEXT_KEYS.get(kind, ()):
        if key in value and value[key] is not None:
            text = value[key]
            if not isinstance(text, str) or not text:
                errors.append({"type": "string_type", "loc": (key,), "input": None})
    for key in _CODE_KEYS.get(kind, ()):
        if key in value:
            code = value[key]
            if not isinstance(code, str) or not _CODE.match(code):
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "string_pattern_mismatch",
                            "must be a code of lower-case letters, digits and _",
                        ),
                        "loc": (key,),
                        "input": None,
                    }
                )
    for key in _OPTIONAL_CODE_KEYS.get(kind, ()):
        if key in value and value[key] is not None:
            code = value[key]
            if not isinstance(code, str) or not _CODE.match(code):
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "string_pattern_mismatch",
                            "must be null or a code of lower-case letters, digits and _",
                        ),
                        "loc": (key,),
                        "input": None,
                    }
                )
    for key in _EXECUTION_RUN_KEYS.get(kind, ()):
        run = value.get(key)
        if isinstance(run, str) and run and not _EXECUTION_RUN.match(run):
            errors.append(
                {
                    "type": PydanticCustomError(
                        "string_pattern_mismatch", "must be r and at least three digits"
                    ),
                    "loc": (key,),
                    "input": None,
                }
            )
    for key in _OPTIONAL_INTEGER_KEYS.get(kind, ()):
        number = value.get(key)
        if number is not None and (not isinstance(number, int) or isinstance(number, bool)):
            errors.append(
                {
                    "type": PydanticCustomError("int_type", "must be a whole number or null"),
                    "loc": (key,),
                    "input": None,
                }
            )
    for key in _OPTIONAL_LIMIT_KEYS.get(kind, ()):
        limit = value.get(key)
        if limit is not None and limit not in {each.value for each in LimitKind}:
            errors.append(
                {
                    "type": PydanticCustomError(
                        "enum",
                        "must be null or one of {limits}",
                        {"limits": ", ".join(each.value for each in LimitKind)},
                    ),
                    "loc": (key,),
                    "input": None,
                }
            )
    for key in _BOOLEAN_KEYS.get(kind, ()):
        if key in value and not isinstance(value[key], bool):
            errors.append(
                {
                    "type": PydanticCustomError("bool_type", "must be true or false"),
                    "loc": (key,),
                    "input": None,
                }
            )
    for key in _COUNT_KEYS.get(kind, ()):
        if key in value:
            count = value[key]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                errors.append(
                    {
                        "type": PydanticCustomError(
                            "int_type", "must be a whole number of zero or more"
                        ),
                        "loc": (key,),
                        "input": None,
                    }
                )
    for key in _USD_KEYS.get(kind, ()):
        if key in value:
            amount = value[key]
            if (
                not isinstance(amount, int | float)
                or isinstance(amount, bool)
                or not math.isfinite(amount)
            ):
                errors.append(
                    {
                        "type": PydanticCustomError("float_type", "must be a number"),
                        "loc": (key,),
                        "input": None,
                    }
                )
            elif amount < 0:
                errors.append(
                    {
                        "type": PydanticCustomError("greater_than_equal", "must be zero or more"),
                        "loc": (key,),
                        "input": None,
                    }
                )
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
