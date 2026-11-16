"""M0-06a: the result record schema (specification, section 7)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError
from utux.schemas.result_record import ResultRecord, load_result_record

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "result_record"
VALID = sorted((FIXTURES / "valid").glob("*.json"))

FIELDS = [
    "schema_version",
    "id",
    "metric",
    "value",
    "unit",
    "dataset",
    "model",
    "split",
    "run_id",
    "source",
    "tolerance",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("missing_unit.json", "unit", "missing"),
    ("missing_tolerance.json", "tolerance", "missing"),
    ("missing_model.json", "model", "missing"),
    ("missing_split.json", "split", "missing"),
    ("unknown_key.json", "note", "unknown_key"),
    ("value_is_text.json", "value", "float_type"),
    ("negative_tolerance.json", "tolerance", "greater_than_equal"),
    ("empty_metric.json", "metric", "string_too_short"),
    ("record_id_malformed.json", "id", "string_pattern_mismatch"),
    ("run_id_malformed.json", "run_id", "string_pattern_mismatch"),
    ("source_outside_project.json", "source", "not_relative_path"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def _record(**changes: Any) -> dict[str, Any]:
    document = json.loads((FIXTURES / "valid" / "auc.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return {**document, **changes}


def _problems(document: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        ResultRecord.from_json(json.dumps(document), source="results.jsonl:1")
    return [(p.field, p.code) for p in caught.value.problems]


def test_specification_example_validates_unchanged() -> None:
    spec = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    section = spec.split("### Result records", 1)[1]
    match = re.search(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert match is not None
    example = match.group(1)
    assert sorted(json.loads(example)) == sorted(FIELDS)
    record = ResultRecord.from_json(example, source="docs/spec.md")
    assert record.id == "R0042"
    assert record.metric == "AUC"
    assert record.value == 0.95
    assert record.unit == "score"
    assert record.dataset == "dataset_x"
    assert record.model == "model_a"
    assert record.split == "test"
    assert record.run_id == "r012"
    assert record.source == "runs/r012/metrics.json"
    assert record.tolerance == 0.005


def test_record_has_exactly_the_fields_of_the_specification() -> None:
    assert sorted(ResultRecord.model_fields) == sorted(FIELDS)


def test_a_number_is_never_stored_bare() -> None:
    """Every field that gives the value its meaning is required."""
    for field in FIELDS:
        document = _record()
        del document[field]
        assert _problems(document) == [(field, "missing")]


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    record = load_result_record(path)
    line = record.to_json_line()
    again = ResultRecord.from_json(line)
    assert again == record
    assert again.to_json_line() == line
    assert line.count("\n") == 1
    assert json.loads(line) == json.loads(path.read_text(encoding="utf-8"))


def test_there_are_valid_fixtures() -> None:
    assert len(VALID) >= 2


@pytest.mark.parametrize("value", [0, -3, 1e-9, 12345.678])
def test_value_may_be_any_finite_number(value: float) -> None:
    assert ResultRecord.from_json(json.dumps(_record(value=value))).value == value


@pytest.mark.parametrize("value", ["0.95", True, None, [0.95]])
def test_value_must_be_a_number(value: object) -> None:
    assert [field for field, _ in _problems(_record(value=value))] == ["value"]


def test_tolerance_may_be_zero_for_an_exact_value() -> None:
    assert ResultRecord.from_json(json.dumps(_record(tolerance=0))).tolerance == 0.0


@pytest.mark.parametrize("field", ["metric", "unit", "dataset", "run_id"])
def test_meaning_fields_may_not_be_empty_or_null(field: str) -> None:
    assert [name for name, _ in _problems(_record(**{field: ""}))] == [field]
    assert [name for name, _ in _problems(_record(**{field: None}))] == [field]


@pytest.mark.parametrize("field", ["model", "split"])
def test_model_and_split_are_required_but_may_be_null(field: str) -> None:
    """A value such as a dataset statistic has no model and no split."""
    record = ResultRecord.from_json(json.dumps(_record(**{field: None})))
    assert getattr(record, field) is None
    # Null is stated; the field is not left out, and it is not empty text.
    assert ResultRecord.model_fields[field].is_required()
    assert [name for name, _ in _problems(_record(**{field: ""}))] == [field]


def test_record_without_model_or_split_fixture() -> None:
    record = load_result_record(
        FIXTURES / "valid" / "dataset_statistic_without_model_or_split.json"
    )
    assert record.model is None
    assert record.split is None
    assert record.value == 1200


@pytest.mark.parametrize("value", ["r0042", "R42", "C017", "R0042x"])
def test_record_id_is_r_and_at_least_three_digits(value: str) -> None:
    assert _problems(_record(id=value)) == [("id", "string_pattern_mismatch")]


@pytest.mark.parametrize("path", ["/tmp/metrics.json", "../metrics.json", "runs/../../x.json"])
def test_source_stays_inside_the_project(path: str) -> None:
    assert _problems(_record(source=path)) == [("source", "not_relative_path")]


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
        load_result_record(path)
    error = caught.value
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    assert error.source == str(path)
    assert str(error) == f"{path}: {field}: {error.problems[0].reason}"


@pytest.mark.parametrize("value", ["12", "run-12", "R012", "r12", "r012x"])
def test_run_id_has_the_form_of_a_run_manifest_id(value: str) -> None:
    assert _problems(_record(run_id=value)) == [("run_id", "string_pattern_mismatch")]


def test_result_record_and_run_manifest_share_the_run_id_type() -> None:
    from utux.schemas.run_manifest import RunManifest

    record_field = ResultRecord.model_fields["run_id"]
    manifest_field = RunManifest.model_fields["run_id"]
    assert record_field.annotation is str
    assert record_field.metadata == manifest_field.metadata
    assert record_field.metadata  # the pattern is there
