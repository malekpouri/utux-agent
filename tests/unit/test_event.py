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
    "status_reason",
    "retry_reason",
    "escalated_from",
    "data",
    "artifacts",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("unknown_type.json", "type", "enum"),
    ("unknown_status.json", "status", "enum"),
    ("missing_actor.json", "actor", "missing"),
    ("missing_cost.json", "cost_usd", "missing"),
    ("missing_status_reason.json", "status_reason", "missing"),
    ("missing_data.json", "data", "missing"),
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
    ("error_without_status_reason.json", "status_reason", "status_reason_required"),
    ("ok_with_status_reason.json", "status_reason", "status_reason_not_allowed"),
    ("status_reason_is_a_sentence.json", "status_reason", "string_pattern_mismatch"),
    ("retry_reason_is_a_sentence.json", "retry_reason", "string_pattern_mismatch"),
    ("model_call_without_model.json", "model", "model_required"),
    ("data_not_an_object.json", "data", "dict_type"),
    ("data_key_not_defined_for_type.json", "data.note", "unknown_key"),
    ("setting_changed_without_new_value.json", "data.new_value", "missing"),
    ("setting_changed_value_is_nested.json", "data.new_value", "not_scalar"),
    ("setting_changed_key_is_not_text.json", "data.key", "string_type"),
    ("project_created_without_utux_version.json", "data.utux_version", "missing"),
    ("log_repaired_without_fragment_hash.json", "data.fragment_hash", "missing"),
    ("model_call_without_provider.json", "data.provider", "missing"),
    ("model_call_is_external_not_boolean.json", "data.is_external", "bool_type"),
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
    assert event.status_reason is None
    assert event.retry_reason is None
    assert event.escalated_from is None
    assert event.data == {"provider": "synthetic-provider", "is_external": True}
    assert event.artifacts == ("method-v003",)


def test_event_with_only_the_fields_that_always_apply() -> None:
    event = load_event(FIXTURES / "valid" / "project_created.json")
    assert event.type is EventType.PROJECT_CREATED
    assert event.actor == "system:utux"
    assert event.stage is None
    assert event.cost_usd is None
    assert event.artifacts == ()
    assert event.data == {"utux_version": "0.1.0"}


def test_escalation_names_the_tier_the_call_came_from() -> None:
    event = load_event(FIXTURES / "valid" / "failed_escalated_retry.json")
    assert event.escalated_from is Tier.STANDARD
    assert event.retry_reason == "check_rejected"
    assert event.status is EventStatus.ERROR
    assert event.status_reason == "model_timeout"


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
    document = json.loads((FIXTURES / "valid" / "setting_changed.json").read_text("utf-8"))
    document["data"]["new_value"] = "first line\nsecond line\r\nthird"
    line = Event.from_json(json.dumps(document)).to_json_line()
    assert line.count("\n") == 1
    assert Event.from_json(line).data["new_value"] == "first line\nsecond line\r\nthird"


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
        "log_repaired",
    }


@pytest.mark.parametrize("value", ["model-call", "MODEL_CALL", "llm_call", "", None, 3])
def test_unknown_type_is_rejected(value: object) -> None:
    document = _valid_document()
    document["type"] = value
    assert [field for field, _ in _problems(document)] == ["type"]


def test_status_is_a_closed_set() -> None:
    assert {status.value for status in EventStatus} == {"ok", "error", "refused"}


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
    # Not a model_call, which must name its model.
    document["type"] = "stage_start"
    document[field] = None
    assert getattr(Event.from_json(json.dumps(document)), field) is None
    document[field] = ""
    assert [name for name, _ in _problems(document)] == [field]


# A new event, before the log gives it an id and a time


def test_new_event_needs_only_actor_type_and_status() -> None:
    new = NewEvent(actor="system:utux", type=EventType.PROJECT_CREATED, status=EventStatus.OK)
    assert new.stage is None
    assert new.cost_usd is None
    assert new.status_reason is None
    assert new.data == {}
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


# Status and its reason


def _with(**changes: object) -> dict[str, object]:
    return {**_valid_document(), **changes}


def test_refused_is_a_status_with_a_reason() -> None:
    event = load_event(FIXTURES / "valid" / "refused_model_call.json")
    assert event.status is EventStatus.REFUSED
    assert event.status_reason == "data_policy_local_only"


@pytest.mark.parametrize("status", ["error", "refused"])
def test_status_other_than_ok_needs_a_reason(status: str) -> None:
    assert _problems(_with(status=status)) == [("status_reason", "status_reason_required")]
    event = Event.from_json(json.dumps(_with(status=status, status_reason="budget_exhausted")))
    assert event.status_reason == "budget_exhausted"


def test_status_ok_has_no_reason() -> None:
    assert _problems(_with(status_reason="model_timeout")) == [
        ("status_reason", "status_reason_not_allowed")
    ]


@pytest.mark.parametrize(
    "value", ["The model timed out.", "Model_Timeout", "model timeout", "", "9lives", 7]
)
def test_status_reason_is_a_machine_code_not_a_message(value: object) -> None:
    problems = _problems(_with(status="error", status_reason=value))
    assert [field for field, _ in problems] == ["status_reason"]


@pytest.mark.parametrize("value", ["rejected by a check", "Check rejected", ""])
def test_retry_reason_is_a_machine_code_not_a_message(value: str) -> None:
    assert [field for field, _ in _problems(_with(retry_reason=value))] == ["retry_reason"]


def test_no_field_of_an_event_holds_a_free_text_message() -> None:
    """The fields that explain a failure accept codes only."""
    for field in ("status_reason", "retry_reason"):
        for text in ("Connection reset by peer", "timeout after 30 s"):
            document = _with(status="error", status_reason="model_timeout")
            document[field] = text
            problems = _problems(document)
            assert [name for name, _ in problems] == [field]
    assert "message" not in Event.model_fields
    assert "error" not in Event.model_fields


# Type rules


def test_model_call_must_name_its_model() -> None:
    assert _problems(_with(model=None)) == [("model", "model_required")]


def test_other_types_need_no_model() -> None:
    event = load_event(FIXTURES / "valid" / "project_created.json")
    assert event.model is None


# data of project_created


def _created(**data: object) -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / "project_created.json").read_text("utf-8"))
    assert isinstance(document, dict)
    document["data"] = data
    return document


def test_project_created_carries_the_utux_version() -> None:
    event = Event.from_json(json.dumps(_created(utux_version="1.2.3")))
    assert event.data == {"utux_version": "1.2.3"}


def test_project_created_needs_the_utux_version_and_no_other_key() -> None:
    assert _problems(_created()) == [("data.utux_version", "missing")]
    assert _problems(_created(utux_version="1.2.3", host="x")) == [("data.host", "unknown_key")]


@pytest.mark.parametrize("value", ["", 1, None, True])
def test_utux_version_is_non_empty_text(value: object) -> None:
    assert _problems(_created(utux_version=value)) == [("data.utux_version", "string_type")]


# data


def _setting(**data: object) -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / "setting_changed.json").read_text("utf-8"))
    assert isinstance(document, dict)
    document["data"] = data
    return document


def test_setting_changed_carries_key_old_value_and_new_value() -> None:
    event = load_event(FIXTURES / "valid" / "setting_changed.json")
    assert event.data == {"key": "verification.enabled", "old_value": True, "new_value": False}


@pytest.mark.parametrize("value", ["text", 3, 0.5, True, False, None])
def test_data_values_are_strings_numbers_booleans_or_null(value: object) -> None:
    document = _setting(key="budget.total_usd", old_value=value, new_value=value)
    event = Event.from_json(json.dumps(document))
    assert event.data["old_value"] == value
    assert type(event.data["old_value"]) is type(value)


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2], []])
def test_data_is_flat(value: object) -> None:
    document = _setting(key="budget.total_usd", old_value=value, new_value=1)
    assert _problems(document) == [("data.old_value", "not_scalar")]


def test_each_missing_setting_key_is_reported_on_its_own_path() -> None:
    assert _problems(_setting()) == [
        ("data.key", "missing"),
        ("data.old_value", "missing"),
        ("data.new_value", "missing"),
    ]


def test_setting_changed_accepts_no_other_key() -> None:
    document = _setting(key="oversight.mode", old_value="guided", new_value="auto", why="x")
    assert _problems(document) == [("data.why", "unknown_key")]


@pytest.mark.parametrize("key", [7, None, True, ""])
def test_setting_key_is_non_empty_text(key: object) -> None:
    document = _setting(key=key, old_value="guided", new_value="auto")
    assert [field for field, _ in _problems(document)] == ["data.key"]


def test_types_without_defined_keys_accept_only_an_empty_object() -> None:
    for kind in EventType:
        # These types define keys of their own, tested separately.
        if kind in (
            EventType.SETTING_CHANGED,
            EventType.PROJECT_CREATED,
            EventType.LOG_REPAIRED,
            EventType.MODEL_CALL,
        ):
            continue
        document = _with(type=kind.value, data={})
        assert Event.from_json(json.dumps(document)).data == {}
        document = _with(type=kind.value, data={"first": 1, "second": "x"})
        assert _problems(document) == [
            ("data.first", "unknown_key"),
            ("data.second", "unknown_key"),
        ]


def test_data_rules_are_silent_when_the_type_is_itself_invalid() -> None:
    assert _problems(_with(type="coffee_break", data={"note": 1})) == [("type", "enum")]


def test_new_event_takes_status_reason_and_data() -> None:
    new = NewEvent(
        actor="human:alex",
        type=EventType.SETTING_CHANGED,
        status=EventStatus.OK,
        data={"key": "verification.enabled", "old_value": True, "new_value": False},
    )
    assert new.data["new_value"] is False
    refused = NewEvent(
        actor="system:utux",
        type=EventType.MODEL_CALL,
        status=EventStatus.REFUSED,
        status_reason="budget_exhausted",
        model="synthetic/model",
    )
    assert refused.status_reason == "budget_exhausted"


# data of log_repaired


def _repaired(**changes: object) -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / "log_repaired.json").read_text("utf-8"))
    assert isinstance(document, dict)
    document["data"] = {**document["data"], **changes}
    return document


def test_log_repaired_carries_file_hash_and_byte_length() -> None:
    event = load_event(FIXTURES / "valid" / "log_repaired.json")
    assert event.type is EventType.LOG_REPAIRED
    assert event.data == {
        "fragment_file": "events.jsonl.fragment-20261116T110712.125Z",
        "fragment_hash": SYNTHETIC_HASH,
        "fragment_bytes": 57,
    }


@pytest.mark.parametrize("value", [-1, 1.5, True, "57", None])
def test_fragment_bytes_is_a_whole_number_of_zero_or_more(value: object) -> None:
    assert _problems(_repaired(fragment_bytes=value)) == [("data.fragment_bytes", "int_type")]


@pytest.mark.parametrize("value", ["sha256:...", "md5:abc", "", 3])
def test_fragment_hash_is_a_content_hash(value: object) -> None:
    assert [field for field, _ in _problems(_repaired(fragment_hash=value))] == [
        "data.fragment_hash"
    ]


@pytest.mark.parametrize("value", ["", None, 4])
def test_fragment_file_is_non_empty_text(value: object) -> None:
    assert _problems(_repaired(fragment_file=value)) == [("data.fragment_file", "string_type")]


# data of model_call


def test_model_call_names_its_provider_and_whether_it_is_external() -> None:
    assert _problems(_with(data={})) == [
        ("data.provider", "missing"),
        ("data.is_external", "missing"),
    ]
    event = Event.from_json(json.dumps(_with(data={"provider": "ollama", "is_external": False})))
    assert event.data == {"provider": "ollama", "is_external": False}


@pytest.mark.parametrize("value", ["", None, 3, True])
def test_model_call_provider_is_non_empty_text(value: object) -> None:
    document = _with(data={"provider": value, "is_external": True})
    assert _problems(document) == [("data.provider", "string_type")]


@pytest.mark.parametrize("value", ["yes", 1, 0, None])
def test_model_call_is_external_is_a_boolean(value: object) -> None:
    document = _with(data={"provider": "openrouter", "is_external": value})
    assert _problems(document) == [("data.is_external", "bool_type")]


def test_model_call_accepts_no_other_data_key() -> None:
    document = _with(data={"provider": "openrouter", "is_external": True, "prompt": "x"})
    assert _problems(document) == [("data.prompt", "unknown_key")]
