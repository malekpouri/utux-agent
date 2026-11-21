"""Scripted services for the workflow tests: a scripted model and executor.

Everything here is synthetic. The model answers by role, from fixed replies;
the executor runs nothing and writes a fixed metrics file into the run's
output directory.
"""

import json
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from utux.core.workflow import WorkflowServices
from utux.executors.scripted import ScriptedExecutor, ScriptedRun
from utux.interfaces.model_provider import FinishReason, ModelRequest, ModelResponse, Usage

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS = REPO_ROOT / "packs" / "generic" / "prompts"


def plan(title: str, metrics: Sequence[str] = ("r2",)) -> dict[str, object]:
    """A methodologist's plan of one step."""
    return {
        "steps": [
            {
                "title": title,
                "description": f"Synthetic step: {title.lower()}.",
                "success_criterion": "The synthetic metric is reported.",
                "metrics": list(metrics),
            }
        ]
    }


def rendered(title: str, metrics: Sequence[str] = ("r2",)) -> str:
    """The method.md that `plan(title, metrics)` gives, written out by hand."""
    lines = "".join(f"- metric: {m}\n" for m in metrics)
    return (
        "# Method\n\n"
        f"## Step 1: {title}\n\n"
        f"Synthetic step: {title.lower()}.\n\n"
        "Success criterion: The synthetic metric is reported.\n\n"
        f"{lines}"
    )


METHOD = plan("Fit a line")
METHOD_MD = rendered("Fit a line")
METHOD_AFTER_QUESTION_EDIT = plan("Fit a line, second version")
METHOD_AFTER_QUESTION_EDIT_MD = rendered("Fit a line, second version")
CODE = "print('synthetic experiment')\n"
CODE_AFTER_EDIT = "print('synthetic experiment, second version')\n"
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


@dataclass(frozen=True)
class Raw:
    """A reply given as it is, for a role: for example one that is not JSON."""

    role: str
    text: str


Reply = dict[str, object] | str | Raw

_ROLE = re.compile(r"^# Role: (\w+)")
_RECORD_ID = re.compile(r"\bR\d{4,}\b")


class RoleScriptedProvider:
    """A scripted `ModelProvider` that answers each role from its own replies.

    The role is read from the first line of the request's first message, the
    prompt's `# Role:` line. A plan (a dict) answers the methodologist, a
    string answers the implementer as code, and `Raw` answers its role as
    given. Unless replies are given for it, the analyst refers to the first
    result id its request lists.
    """

    def __init__(self, replies: Sequence[Reply], *, cost_usd: float = 0.0) -> None:
        self._queues: dict[str, list[str]] = {"methodologist": [], "implementer": [], "analyst": []}
        for reply in replies:
            if isinstance(reply, Raw):
                self._queues[reply.role].append(reply.text)
            elif isinstance(reply, dict):
                self._queues["methodologist"].append(json.dumps(reply))
            else:
                self._queues["implementer"].append(json.dumps({"code": reply}))
        self._cost = cost_usd
        self._lock = threading.Lock()
        self.requests: list[ModelRequest] = []

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def is_external(self) -> bool:
        return False

    def complete(self, request: ModelRequest) -> ModelResponse:
        found = _ROLE.match(request.messages[0].content)
        assert found is not None, "a request without a role line"
        role = found.group(1)
        with self._lock:
            self.requests.append(request)
            queue = self._queues[role]
            if queue:
                content = queue.pop(0)
            elif role == "analyst":
                ids = _RECORD_ID.findall(request.messages[-1].content)
                text = f"The synthetic line fits: [{ids[0]}]." if ids else "No records."
                content = json.dumps({"text": text})
            else:
                raise AssertionError(f"no scripted reply left for the {role}")
        return ModelResponse(
            model=request.model,
            content=content,
            finish_reason=FinishReason.STOP,
            usage=Usage(tokens_in=1, tokens_out=1),
            cost_usd=self._cost,
        )

    def of(self, role: str) -> list[ModelRequest]:
        """The requests made for one role, in order."""
        return [r for r in self.requests if r.messages[0].content.startswith(f"# Role: {role}")]


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
    replies: Sequence[Reply] = (METHOD, CODE),
    *,
    cost_usd: float = 0.0,
    runs: int = 1,
    before_stage: Callable[[str], None] | None = None,
    inside_stage: Callable[[str, str], None] | None = None,
    executions: Sequence[ScriptedRun] | None = None,
) -> WorkflowServices:
    """Scripted services: replies by role, and `runs` passing scripted runs."""
    passing = ScriptedRun(stdout=b"synthetic\n", files={"metrics.json": METRICS})
    return WorkflowServices(
        provider=RoleScriptedProvider(replies, cost_usd=cost_usd),
        executor=ScriptedExecutor(
            project, list(executions) if executions is not None else [passing] * runs
        ),
        image_digest=IMAGE,
        locked_packages=lambda digest: {"numpy": "2.5.5"},
        rootless=False,
        prompts=PROMPTS,
        before_stage=before_stage,
        inside_stage=inside_stage,
    )
