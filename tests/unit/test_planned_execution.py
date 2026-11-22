"""Findings of M1-16: an approval names the limits that will actually apply."""

from pathlib import Path

from utux.core.workflow import planned_execution
from utux.executors.docker import DEFAULT_LIMITS
from utux.schemas.project_config import DataPolicy, load_project_config
from utux.workspace.project import init_project

IMAGE = "sha256:" + "a" * 64


def test_unset_limits_are_the_executor_defaults(tmp_path: Path) -> None:
    project = init_project(tmp_path / "p", budget_usd=1, data_policy=DataPolicy.LOCAL_ONLY)
    limits = planned_execution(load_project_config(project / "utux.yaml"), IMAGE).limits
    assert (limits.cpus, limits.memory_mb, limits.disk_mb) == (
        DEFAULT_LIMITS.cpus,
        DEFAULT_LIMITS.memory_mb,
        DEFAULT_LIMITS.disk_mb,
    )
    assert (limits.max_processes, limits.output_mb) == (
        DEFAULT_LIMITS.max_processes,
        DEFAULT_LIMITS.output_mb,
    )
    assert limits.gpus == 0
    assert limits.timeout_seconds == 3600.0


def test_a_limit_set_in_utux_yaml_is_kept(tmp_path: Path) -> None:
    project = init_project(tmp_path / "p", budget_usd=1, data_policy=DataPolicy.LOCAL_ONLY)
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("  memory_mb: null\n", "  memory_mb: 512\n"), encoding="utf-8")
    limits = planned_execution(load_project_config(config), IMAGE).limits
    assert limits.memory_mb == 512
    assert limits.cpus == DEFAULT_LIMITS.cpus
