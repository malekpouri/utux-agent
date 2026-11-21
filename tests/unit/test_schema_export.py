"""M0-06b: export of one JSON Schema file per contract."""

import importlib
import json
import pkgutil
from pathlib import Path

import jsonschema
import pytest
import yaml

import utux.schemas
from utux.errors import SchemaExportError, UtuxError
from utux.schemas.base import ContractDocument
from utux.schemas.export import CONTRACTS, export_json_schemas

EXPECTED = {
    "project_config",
    "artifact_metadata",
    "event",
    "claim_ledger_entry",
    "result_record",
    "run_manifest",
    "approval_request",
    "approval_response",
    "source_record",
    "gold_item",
    "metrics",
}


def _all_contract_models() -> set[type[ContractDocument]]:
    for module in pkgutil.iter_modules(utux.schemas.__path__):
        importlib.import_module(f"utux.schemas.{module.name}")
    return set(ContractDocument.__subclasses__())


def test_registry_names_every_contract() -> None:
    assert set(CONTRACTS) == EXPECTED


def test_every_contract_model_in_the_package_is_registered() -> None:
    """A schema added later cannot be forgotten by the export."""
    assert set(CONTRACTS.values()) == _all_contract_models()
    assert len(set(CONTRACTS.values())) == len(CONTRACTS)


def test_export_writes_one_file_per_contract(tmp_path: Path) -> None:
    written = export_json_schemas(tmp_path)
    assert sorted(path.name for path in written) == sorted(
        f"{name}.schema.json" for name in EXPECTED
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(path.name for path in written)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_exported_file_is_a_json_schema_of_its_contract(tmp_path: Path, name: str) -> None:
    export_json_schemas(tmp_path)
    schema = json.loads((tmp_path / f"{name}.schema.json").read_text(encoding="utf-8"))
    model = CONTRACTS[name]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == model.__name__
    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(model.model_fields)
    assert set(schema["required"]) == {
        field for field, info in model.model_fields.items() if info.is_required()
    }
    assert "schema_version" in schema["required"]
    # Unknown keys are errors in every contract.
    assert schema["additionalProperties"] is False


def test_export_is_deterministic_and_ends_files_with_a_newline(tmp_path: Path) -> None:
    first = {path.name: path.read_bytes() for path in export_json_schemas(tmp_path / "a")}
    second = {path.name: path.read_bytes() for path in export_json_schemas(tmp_path / "b")}
    assert first == second
    assert all(content.endswith(b"\n") for content in first.values())


def test_export_creates_the_directory_and_replaces_existing_files(tmp_path: Path) -> None:
    target = tmp_path / "does" / "not" / "exist"
    export_json_schemas(target)
    stale = target / "event.schema.json"
    expected = stale.read_bytes()
    stale.write_text("stale", encoding="utf-8")
    other = target / "keep-me.txt"
    other.write_text("not a schema", encoding="utf-8")
    export_json_schemas(target)
    assert stale.read_bytes() == expected
    # Files the export does not own are left alone.
    assert other.read_text(encoding="utf-8") == "not a schema"


def test_export_leaves_no_temporary_files(tmp_path: Path) -> None:
    export_json_schemas(tmp_path)
    assert all(path.name.endswith(".schema.json") for path in tmp_path.iterdir())


def test_export_to_a_path_that_is_a_file_is_a_typed_error(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(SchemaExportError, match=r"file\.txt"):
        export_json_schemas(target)
    assert issubclass(SchemaExportError, UtuxError)
    assert target.read_text(encoding="utf-8") == "x"


def test_evidence_schema_lists_the_three_entry_types(tmp_path: Path) -> None:
    export_json_schemas(tmp_path)
    schema = json.loads((tmp_path / "claim_ledger_entry.schema.json").read_text(encoding="utf-8"))
    items = schema["properties"]["evidence"]["items"]
    assert len(items["oneOf"]) == 3
    assert set(items["discriminator"]["mapping"]) == {"source", "result_record", "claim"}


# The exported files work with a JSON Schema validator

FIXTURE_DIRECTORY = {
    "project_config": "project_config",
    "artifact_metadata": "artifact_metadata",
    "event": "event",
    "claim_ledger_entry": "claim_ledger",
    "result_record": "result_record",
    "run_manifest": "run_manifest",
    "approval_request": "approval_request",
    "approval_response": "approval_response",
    "source_record": "source_record",
    "gold_item": "gold_item",
    "metrics": "metrics",
}
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOTE = (
    "utux applies further rules between fields; "
    "passing this schema is necessary but not sufficient."
)


def _exported(tmp_path: Path, name: str) -> dict[str, object]:
    export_json_schemas(tmp_path)
    schema = json.loads((tmp_path / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert isinstance(schema, dict)
    return schema


def _valid_fixtures(name: str) -> list[Path]:
    return sorted((FIXTURES / FIXTURE_DIRECTORY[name] / "valid").iterdir())


def _read(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if path.suffix == ".yaml" else json.loads(text)


def test_every_contract_has_valid_fixtures_to_check() -> None:
    assert set(FIXTURE_DIRECTORY) == EXPECTED
    for name in EXPECTED:
        assert len(_valid_fixtures(name)) >= 2


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_exported_file_is_itself_a_valid_json_schema(tmp_path: Path, name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(_exported(tmp_path, name))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_valid_fixture_passes_its_exported_schema(tmp_path: Path, name: str) -> None:
    validator = jsonschema.Draft202012Validator(_exported(tmp_path, name))
    for path in _valid_fixtures(name):
        errors = [error.message for error in validator.iter_errors(_read(path))]
        assert errors == [], f"{path.name}: {errors}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_exported_schema_refuses_an_unknown_key_and_a_missing_version(
    tmp_path: Path, name: str
) -> None:
    """The validator is really applied: a broken document does not pass."""
    validator = jsonschema.Draft202012Validator(_exported(tmp_path, name))
    document = _read(_valid_fixtures(name)[0])
    assert isinstance(document, dict)
    assert not validator.is_valid({**document, "not_a_field": 1})
    without_version = {key: value for key, value in document.items() if key != "schema_version"}
    assert not validator.is_valid(without_version)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_description_says_that_the_schema_is_not_sufficient(tmp_path: Path, name: str) -> None:
    description = _exported(tmp_path, name)["description"]
    assert isinstance(description, str)
    assert description.endswith(NOTE)
    # The model's own description is kept in front of the note.
    assert len(description) > len(NOTE)
