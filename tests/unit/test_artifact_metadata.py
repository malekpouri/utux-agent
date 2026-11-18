"""M0-04: the artifact metadata sidecar schema."""

import json
import re
from pathlib import Path

import pytest

from utux.errors import ContractValidationError
from utux.schemas.artifact_metadata import (
    ArtifactMetadata,
    ArtifactState,
    load_artifact_metadata,
)
from utux.schemas.common import Stage

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "artifact_metadata"
VALID = sorted((FIXTURES / "valid").glob("*.json"))

# SHA-256 of b"synthetic fixture content\n", computed with sha256sum.
SYNTHETIC_HASH = "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"

# One row per invalid fixture: file name, the field the error must name, and
# the code. No (field, code) pair is repeated.
INVALID = [
    ("missing_content_hash.json", "content_hash", "missing"),
    ("missing_state.json", "state", "missing"),
    ("unknown_key.json", "owner", "unknown_key"),
    ("unknown_state.json", "state", "enum"),
    ("unknown_stage.json", "stage", "enum"),
    ("hash_not_sha256.json", "content_hash", "string_pattern_mismatch"),
    ("timestamp_without_z.json", "created_at", "utc_timestamp"),
    ("artifact_id_without_version.json", "artifact_id", "string_pattern_mismatch"),
    ("input_artifact_without_version.json", "input_artifacts.1", "string_pattern_mismatch"),
    ("input_artifacts_not_a_list.json", "input_artifacts", "tuple_type"),
    ("created_by_without_kind.json", "created_by", "string_pattern_mismatch"),
    ("input_artifact_is_itself.json", "input_artifacts.1", "self_reference"),
    ("input_artifact_repeated.json", "input_artifacts.2", "duplicate_input"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("not_an_object.json", "<document>", "not_a_mapping"),
    ("malformed_json.json", "<document>", "invalid_json"),
    ("duplicate_key.json", "state", "duplicate_key"),
    ("missing_path.json", "path", "missing"),
    ("path_absolute.json", "path", "not_relative_path"),
]


def _valid_document() -> dict[str, object]:
    document = json.loads((FIXTURES / "valid" / "with_inputs.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _validate(document: dict[str, object]) -> ArtifactMetadata:
    return ArtifactMetadata.from_json(json.dumps(document), source="sidecar.json")


def _problems(document: dict[str, object]) -> list[tuple[str, str]]:
    with pytest.raises(ContractValidationError) as caught:
        _validate(document)
    return [(p.field, p.code) for p in caught.value.problems]


# Valid documents


def test_valid_fixture_reads_every_field() -> None:
    metadata = load_artifact_metadata(FIXTURES / "valid" / "with_inputs.json")
    assert metadata.artifact_id == "method-v003"
    assert metadata.stage is Stage.METHODOLOGY
    assert metadata.schema_version == 1
    assert metadata.created_by == "agent:methodologist"
    assert metadata.created_at == "2026-11-15T10:00:00Z"
    assert metadata.input_artifacts == ("idea-v002", "literature-v004")
    assert metadata.path == "method.md"
    assert metadata.content_hash == SYNTHETIC_HASH
    assert metadata.state is ArtifactState.VALID


def test_artifact_without_inputs_is_valid() -> None:
    metadata = load_artifact_metadata(FIXTURES / "valid" / "no_inputs_stale.json")
    assert metadata.input_artifacts == ()
    assert metadata.state is ArtifactState.STALE
    assert metadata.created_by == "human:alex"


def test_every_field_is_required() -> None:
    for field in ArtifactMetadata.model_fields:
        document = _valid_document()
        del document[field]
        assert _problems(document) == [(field, "missing")]


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_json(path: Path) -> None:
    metadata = load_artifact_metadata(path)
    again = ArtifactMetadata.from_json(metadata.to_json())
    assert again == metadata
    assert again.to_json() == metadata.to_json()
    # Field values, including the timestamp text, come back unchanged.
    assert json.loads(metadata.to_json()) == json.loads(path.read_text(encoding="utf-8"))


def test_there_are_valid_fixtures() -> None:
    assert len(VALID) >= 2


# The example of the specification


def test_specification_example_validates() -> None:
    """The sidecar example of docs/spec.md, section 7, is a valid sidecar.

    The example elides the digest as "sha256:...". That placeholder is the
    one thing replaced here, with a synthetic digest; everything else is
    validated as written in the specification.
    """
    spec = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    section = spec.split("### Artifact metadata and validity", 1)[1]
    match = re.search(r"```json\n(.*?)```", section, flags=re.DOTALL)
    assert match is not None
    example = match.group(1)
    assert example.count('"sha256:..."') == 1
    metadata = ArtifactMetadata.from_json(
        example.replace('"sha256:..."', f'"{SYNTHETIC_HASH}"'), source="docs/spec.md"
    )
    assert metadata.artifact_id == "method-v003"
    assert metadata.stage is Stage.METHODOLOGY
    assert metadata.created_by == "agent:methodologist"
    assert metadata.created_at == "2026-11-15T10:00:00Z"
    assert metadata.input_artifacts == ("idea-v002", "literature-v004")
    assert metadata.path == "method.md"
    assert metadata.state is ArtifactState.VALID


def test_elided_digest_of_the_specification_is_not_a_hash() -> None:
    document = _valid_document()
    document["content_hash"] = "sha256:..."
    assert _problems(document) == [("content_hash", "string_pattern_mismatch")]


# State


def test_state_accepts_only_the_documented_values() -> None:
    assert {state.value for state in ArtifactState} == {"valid", "stale"}
    for value in ("valid", "stale"):
        document = _valid_document()
        document["state"] = value
        assert _validate(document).state.value == value
    for value in ("VALID", "invalid", "pending", "", None, True):
        document = _valid_document()
        document["state"] = value
        assert [field for field, _ in _problems(document)] == ["state"]


# Timestamps


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-15T10:00:00",  # no zone
        "2026-11-15T10:00:00+00:00",  # UTC, but not written with Z
        "2026-11-15T13:30:00+03:30",  # not UTC
        "2026-11-15 10:00:00Z",  # no T
        "2026-11-15T10:00Z",  # no seconds
        "2026-02-30T10:00:00Z",  # no such day
        "2026-11-15T25:00:00Z",  # no such hour
        "2026-11-15",
    ],
)
def test_timestamp_must_be_utc_iso_8601_with_z(value: str) -> None:
    document = _valid_document()
    document["created_at"] = value
    assert _problems(document) == [("created_at", "utc_timestamp")]


def test_timestamp_may_have_fractional_seconds() -> None:
    document = _valid_document()
    document["created_at"] = "2026-11-15T10:00:00.123456Z"
    assert _validate(document).created_at == "2026-11-15T10:00:00.123456Z"


# Hashes and identifiers


@pytest.mark.parametrize(
    "value",
    [
        SYNTHETIC_HASH.removeprefix("sha256:"),  # no algorithm prefix
        SYNTHETIC_HASH.upper(),
        SYNTHETIC_HASH[:-1],  # one character short
        SYNTHETIC_HASH + "0",
        "sha256:" + "g" * 64,
    ],
)
def test_content_hash_must_be_a_full_lower_case_sha256(value: str) -> None:
    document = _valid_document()
    document["content_hash"] = value
    assert _problems(document) == [("content_hash", "string_pattern_mismatch")]


@pytest.mark.parametrize("value", ["method", "method-v3", "Method-v003", "-v003", "method v003"])
def test_artifact_id_needs_a_name_and_a_version(value: str) -> None:
    document = _valid_document()
    document["artifact_id"] = value
    assert _problems(document) == [("artifact_id", "string_pattern_mismatch")]


def test_each_bad_input_artifact_is_reported_on_its_own_position() -> None:
    document = _valid_document()
    document["input_artifacts"] = ["idea", "literature-v004", "plan"]
    assert _problems(document) == [
        ("input_artifacts.0", "string_pattern_mismatch"),
        ("input_artifacts.2", "string_pattern_mismatch"),
    ]


@pytest.mark.parametrize("value", ["methodologist", "robot:x", "agent:", "agent:Has Space", ":x"])
def test_created_by_needs_a_known_kind_and_a_name(value: str) -> None:
    document = _valid_document()
    document["created_by"] = value
    assert _problems(document) == [("created_by", "string_pattern_mismatch")]


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
        load_artifact_metadata(path)
    error = caught.value
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    assert error.source == str(path)
    assert str(error) == f"{path}: {field}: {error.problems[0].reason}"


def test_missing_file_is_a_typed_error_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(ContractValidationError) as caught:
        load_artifact_metadata(path)
    assert [(p.field, p.code) for p in caught.value.problems] == [("<document>", "unreadable")]
    assert str(path) in str(caught.value)


def test_json_constants_that_are_not_json_are_rejected() -> None:
    with pytest.raises(ContractValidationError) as caught:
        ArtifactMetadata.from_json('{"schema_version": NaN}', source="sidecar.json")
    assert [(p.field, p.code) for p in caught.value.problems] == [("<document>", "invalid_json")]


# Actors


@pytest.mark.parametrize("value", ["agent:methodologist", "human:alex", "system:utux"])
def test_created_by_accepts_the_three_kinds_of_actor(value: str) -> None:
    document = _valid_document()
    document["created_by"] = value
    assert _validate(document).created_by == value


def test_system_actor_fixture_is_valid() -> None:
    metadata = load_artifact_metadata(FIXTURES / "valid" / "created_by_system.json")
    assert metadata.created_by == "system:utux"


# Rules across input_artifacts


def test_an_artifact_cannot_list_itself_as_input() -> None:
    document = _valid_document()
    document["input_artifacts"] = ["method-v003", "idea-v002", "method-v003"]
    assert _problems(document) == [
        ("input_artifacts.0", "self_reference"),
        ("input_artifacts.2", "self_reference"),
    ]


def test_each_repeated_input_is_reported_on_its_own_position() -> None:
    document = _valid_document()
    document["input_artifacts"] = [
        "idea-v002",
        "literature-v004",
        "idea-v002",
        "plan-v001",
        "literature-v004",
        "idea-v002",
    ]
    # The first occurrence is kept; every later one is a problem.
    assert _problems(document) == [
        ("input_artifacts.2", "duplicate_input"),
        ("input_artifacts.4", "duplicate_input"),
        ("input_artifacts.5", "duplicate_input"),
    ]


def test_repeated_input_reason_names_the_entry_and_its_first_position() -> None:
    document = _valid_document()
    document["input_artifacts"] = ["idea-v002", "literature-v004", "idea-v002"]
    with pytest.raises(ContractValidationError) as caught:
        _validate(document)
    assert caught.value.problems[0].reason == "idea-v002 is already listed at position 0"


def test_different_versions_of_one_artifact_are_not_duplicates() -> None:
    document = _valid_document()
    document["input_artifacts"] = ["idea-v001", "idea-v002"]
    assert _validate(document).input_artifacts == ("idea-v001", "idea-v002")


def test_input_rules_are_silent_when_artifact_id_is_itself_invalid() -> None:
    document = _valid_document()
    document["artifact_id"] = "method"
    document["input_artifacts"] = ["idea-v002", "idea-v002"]
    assert _problems(document) == [("artifact_id", "string_pattern_mismatch")]


def test_the_example_of_the_documentation_is_a_valid_sidecar() -> None:
    """The complete sidecar in docs/artifact-metadata.md validates (M1 rule 2)."""
    text = (REPO_ROOT / "docs" / "artifact-metadata.md").read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)```", text, flags=re.DOTALL)
    assert match is not None
    metadata = ArtifactMetadata.from_json(match.group(1), source="docs/artifact-metadata.md")
    assert metadata.path == "method.md"
    assert metadata.content_hash == SYNTHETIC_HASH
