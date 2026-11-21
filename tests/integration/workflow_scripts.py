"""Scripted services for the workflow tests: a scripted model and executor.

Everything here is synthetic. The model's replies are fixed texts, and the
executor runs nothing: it writes a fixed metrics file into the run's output
directory.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from utux.core.workflow import WorkflowServices
from utux.executors.scripted import ScriptedExecutor, ScriptedRun
from utux.providers.scripted import ScriptedModelProvider, ScriptedReply

METHOD = "# Method\n\nSynthetic method: fit a line to the synthetic data.\n\n- metric: r2\n"
CODE = "print('synthetic experiment')\n"
CODE_AFTER_EDIT = "print('synthetic experiment, second version')\n"
METHOD_AFTER_QUESTION_EDIT = "# Method\n\nSynthetic method, second version.\n\n- metric: r2\n"
QUESTION = "Synthetic question: does a line fit the synthetic data?\n"
IMAGE = "sha256:" + "a" * 64

METRICS = (
    json.dumps(
        {
            "schema_version": 1,
            "entries": [
                {
                    "metric": "r2",
                    "value": 0.97,
                    "unit": "score",
                    "dataset": "synthetic_line",
                    "model": "linear",
                    "split": "test",
                    "tolerance": 0.005,
                }
            ],
        },
        indent=2,
    )
    + "\n"
).encode("utf-8")


def configure_models(project: Path) -> None:
    """Give the project a model for the standard tier, as a user would."""
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count("  tiers: {}\n") == 1
    config.write_text(
        text.replace("  tiers: {}\n", "  tiers:\n    standard: scripted/standard-model\n"),
        encoding="utf-8",
    )


def switch_gates_off(project: Path) -> None:
    """Switch the method and experiment-plan gates off, as a user can."""
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    for gate in ("method", "experiment_plan"):
        old = f"    {gate}: null\n"
        assert text.count(old) == 1, old
        text = text.replace(old, f"    {gate}: false\n")
    config.write_text(text, encoding="utf-8")


def services(
    project: Path,
    replies: Sequence[str] = (METHOD, CODE),
    *,
    cost_usd: float = 0.0,
    runs: int = 1,
    before_stage: Callable[[str], None] | None = None,
    inside_stage: Callable[[str, str], None] | None = None,
) -> WorkflowServices:
    """Scripted services: one reply per model call, `runs` scripted runs."""
    provider = ScriptedModelProvider(
        [ScriptedReply(content=reply, cost_usd=cost_usd) for reply in replies],
        name="scripted",
        is_external=False,
    )
    executor = ScriptedExecutor(
        project,
        [ScriptedRun(stdout=b"synthetic\n", files={"metrics.json": METRICS})] * runs,
    )
    return WorkflowServices(
        provider=provider,
        executor=executor,
        image_digest=IMAGE,
        locked_packages=lambda digest: {"numpy": "2.5.5"},
        rootless=False,
        before_stage=before_stage,
        inside_stage=inside_stage,
    )
