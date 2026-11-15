"""M0-03: the `utux.yaml` project configuration schema."""

from pathlib import Path

import pytest
import yaml

from utux.errors import ContractValidationError, UtuxError
from utux.schemas.common import Stage, Tier
from utux.schemas.project_config import (
    DataPolicy,
    Gate,
    OversightMode,
    ProjectConfig,
    load_project_config,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "project_config"
VALID = sorted((FIXTURES / "valid").glob("*.yaml"))

# One row per invalid fixture: file name, the field the error must name, and
# the reason code. Every fixture fails for a different reason; the test below
# checks that no (field, code) pair is repeated.
INVALID = [
    ("missing_data_policy.yaml", "data_policy", "missing"),
    ("missing_schema_version.yaml", "schema_version", "missing"),
    ("missing_total_budget.yaml", "budget.total_usd", "missing"),
    ("unknown_top_level_key.yaml", "colour", "unknown_key"),
    ("unknown_nested_key.yaml", "oversight.gatez", "unknown_key"),
    ("final_gate_switched_off.yaml", "oversight.gates.final_manuscript", "final_gate_off"),
    ("unknown_oversight_mode.yaml", "oversight.mode", "enum"),
    ("unknown_data_policy.yaml", "data_policy", "enum"),
    ("negative_total_budget.yaml", "budget.total_usd", "greater_than"),
    ("unknown_stage_in_budget.yaml", "budget.per_stage_usd.cooking", "enum"),
    ("unknown_tier_for_role.yaml", "models.roles.writer", "enum"),
    ("verification_not_boolean.yaml", "verification.enabled", "bool_type"),
    ("newer_schema_version.yaml", "schema_version", "schema_version_newer"),
    ("not_a_mapping.yaml", "<document>", "not_a_mapping"),
    ("duplicate_key.yaml", "data_policy", "duplicate_key"),
    ("malformed_yaml.yaml", "<document>", "invalid_yaml"),
]


def _minimal() -> ProjectConfig:
    return load_project_config(FIXTURES / "valid" / "minimal.yaml")


# Minimal file and defaults


def test_minimal_file_validates_and_fills_documented_defaults() -> None:
    config = _minimal()
    assert config.schema_version == 1
    assert config.data_policy is DataPolicy.LOCAL_ONLY
    assert config.budget.total_usd == 20.0
    # Documented defaults.
    assert config.profile == "default"
    assert config.domain_pack == "generic"
    assert config.budget.per_stage_usd == {}
    assert config.oversight.mode is OversightMode.GUIDED
    assert config.verification.enabled is True
    assert config.ai_disclosure.draft is True
    assert config.resources.cpus is None
    assert config.resources.memory_mb is None
    assert config.resources.gpus is None
    assert config.resources.wall_clock_seconds is None
    assert config.resources.disk_mb is None
    assert config.resources.max_processes is None
    assert config.models.tiers == {}
    assert config.models.roles == {}


def test_minimal_fixture_holds_only_the_required_fields() -> None:
    document = yaml.safe_load((FIXTURES / "valid" / "minimal.yaml").read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "data_policy": "local_only",
        "budget": {"total_usd": 20},
    }


def test_data_policy_has_no_default() -> None:
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(FIXTURES / "invalid" / "missing_data_policy.yaml")
    assert [(p.field, p.code) for p in caught.value.problems] == [("data_policy", "missing")]


def test_guided_mode_switches_every_gate_on() -> None:
    oversight = _minimal().oversight
    assert all(oversight.gate_enabled(gate) for gate in Gate)


def test_auto_mode_keeps_only_the_final_gate_unless_overridden() -> None:
    config = ProjectConfig.from_yaml(
        "schema_version: 1\ndata_policy: local_only\nbudget: {total_usd: 1}\n"
        "oversight: {mode: auto}\n"
    )
    enabled = {gate: config.oversight.gate_enabled(gate) for gate in Gate}
    assert enabled == {
        Gate.IDEA: False,
        Gate.METHOD: False,
        Gate.EXPERIMENT_PLAN: False,
        Gate.FINAL_MANUSCRIPT: True,
    }


def test_full_file_reads_every_field() -> None:
    config = load_project_config(FIXTURES / "valid" / "full.yaml")
    assert config.profile == "local"
    assert config.domain_pack == "bio-pilot"
    assert config.data_policy is DataPolicy.EXTERNAL_ALLOWED
    assert config.budget.per_stage_usd[Stage.EXPERIMENT] == 20.0
    assert set(config.budget.per_stage_usd) == set(Stage)
    assert config.oversight.mode is OversightMode.AUTO
    # Per-gate switches override the mode.
    assert config.oversight.gate_enabled(Gate.IDEA) is True
    assert config.oversight.gate_enabled(Gate.METHOD) is False
    assert config.oversight.gate_enabled(Gate.EXPERIMENT_PLAN) is True
    assert config.oversight.gate_enabled(Gate.FINAL_MANUSCRIPT) is True
    assert config.verification.enabled is False
    assert config.ai_disclosure.draft is False
    assert config.resources.cpus == 4
    assert config.resources.wall_clock_seconds == 3600
    assert config.models.tiers[Tier.STRONG] == "example/strong-model"
    assert config.models.roles == {
        "planner": Tier.STRONG,
        "writer": Tier.STANDARD,
        "summariser": Tier.LIGHT,
    }


# Round trip


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_round_trip_through_yaml(path: Path) -> None:
    config = load_project_config(path)
    again = ProjectConfig.from_yaml(config.to_yaml())
    assert again == config
    assert again.to_yaml() == config.to_yaml()


def test_there_are_valid_fixtures() -> None:
    assert len(VALID) >= 2


# Invalid documents


def test_at_least_five_invalid_fixtures_with_distinct_reasons() -> None:
    reasons = [(field, code) for _, field, code in INVALID]
    assert len(INVALID) >= 5
    assert len(set(reasons)) == len(reasons)


def test_every_invalid_fixture_is_listed() -> None:
    on_disk = sorted(path.name for path in (FIXTURES / "invalid").glob("*.yaml"))
    assert on_disk == sorted(name for name, _, _ in INVALID)


@pytest.mark.parametrize(("name", "field", "code"), INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(name: str, field: str, code: str) -> None:
    path = FIXTURES / "invalid" / name
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(path)
    error = caught.value
    # Each fixture is wrong in exactly one way.
    assert [(p.field, p.code) for p in error.problems] == [(field, code)]
    # The message names the file, the field and the reason.
    assert error.source == str(path)
    problem = error.problems[0]
    assert problem.reason
    assert str(error) == f"{path}: {field}: {problem.reason}"


def test_validation_error_is_a_utux_error() -> None:
    assert issubclass(ContractValidationError, UtuxError)


def test_unknown_key_is_named_in_the_message() -> None:
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(FIXTURES / "invalid" / "unknown_top_level_key.yaml")
    assert "colour" in str(caught.value)
    assert "unknown key" in str(caught.value)


def test_final_gate_message_says_it_cannot_be_switched_off() -> None:
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(FIXTURES / "invalid" / "final_gate_switched_off.yaml")
    assert "final-manuscript gate" in str(caught.value)
    assert "cannot be switched off" in str(caught.value)


def test_final_gate_may_be_stated_as_on() -> None:
    config = ProjectConfig.from_yaml(
        "schema_version: 1\ndata_policy: local_only\nbudget: {total_usd: 1}\n"
        "oversight: {gates: {final_manuscript: true}}\n"
    )
    assert config.oversight.gate_enabled(Gate.FINAL_MANUSCRIPT) is True


def test_newer_schema_version_is_reported_alone_and_says_so() -> None:
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(FIXTURES / "invalid" / "newer_schema_version.yaml")
    # The unknown key in that fixture is not reported: a newer file cannot be
    # judged by an older schema.
    assert len(caught.value.problems) == 1
    assert "newer" in caught.value.problems[0].reason


def test_older_schema_version_is_rejected() -> None:
    with pytest.raises(ContractValidationError) as caught:
        ProjectConfig.from_yaml("schema_version: 0\ndata_policy: local_only\n")
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("schema_version", "schema_version_unsupported")
    ]


def test_all_problems_are_reported_not_only_the_first() -> None:
    with pytest.raises(ContractValidationError) as caught:
        ProjectConfig.from_yaml(
            "schema_version: 1\nbudget: {total_usd: 0}\nsurprise: 1\n", source="inline.yaml"
        )
    assert sorted((p.field, p.code) for p in caught.value.problems) == [
        ("budget.total_usd", "greater_than"),
        ("data_policy", "missing"),
        ("surprise", "unknown_key"),
    ]
    assert str(caught.value).splitlines() == [
        f"inline.yaml: {p.field}: {p.reason}" for p in caught.value.problems
    ]


def test_missing_file_is_a_typed_error_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "utux.yaml"
    with pytest.raises(ContractValidationError) as caught:
        load_project_config(path)
    assert [(p.field, p.code) for p in caught.value.problems] == [("<document>", "unreadable")]
    assert str(path) in str(caught.value)


def test_config_is_immutable() -> None:
    config = _minimal()
    with pytest.raises(Exception, match="frozen"):
        config.profile = "local"  # type: ignore[misc]


def test_yaml_that_asks_for_python_objects_is_rejected() -> None:
    # Only safe YAML is loaded; a tag that would build a Python object is an error.
    with pytest.raises(ContractValidationError) as caught:
        ProjectConfig.from_yaml("schema_version: !!python/object/apply:os.getcwd []\n")
    assert [(p.field, p.code) for p in caught.value.problems] == [("<document>", "invalid_yaml")]


def test_boolean_is_not_accepted_as_a_number() -> None:
    with pytest.raises(ContractValidationError) as caught:
        ProjectConfig.from_yaml(
            "schema_version: 1\ndata_policy: local_only\nbudget: {total_usd: true}\n"
        )
    assert [p.field for p in caught.value.problems] == ["budget.total_usd"]
