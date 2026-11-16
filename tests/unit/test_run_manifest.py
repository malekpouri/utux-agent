"""M0-06b: the run manifest schema."""

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

from utux.schemas.run_manifest import RunManifest, load_run_manifest

CONTRACT = "run_manifest"

# One field or group per item of the specification, section 7, "Run manifest".
FIELDS = [
    "schema_version",
    "run_id",
    "command",
    "parameters",
    "config_files",
    "git",
    "container",
    "datasets",
    "seeds",
    "hardware",
    "models",
    "external_services",
    "outputs",
    "started_at",
    "ended_at",
    "exit_status",
]

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID: list[Row] = [
    ("missing_seeds.json", "seeds", "missing"),
    ("missing_exit_status.json", "exit_status", "missing"),
    ("missing_outputs.json", "outputs", "missing"),
    ("output_outside_project.json", "outputs.0.path", "not_relative_path"),
    ("unknown_key.json", "notes", "unknown_key"),
    ("empty_command.json", "command", "too_short"),
    ("command_is_a_shell_string.json", "command", "tuple_type"),
    ("run_id_malformed.json", "run_id", "string_pattern_mismatch"),
    ("git_commit_abbreviated.json", "git.commit", "string_pattern_mismatch"),
    ("git_dirty_not_boolean.json", "git.dirty", "bool_type"),
    ("image_digest_is_a_tag.json", "container.image_digest", "string_pattern_mismatch"),
    ("config_file_outside_project.json", "config_files.0.path", "not_relative_path"),
    ("dataset_file_hash_elided.json", "datasets.0.files.0.hash", "string_pattern_mismatch"),
    ("dataset_without_version.json", "datasets.0.version", "missing"),
    ("parameter_is_nested.json", "parameters.optimizer", "not_scalar"),
    ("seed_is_not_an_integer.json", "seeds.numpy", "int_type"),
    ("exit_status_is_text.json", "exit_status", "int_type"),
    ("ended_before_started.json", "ended_at", "ended_before_started"),
    ("gpu_without_cuda_version.json", "hardware.cuda_version", "required_with_gpu"),
    ("cuda_version_without_gpu.json", "hardware.cuda_version", "not_allowed_without_gpu"),
    ("zero_cpu_count.json", "hardware.cpu_count", "greater_than"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def _manifest(**changes: Any) -> dict[str, Any]:
    return {**read_valid(CONTRACT, "cpu_run.json"), **changes}


def _validate(document: dict[str, Any]) -> RunManifest:
    return RunManifest.from_json(json.dumps(document))


def test_manifest_has_the_proposed_fields() -> None:
    assert sorted(RunManifest.model_fields) == sorted(FIELDS)


def test_every_field_is_required() -> None:
    for field in FIELDS:
        document = _manifest()
        del document[field]
        assert problems(RunManifest, document) == [(field, "missing")]


def test_cpu_run_reads_every_group() -> None:
    manifest = load_run_manifest(valid_paths(CONTRACT)[0])
    assert manifest.run_id == "r012"
    assert manifest.command == ("python", "code/train.py", "--config", "code/config.yaml")
    assert manifest.parameters == {
        "learning_rate": 0.001,
        "epochs": 20,
        "scheduler": "cosine",
        "augment": True,
    }
    assert manifest.config_files[0].path == "code/config.yaml"
    assert manifest.git.commit == "0123456789abcdef0123456789abcdef01234567"
    assert manifest.git.dirty is False
    assert manifest.container.locked_packages == {"numpy": "2.1.0", "scikit-learn": "1.5.2"}
    assert manifest.datasets[0].name == "dataset_x"
    assert manifest.datasets[0].version == "1.0"
    assert manifest.datasets[0].obtained_from == "synthetic public archive"
    assert manifest.datasets[0].files[0].path == "inputs/dataset_x/train.csv"
    assert manifest.seeds == {"python": 0, "numpy": 0}
    assert manifest.hardware.cpu_count == 8
    assert manifest.hardware.gpu is None
    assert manifest.models == ()
    assert manifest.external_services == ()
    assert manifest.outputs[0].path == "runs/r012/metrics.json"
    assert manifest.outputs[0].hash.startswith("sha256:")
    assert manifest.started_at == "2026-11-15T10:00:00Z"
    assert manifest.ended_at == "2026-11-15T10:14:30Z"
    assert manifest.exit_status == 0


def test_gpu_run_records_cuda_driver_models_and_services() -> None:
    manifest = load_run_manifest(valid_paths(CONTRACT)[2])
    assert manifest.hardware.gpu == "synthetic GPU 24 GB"
    assert manifest.hardware.cuda_version == "12.4"
    assert manifest.hardware.driver_version == "550.54"
    assert manifest.models[0].model == "synthetic/model"
    assert manifest.models[0].settings == {"temperature": 0, "max_output_tokens": 512}
    assert manifest.external_services[0].name == "synthetic-data-api"
    assert manifest.git.dirty is True
    assert manifest.exit_status == 1


def test_gpu_needs_both_cuda_and_driver_versions() -> None:
    hardware = {**_manifest()["hardware"], "gpu": "synthetic GPU"}
    assert problems(RunManifest, _manifest(hardware=hardware)) == [
        ("hardware.cuda_version", "required_with_gpu"),
        ("hardware.driver_version", "required_with_gpu"),
    ]


def test_no_gpu_allows_neither_cuda_nor_driver_version() -> None:
    hardware = {**_manifest()["hardware"], "cuda_version": "12.4", "driver_version": "550.54"}
    assert problems(RunManifest, _manifest(hardware=hardware)) == [
        ("hardware.cuda_version", "not_allowed_without_gpu"),
        ("hardware.driver_version", "not_allowed_without_gpu"),
    ]


def test_run_may_end_at_the_moment_it_started() -> None:
    document = _manifest(ended_at="2026-11-15T10:00:00Z")
    assert _validate(document).ended_at == "2026-11-15T10:00:00Z"


def test_times_are_compared_as_times_not_as_text() -> None:
    # As text, ".5Z" sorts before "Z"; as times it is half a second later.
    document = _manifest(started_at="2026-11-15T10:00:00Z", ended_at="2026-11-15T10:00:00.5Z")
    assert _validate(document).ended_at == "2026-11-15T10:00:00.5Z"
    document = _manifest(started_at="2026-11-15T10:00:00.5Z", ended_at="2026-11-15T10:00:00Z")
    assert problems(RunManifest, document) == [("ended_at", "ended_before_started")]


@pytest.mark.parametrize("status", [0, 1, 137, -9])
def test_exit_status_is_any_integer(status: int) -> None:
    assert _validate(_manifest(exit_status=status)).exit_status == status


@pytest.mark.parametrize("value", [{"a": 1}, [1, 2]])
@pytest.mark.parametrize("group", ["parameters", "settings"])
def test_parameters_and_model_settings_are_flat(group: str, value: object) -> None:
    if group == "parameters":
        document = _manifest(parameters={"good": 1, "bad": value})
        expected = "parameters.bad"
    else:
        document = _manifest(
            models=[{"model": "synthetic/model", "version": None, "settings": {"bad": value}}]
        )
        expected = "models.0.settings.bad"
    assert problems(RunManifest, document) == [(expected, "not_scalar")]


def test_each_bad_file_reference_is_reported_on_its_own_path() -> None:
    document = _manifest(
        config_files=[
            {"path": "code/a.yaml", "hash": "sha256:..."},
            {"path": "../b.yaml", "hash": _manifest()["config_files"][0]["hash"]},
        ]
    )
    assert problems(RunManifest, document) == [
        ("config_files.0.hash", "string_pattern_mismatch"),
        ("config_files.1.path", "not_relative_path"),
    ]


@pytest.mark.parametrize("path", valid_paths(CONTRACT), ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    check_round_trip(RunManifest, load_run_manifest, path)


def test_invalid_fixture_table() -> None:
    check_table(CONTRACT, INVALID)


@pytest.mark.parametrize("row", INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(CONTRACT, load_run_manifest, row)


def test_run_that_produced_no_file_has_empty_outputs() -> None:
    assert _validate(_manifest(outputs=[])).outputs == ()
    assert load_run_manifest(valid_paths(CONTRACT)[1]).outputs == ()
