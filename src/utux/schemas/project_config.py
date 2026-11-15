"""Schema of `utux.yaml`, the project configuration file.

The fields come from the specification: profiles (section 5), the project
directory (section 7), oversight, routing and budgets (section 9), and
resource limits, data policy and AI disclosure (section 10).
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Self

import yaml
from pydantic import Field, StrictBool, field_validator
from pydantic_core import PydanticCustomError

from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.common import Identifier, NonNegativeInt, PositiveInt, PositiveUsd, Stage, Tier
from utux.schemas.yaml_io import parse_yaml, read_yaml

FILE_NAME = "utux.yaml"


class DataPolicy(StrEnum):
    """What may be sent to external services."""

    EXTERNAL_ALLOWED = "external_allowed"
    LOCAL_ONLY = "local_only"


class OversightMode(StrEnum):
    """Which approval gates are on unless a gate is switched individually."""

    GUIDED = "guided"
    AUTO = "auto"


class Gate(StrEnum):
    """The four approval gates."""

    IDEA = "idea"
    METHOD = "method"
    EXPERIMENT_PLAN = "experiment_plan"
    FINAL_MANUSCRIPT = "final_manuscript"


class Budget(ContractPart):
    """Spending limits in US dollars.

    The total has no default: the specification asks for conservative
    defaults but states no amount, so the project must state one.
    """

    total_usd: PositiveUsd
    per_stage_usd: dict[Stage, PositiveUsd] = Field(default_factory=dict)


class Gates(ContractPart):
    """Per-gate switches. A gate that is not set follows the oversight mode."""

    idea: StrictBool | None = None
    method: StrictBool | None = None
    experiment_plan: StrictBool | None = None
    final_manuscript: StrictBool | None = None

    @field_validator("final_manuscript")
    @classmethod
    def _final_gate_stays_on(cls, value: bool | None) -> bool | None:
        if value is False:
            raise PydanticCustomError(
                "final_gate_off",
                "the final-manuscript gate is always on and cannot be switched off",
            )
        return value


class Oversight(ContractPart):
    """Human oversight: the mode and any per-gate switches."""

    mode: OversightMode = OversightMode.GUIDED
    gates: Gates = Field(default_factory=Gates)

    def gate_enabled(self, gate: Gate) -> bool:
        """Return whether a gate asks for human approval.

        A per-gate switch wins over the mode. The final-manuscript gate is on
        in every mode.
        """
        if gate is Gate.FINAL_MANUSCRIPT:
            return True
        switch: bool | None = getattr(self.gates, gate.value)
        if switch is not None:
            return switch
        return self.mode is OversightMode.GUIDED


class Verification(ContractPart):
    """The verification toggle. Verification is on unless switched off."""

    enabled: StrictBool = True


class AiDisclosure(ContractPart):
    """Whether an AI-use disclosure statement is drafted. On unless switched off."""

    draft: StrictBool = True


class Resources(ContractPart):
    """Limits for each run. A limit that is not set is left to the executor."""

    cpus: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)] | None = None
    memory_mb: PositiveInt | None = None
    gpus: NonNegativeInt | None = None
    wall_clock_seconds: PositiveInt | None = None
    disk_mb: PositiveInt | None = None
    max_processes: PositiveInt | None = None


class Models(ContractPart):
    """Model routing: which model serves each tier, and which tier each role uses.

    Both mappings are empty by default; the profile supplies what is not set.
    """

    tiers: dict[Tier, Annotated[str, Field(min_length=1)]] = Field(default_factory=dict)
    roles: dict[Identifier, Tier] = Field(default_factory=dict)


class ProjectConfig(ContractDocument):
    """The content of `utux.yaml`.

    Required: `schema_version`, `data_policy` and `budget.total_usd`. The data
    policy has no default on purpose, so that sending data to external
    services is always a stated choice.
    """

    SCHEMA_VERSION: ClassVar[int] = 1

    profile: Identifier = "default"
    domain_pack: Identifier = "generic"
    data_policy: DataPolicy
    budget: Budget
    oversight: Oversight = Field(default_factory=Oversight)
    verification: Verification = Field(default_factory=Verification)
    ai_disclosure: AiDisclosure = Field(default_factory=AiDisclosure)
    resources: Resources = Field(default_factory=Resources)
    models: Models = Field(default_factory=Models)

    @classmethod
    def from_yaml(cls, text: str, source: str = FILE_NAME) -> Self:
        """Parse and validate the text of a `utux.yaml` file.

        Args:
            text: The YAML text.
            source: The file name to use in error messages.

        Raises:
            ContractValidationError: If the text is not a valid configuration.
        """
        return cls.validate_document(parse_yaml(text, source), source)

    def to_yaml(self) -> str:
        """Return the configuration as YAML text, with defaults written out."""
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)


def load_project_config(path: Path) -> ProjectConfig:
    """Read and validate a `utux.yaml` file.

    Raises:
        ContractValidationError: If the file cannot be read or is not a valid
            configuration. The error names the path as it was given.
    """
    return ProjectConfig.validate_document(read_yaml(path), str(path))
