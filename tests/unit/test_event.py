"""M0-05: the event schema."""

import json
import re
from pathlib import Path

import pytest

from utux.errors import ContractValidationError
from utux.schemas.common import Stage, Tier
from utux.schemas.event import Event, EventStatus, EventType, NewEvent, load_event

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "event"
VALID = sorted((FIXTURES / "valid").glob("*.json"))

# SHA-256 of b"synthetic fixture content\n", computed with sha256sum.
SYNTHETIC_HASH = "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"

# Every field of the specification, section 7, "Event log".
SPEC_FIELDS = [
    "schema_version",
    "event_id",
    "run_id",
    "request_id",
    "parent_id",
    "ts",
    "actor",
    "stage",
    "type",
    "model",
    "prompt_version",
    "tool_version",
    "input_hash",
    "output_hash",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "duration_ms",
    "status",
    "retry_reason",
    "escalated_from",
    "artifacts",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("unknown_type.json", "type", "enum"),
    ("unknown_status.json", "status", "enum"),
    ("missing_actor.json", "actor", "missing"),
    ("missing_cost.json", "cost_usd", "missing"),
    ("unknown_key.json", "message", "unknown_key"),
    ("negative_tokens.json", "tokens_in", "greater_than_equal"),
    ("negative_cost.json", "cost_usd", "greater_than_equal"),
    ("event_id_malformed.json", "event_id", "string_pattern_mismatch"),
    ("timestamp_without_z.json", "ts", "utc_timestamp"),
    ("unknown_stage.json", "stage", "enum"),
    ("hash_not_sha256.json", "input_hash", "string_pattern_mismatch"),
    ("artifact_without_version.json", "artifacts.1", "string_pattern_mismatch"),
    ("unknown_tier_in_escalated_from.json", "escalated_from", "enum"),
    ("actor_without_kind.json", "actor", "string_pattern_mismatch"),
    ("parent_is_the_event_itself.json", "parent_id", "self_reference"),
    ("parent_is_a_later_event.json", "parent_id", "parent_not_earlier"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def _valid_document() -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / "model_call.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _problems(document: dict[str, object]) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        Event.from_json(json.dumps(document), source="event.json")
    return [(p.field, p.code) for p in caught.value.problems]


# Fields


def test_event_has_exactly_the_fields_of_the_specification() -> None:
    assert sorted(Event.model_fields) == sorted(SPEC_FIELDS)


def test_every_field_is_required_in_a_stored_event() -> None:
    for field in SPEC_FIELDS:
        document = _valid_document()
        del document[field]
        assert _problems(document) == [(field, "missing")]


def test_model_call_fixture_reads_every_field() -> None:
    event = load_event(FIXTURES / "valid" / "model_call.json")
    assert event.schema_version == 1
    assert event.event_id == "e-000913"
    assert event.run_id == "p-7f3a"
    assert event.request_id == "q-0412"
    assert event.parent_id == "e-000907"
    assert event.ts == "2026-11-15T10:42:07Z"
    assert event.actor == "agent:planner"
    assert event.stage is Stage.METHODOLOGY
    assert event.type is EventType.MODEL_CALL
    assert event.model == "synthetic/model"
    assert event.prompt_version == "planner@3"
    assert event.tool_version is None
    assert event.input_hash == SYNTHETIC_HASH
    assert event.output_hash == SYNTHETIC_HASH
    assert event.tokens_in == 5120
    assert event.tokens_out == 830
    assert event.cost_usd == 0.012
    assert event.duration_ms == 8400
    assert event.status is EventStatus.OK
    assert event.retry_reason is None
    assert event.escalated_from is None
    assert event.artifacts == ("method-v003",)


def test_event_with_only_the_fields_that_always_apply() -> None:
    event = load_event(FIXTURES / "valid" / "project_created.json")
    assert event.type is EventType.PROJECT_CREATED
    assert event.actor == "system:utux"
    assert event.stage is None
    assert event.cost_usd is None
    assert event.artifacts == ()


def test_escalation_names_the_tier_the_call_came_from() -> None:
    event = load_event(FIXTURES / "valid" / "escalated_retry_without_cost.json")
    assert event.escalated_from is Tier.STANDARD
    assert event.retry_reason == "rejected by a deterministic check"
    assert event.status is EventStatus.ERROR


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    event = load_event(path)
    line = event.to_json_line()
    again = Event.from_json(line)
    assert again == event
    assert again.to_json_line() == line
    assert json.loads(line) == json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_an_event_is_written_as_exactly_one_line(path: Path) -> None:
    line = load_event(path).to_json_line()
    assert line.endswith("\n")
    assert line.count("\n") == 1


def test_text_with_line_breaks_still_gives_one_line() -> None:
    document = _valid_document()
    document["retry_reason"] = "first line\nsecond line\r\nthird"
    line = Event.from_json(json.dumps(document)).to_json_line()
    assert line.count("\n") == 1
    assert Event.from_json(line).retry_reason == "first line\nsecond line\r\nthird"


def test_there_are_valid_fixtures() -> None:
    assert len(VALID) >= 2


# The example of the specification


def test_specification_example_validates() -> None:
    """The event example of docs/spec.md, section 7, is a valid event.

    The example elides two digests as "sha256:...". Those placeholders are
    the one thing replaced here, with a synthetic digest; everything else is
    validated as written in the specification.
    """
    spec = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    section = spec.split("### Event log", 1)[1]
    match = re.search(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert match is not None
    example = match.group(1)
    assert example.count('"sha256:..."') == 2
    assert sorted(json.loads(example)) == sorted(SPEC_FIELDS)
    event = Event.from_json(
        example.replace('"sha256:..."', f'"{SYNTHETIC_HASH}"'), source="docs/spec.md"
    )
    assert event.event_id == "e-000913"
    assert event.parent_id == "e-000907"
    assert event.type is EventType.MODEL_CALL
    assert event.actor == "agent:planner"
    assert event.stage is Stage.METHODOLOGY
    assert event.cost_usd == 0.012
    assert event.artifacts == ("method-v003",)


# Closed sets


def test_event_types_are_the_ones_named_in_the_specification_and_the_plan() -> None:
    assert {kind.value for kind in EventType} == {
        "project_created",
        "stage_start",
        "stage_end",
        "model_call",
        "tool_call",
        "code_execution",
        "verification_result",
        "approval_requested",
        "approval_answered",
        "budget_warning",
        "setting_changed",
        "error",
    }


@pytest.mark.parametrize("value", ["model-call", "MODEL_CALL", "llm_call", "", None, 3])
def test_unknown_type_is_rejected(value: object) -> None:
    document = _valid_document()
    document["type"] = value
    assert [field for field, _ in _problems(document)] == ["type"]


def test_status_is_a_closed_set() -> None:
    assert {status.value for status in EventStatus} == {"ok", "error"}


# Values


@pytest.mark.parametrize("field", ["tokens_in", "tokens_out", "duration_ms"])
@pytest.mark.parametrize("value", [-1, 1.5, "12", True])
def test_counts_are_whole_numbers_of_zero_or_more(field: str, value: object) -> None:
    document = _valid_document()
    document[field] = value
    assert [name for name, _ in _problems(document)] == [field]


@pytest.mark.parametrize("value", [-0.01, "0.01", True])
def test_cost_is_a_number_of_zero_or_more_or_null(value: object) -> None:
    document = _valid_document()
    document["cost_usd"] = value
    assert [name for name, _ in _problems(document)] == ["cost_usd"]


def test_cost_of_zero_and_unknown_cost_are_different_and_both_valid() -> None:
    document = _valid_document()
    document["cost_usd"] = 0
    assert Event.from_json(json.dumps(document)).cost_usd == 0.0
    document["cost_usd"] = None
    assert Event.from_json(json.dumps(document)).cost_usd is None


@pytest.mark.parametrize("value", ["e-913", "E-000913", "e000913", "e-00091x", "x-000913"])
def test_event_id_is_e_and_at_least_six_digits(value: str) -> None:
    document = _valid_document()
    document["event_id"] = value
    document["parent_id"] = None
    assert _problems(document) == [("event_id", "string_pattern_mismatch")]


def test_event_id_may_grow_beyond_six_digits() -> None:
    document = _valid_document()
    document["event_id"] = "e-1000000"
    assert Event.from_json(json.dumps(document)).event_id == "e-1000000"


def test_parent_must_be_an_earlier_event() -> None:
    document = _valid_document()
    document["parent_id"] = "e-000912"
    assert Event.from_json(json.dumps(document)).parent_id == "e-000912"
    # Compared as numbers, not as text.
    document["event_id"] = "e-1000000"
    document["parent_id"] = "e-999999"
    assert Event.from_json(json.dumps(document)).parent_id == "e-999999"


@pytest.mark.parametrize("field", ["run_id", "request_id", "model", "prompt_version"])
def test_text_fields_may_be_null_but_not_empty(field: str) -> None:
    document = _valid_document()
    document[field] = None
    assert getattr(Event.from_json(json.dumps(document)), field) is None
    document[field] = ""
    assert [name for name, _ in _problems(document)] == [field]


# A new event, before the log gives it an id and a time


def test_new_event_needs_only_actor_type_and_status() -> None:
    new = NewEvent(actor="system:utux", type=EventType.PROJECT_CREATED, status=EventStatus.OK)
    assert new.stage is None
    assert new.cost_usd is None
    assert new.artifacts == ()


def test_new_event_has_every_event_field_except_those_the_log_sets() -> None:
    assert set(NewEvent.model_fields) == set(SPEC_FIELDS) - {"schema_version", "event_id", "ts"}


def test_new_event_rejects_an_unknown_type_and_an_unknown_field() -> None:
    with pytest.raises(ValueError, match="type"):
        NewEvent(actor="system:utux", type="coffee_break", status=EventStatus.OK)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="message"):
        NewEvent(  # type: ignore[call-arg]
            actor="system:utux", type=EventType.ERROR, status=EventStatus.ERROR, message="x"
        )


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
        load_event(path)
    error = caught.value
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    assert error.source == str(path)
    assert str(error) == f"{path}: {field}: {error.problems[0].reason}"
