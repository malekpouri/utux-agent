"""The workflow graph of stages 3 to 5 (milestone M1).

Four nodes run in order: `methodology`, `implementation`, `experiment` and
`analysis`. The analysis belongs to stage 5, experiment and analysis
(specification, section 4), so its events and sidecars name the stage
`experiment`. Each node writes its outputs with sidecars, between a
`stage_start` and a `stage_end` event, and the stage is then committed
(ADR-0010).

A run is named by its `run_started` event: the event's id is the run id, and
the LangGraph thread id of its checkpoints. The graph state holds only ids,
relative paths, hashes and node names, never artifact text or model output;
texts are in the files, and the checkpoints are written with
`StrictCheckpointSerializer` to `.utux/checkpoints.sqlite`, after every node.

On resume, the files win: the input hashes each finished node recorded are
compared with the files, and the run restarts at the earliest node whose
inputs changed, recorded as a `run_restarted` event. A checkpoint that no
`run_started` event of the project's log matches is refused.

LangGraph is used only in `utux.core`; this module is the one place that
builds the graph.
"""

import ast
import itertools
import math
import os
import platform
import re
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from utux.core.agents import (
    AnalysisOutput,
    CodeOutput,
    MethodPlan,
    Prompt,
    check_analysis_text,
    check_results,
    load_prompt,
    render_method,
    render_results,
)
from utux.core.checkpoints import StrictCheckpointSerializer
from utux.errors import (
    AgentOutputError,
    ApprovalMismatchError,
    BudgetExhaustedError,
    CheckpointMismatchError,
    MethodFormatError,
    ModelProviderConfigError,
    NoRunToResumeError,
    RunPausedError,
    RunRefusedError,
    RunRejectedError,
)
from utux.events.log import EventLog
from utux.interfaces.executor import ExecutionStep, Executor, ResourceLimits
from utux.interfaces.model_provider import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
)
from utux.schemas.approval import (
    ApprovalKind,
    ApprovalRequest,
    ApprovalResponse,
    Decision,
    ExecutionLimits,
    PlannedExecution,
    check_response_matches_request,
    load_approval_request,
    load_approval_response,
)
from utux.schemas.artifact_metadata import ArtifactMetadata, ArtifactState
from utux.schemas.common import Scalar, Stage, Tier
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.schemas.json_io import parse_json
from utux.schemas.project_config import Gate, OversightMode, ProjectConfig, load_project_config
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import (
    Container,
    GitState,
    Hardware,
    RunManifest,
    load_run_manifest,
)
from utux.workspace.atomic import atomic_write_text
from utux.workspace.commits import check_commits, commit_stage, head_commit
from utux.workspace.hashing import hash_file
from utux.workspace.layout import CONFIG_FILE, EVENT_LOG_FILE, RESULTS_FILE
from utux.workspace.model_calls import LoggedModelCaller
from utux.workspace.results import METRICS_FILE, manifest_outputs, record_run
from utux.workspace.writer import writing_command

NODES = ("methodology", "implementation", "experiment", "analysis")
"""The nodes of the graph, in order."""

CHECKPOINT_FILE = ".utux/checkpoints.sqlite"
"""The checkpoint database of a project."""

STAGE_OF = {
    "methodology": Stage.METHODOLOGY,
    "implementation": Stage.IMPLEMENTATION,
    "experiment": Stage.EXPERIMENT,
    "analysis": Stage.EXPERIMENT,
}

SYSTEM_ACTOR = "system:utux"
EDITED_BY = "human:unknown"
"""Who made a version that changed outside utux: a person, not known by name."""

_DEFAULT_TIMEOUT_SECONDS = 3600.0


@dataclass
class WorkflowServices:
    """What a run uses besides the project directory.

    Attributes:
        provider: The model provider; tests pass a scripted one.
        executor: The executor; tests pass the scripted one.
        image_digest: The image to run code in, the pack's recorded image.
        locked_packages: Reads the package versions from inside an image.
        rootless: Whether the executor runs rootless Docker.
        prompts: The directory of the pack's prompts.
        before_stage: Called with a node's name before it starts; tests use
            it to look at the log or to stop a run.
        inside_stage: Called with a node's name and `staged` once its outputs
            are in the staging area, and `moved` once they are in place; tests
            use it to stop a node halfway.
    """

    provider: ModelProvider
    executor: Executor
    image_digest: str
    locked_packages: Callable[[str], dict[str, str]]
    rootless: bool
    prompts: Path
    before_stage: Callable[[str], None] | None = None
    inside_stage: Callable[[str, str], None] | None = None


@dataclass(frozen=True)
class RunOutcome:
    """How a run ended.

    Attributes:
        run_id: The run, the id of its `run_started` event.
        commits: Whether stages were committed.
        results: The result records of the run.
    """

    run_id: str
    commits: bool
    results: tuple[ResultRecord, ...]


class StageRecord(TypedDict):
    """What a finished node recorded.

    Its inputs and outputs by path and hash, and the artifact versions it made.
    """

    inputs: dict[str, str]
    outputs: dict[str, str]
    artifacts: list[str]


class RunState(TypedDict, total=False):
    """The graph state. Only ids, relative paths, hashes and small enums.

    `route_to` and `finding` are set by the check after the analysis, or by
    a rejection at a gate: the node to go back to (or `end`) and the finding
    that sends the run there (or `none`). After a rejection, `feedback` is
    the id of the approval whose response holds the person's feedback.
    """

    stages: dict[str, StageRecord]
    experiment_run: str
    results: list[str]
    route_to: str
    finding: str
    feedback: str


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_or_none(path: Path) -> str | None:
    return hash_file(path) if path.is_file() else None


# Sidecars


def _sidecars(project: Path) -> list[ArtifactMetadata]:
    found = []
    for path in sorted((project / ".utux" / "meta").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        found.append(ArtifactMetadata.validate_document(parse_json(text, str(path)), str(path)))
    return found


def _version(artifact_id: str) -> int:
    return int(artifact_id.rsplit("-v", 1)[1])


def current_artifact(project: Path, path: str) -> ArtifactMetadata | None:
    """The current version of a path: its sidecar with the highest version."""
    versions = [s for s in _sidecars(project) if s.path == path]
    return max(versions, key=lambda s: _version(s.artifact_id)) if versions else None


STAGING_DIRECTORY = ".utux/staging"
"""Where a node writes its outputs and sidecars before it completes."""


class _Staging:
    """The staging area of one node: the project's paths below its own root.

    A node writes here; only when it completes are the files moved into the
    project, sidecars last (specification, section 7, "A stage stops
    halfway"). A node that starts again starts from an empty area.
    """

    def __init__(self, project: Path, node: str) -> None:
        self.project = project
        self.relative = f"{STAGING_DIRECTORY}/{node}"
        self.root = project / self.relative

    def clean(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def path(self, relative: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def move_into_project(self) -> None:
        files = sorted(p for p in self.root.rglob("*") if p.is_file())
        sidecars = [p for p in files if p.relative_to(self.root).parts[:2] == (".utux", "meta")]
        for path in [p for p in files if p not in sidecars] + sidecars:
            target = self.project / path.relative_to(self.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        shutil.rmtree(self.root)
        staging = self.project / STAGING_DIRECTORY
        if staging.is_dir() and not any(staging.iterdir()):
            staging.rmdir()


def _record_artifact(
    project: Path,
    staging: _Staging | None,
    name: str,
    path: str,
    stage: Stage,
    created_by: str,
    inputs: tuple[str, ...],
) -> str:
    """Record a version of an artifact and return its id.

    The content is read from the staging area if the node wrote it there.
    If the current version of the path already has this content, these
    inputs and this maker, it is that version: a node run again after a
    crash makes no second, identical version.
    """
    root = project if staging is None else staging.root
    content_hash = hash_file(root / path)
    current = current_artifact(project, path)
    if (
        current is not None
        and current.content_hash == content_hash
        and current.input_artifacts == inputs
        and current.created_by == created_by
    ):
        return current.artifact_id
    taken = [
        _version(s.artifact_id) for s in _sidecars(project) if s.artifact_id.startswith(name + "-v")
    ]
    artifact_id = f"{name}-v{max(taken, default=0) + 1:03d}"
    sidecar = ArtifactMetadata(
        schema_version=ArtifactMetadata.SCHEMA_VERSION,
        artifact_id=artifact_id,
        path=path,
        stage=stage,
        created_by=created_by,
        created_at=_timestamp(),
        input_artifacts=inputs,
        content_hash=content_hash,
        state=ArtifactState.VALID,
    )
    target = root / ".utux" / "meta" / f"{artifact_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, sidecar.to_json())
    return artifact_id


def _current_id(project: Path, path: str) -> tuple[str, ...]:
    current = current_artifact(project, path)
    return () if current is None else (current.artifact_id,)


# The inputs of each node, as they are now


def _question_files(project: Path) -> list[str]:
    return sorted(
        path.relative_to(project).as_posix() for path in (project / "inputs").glob("*.md")
    )


def _current_inputs(project: Path, node: str, state: RunState) -> dict[str, str | None]:
    if node == "methodology":
        paths = _question_files(project)
    elif node == "implementation":
        paths = ["method.md"]
    elif node == "experiment":
        paths = ["code/main.py"]
    else:
        run = state.get("experiment_run")
        paths = [] if run is None else [f"runs/{run}/manifest.json"]
    return {path: _hash_or_none(project / path) for path in paths}


# The nodes


@dataclass
class _Context:
    project: Path
    services: WorkflowServices
    config: ProjectConfig
    log: EventLog
    caller: LoggedModelCaller
    run_id: str
    commits: bool


def _with_finding(context: _Context, state: RunState, node: str, inputs: str) -> str:
    """Add why the run came back to this node, if it did: a finding or a person's feedback."""
    if state.get("route_to") != node:
        return inputs
    finding = state.get("finding", NO_FINDING)
    if finding == REJECTED_AT_GATE and state.get("feedback"):
        response = _response(context.project, state["feedback"])
        if response is not None and response.feedback is not None:
            return (
                inputs
                + "\n\nA person rejected the previous version of this stage's output with "
                + "this feedback:\n\n"
                + response.feedback
            )
    if finding != NO_FINDING:
        return (
            inputs
            + "\n\nThe previous attempt was sent back to this stage with the finding: "
            + f"{finding}."
        )
    return inputs


_ROLE_OF = {
    "methodology": "methodologist",
    "implementation": "implementer",
    "analysis": "analyst",
}

INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"


def _call(context: _Context, node: str, prompt: Prompt, inputs: str, retry: bool) -> str:
    role = _ROLE_OF[node]
    tier = context.config.models.roles.get(role, Tier.STANDARD)
    model = context.config.models.tiers.get(tier)
    if model is None:
        raise ModelProviderConfigError(
            f"no model is configured for the tier {tier.value} of the role {role} in "
            f"{CONFIG_FILE} (models.tiers)"
        )
    try:
        response = context.caller.call(
            ModelRequest(
                model=model,
                messages=(
                    Message(role=MessageRole.SYSTEM, content=prompt.fill()),
                    Message(role=MessageRole.USER, content=inputs),
                ),
                timeout_seconds=300.0,
                temperature=0.0,
            ),
            actor=f"agent:{role}",
            prompt_version=prompt.version,
            stage=STAGE_OF[node],
            run_id=context.run_id,
            retry_reason=INVALID_STRUCTURED_OUTPUT if retry else None,
        )
    except BudgetExhaustedError as error:
        _pause_for_budget(context, node, error)
    return response.content


def _ask[T: BaseModel](
    context: _Context,
    node: str,
    inputs: str,
    output: type[T],
    check: Callable[[T], None] | None = None,
) -> T:
    """Ask a role for its JSON answer, validate it, and ask once more if it fails.

    Raises:
        AgentOutputError: The second answer is not valid either. An `error`
            event records it.
    """
    role = _ROLE_OF[node]
    prompt = load_prompt(context.services.prompts, role)
    problem = ""
    for attempt in range(2):
        asked = (
            inputs
            if attempt == 0
            else (
                inputs
                + "\n\nYour previous answer was not valid: "
                + problem
                + "\nAnswer again with JSON only, of the form the instructions give."
            )
        )
        content = _call(context, node, prompt, asked, retry=attempt > 0)
        try:
            answer = output.model_validate_json(content)
            if check is not None:
                check(answer)
            return answer
        except ValidationError as error:
            problem = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}"
                for e in error.errors()
            )
        except AgentOutputError as error:
            problem = str(error)
    context.log.append(
        NewEvent(
            actor=SYSTEM_ACTOR,
            type=EventType.ERROR,
            status=EventStatus.ERROR,
            status_reason=INVALID_STRUCTURED_OUTPUT,
            run_id=context.run_id,
            stage=STAGE_OF[node],
        )
    )
    raise AgentOutputError(
        f"the {role}'s answer was not valid twice, so the {node} stage failed: {problem}"
    )


def _input_files(project: Path) -> str:
    return "\n\n".join(
        f"{path}:\n\n" + (project / path).read_text(encoding="utf-8")
        for path in _question_files(project)
    )


def _methodology(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    inputs = {p: hash_file(project / p) for p in _question_files(project)}
    asked = _with_finding(
        context,
        state,
        "methodology",
        "The research question and the data description:\n\n" + _input_files(project),
    )
    plan = _ask(context, "methodology", asked, MethodPlan)
    atomic_write_text(staging.path("method.md"), render_method(plan))
    artifact = _record_artifact(
        project, staging, "method", "method.md", Stage.METHODOLOGY, "agent:methodologist", ()
    )
    return {
        "inputs": inputs,
        "outputs": {"method.md": hash_file(staging.path("method.md"))},
        "artifacts": [artifact],
    }, {}


def _implementation(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    inputs = {"method.md": hash_file(project / "method.md")}
    method = (project / "method.md").read_text(encoding="utf-8")
    asked = _with_finding(context, state, "implementation", "The method:\n\n" + method)
    code = _ask(context, "implementation", asked, CodeOutput)
    atomic_write_text(staging.path("code/main.py"), code.code)
    artifact = _record_artifact(
        project,
        staging,
        "code",
        "code/main.py",
        Stage.IMPLEMENTATION,
        "agent:implementer",
        _current_id(project, "method.md"),
    )
    return {
        "inputs": inputs,
        "outputs": {"code/main.py": hash_file(staging.path("code/main.py"))},
        "artifacts": [artifact],
    }, {}


def _next_run_id(project: Path) -> str:
    taken = [
        int(path.name[1:])
        for path in (project / "runs").glob("r*")
        if path.is_dir() and path.name[1:].isdigit()
    ]
    return f"r{max(taken, default=0) + 1:03d}"


def _hardware() -> Hardware:
    try:
        memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (ValueError, OSError):
        memory = 1
    return Hardware(
        cpu=platform.machine() or "unknown",
        cpu_count=os.cpu_count() or 1,
        memory_mb=max(memory, 1),
        gpu=None,
        cuda_version=None,
        driver_version=None,
    )


def planned_execution(config: ProjectConfig, image_digest: str) -> PlannedExecution:
    """The execution the experiment runs: what its approval covers.

    The experiment builds its step from this record, and the experiment-plan
    gate compares it with the record its request approved.
    """
    resources = config.resources
    return PlannedExecution(
        image_digest=image_digest,
        command=("python", "code/main.py"),
        read_only_paths=("code", "inputs"),
        limits=ExecutionLimits(
            cpus=resources.cpus,
            memory_mb=resources.memory_mb,
            gpus=resources.gpus,
            disk_mb=resources.disk_mb,
            max_processes=resources.max_processes,
            output_mb=resources.output_mb,
            timeout_seconds=float(resources.wall_clock_seconds or _DEFAULT_TIMEOUT_SECONDS),
        ),
    )


def _experiment(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    services = context.services
    inputs = {"code/main.py": hash_file(project / "code/main.py")}
    run = _next_run_id(project)
    planned = planned_execution(context.config, services.image_digest)
    limits = planned.limits
    step = ExecutionStep(
        run_id=run,
        command=planned.command,
        image_digest=planned.image_digest,
        read_only_paths=planned.read_only_paths,
        # The container writes into the staging area; the outputs are moved
        # to runs/<run>/outputs when the node completes.
        output_directory=f"{staging.relative}/runs/{run}/outputs",
        limits=ResourceLimits(
            cpus=limits.cpus,
            memory_mb=limits.memory_mb,
            gpus=limits.gpus,
            disk_mb=limits.disk_mb,
            max_processes=limits.max_processes,
            output_mb=limits.output_mb,
        ),
        timeout_seconds=limits.timeout_seconds,
        # The code writes its metrics.json here (the implementer's prompt says so).
        environment={"UTUX_OUTPUT_DIR": f"{staging.relative}/runs/{run}/outputs"},
    )
    result = services.executor.run(step)
    final = step.model_copy(update={"output_directory": f"runs/{run}/outputs"})
    commit, dirty = head_commit(project)
    manifest = RunManifest(
        schema_version=RunManifest.SCHEMA_VERSION,
        run_id=run,
        command=step.command,
        parameters={},
        config_files=(),
        git=GitState(commit=commit, dirty=dirty),
        container=Container(
            image_digest=services.image_digest,
            locked_packages=services.locked_packages(services.image_digest),
            rootless=services.rootless,
        ),
        datasets=(),
        seeds={},
        hardware=_hardware(),
        models=(),
        external_services=(),
        outputs=manifest_outputs(final, result),
        started_at=result.started_at,
        ended_at=result.ended_at,
        exit_status=result.exit_status,
        stopped_by=result.stopped_by,
    )
    recording = record_run(project, final, result, manifest, root=staging.root)
    manifest_path = f"runs/{run}/manifest.json"
    outputs = {manifest_path: hash_file(staging.path(manifest_path))}
    outputs |= {ref.path: ref.hash for ref in manifest.outputs}
    artifacts: list[str] = []
    metrics = f"{final.output_directory}/{METRICS_FILE}"
    if metrics in outputs:
        artifacts.append(
            _record_artifact(
                project,
                staging,
                "metrics",
                metrics,
                Stage.EXPERIMENT,
                SYSTEM_ACTOR,
                _current_id(project, "code/main.py"),
            )
        )
    record: StageRecord = {"inputs": inputs, "outputs": outputs, "artifacts": artifacts}
    return record, {"experiment_run": run, "results": [r.id for r in recording.records]}


def _read_records(project: Path, ids: list[str]) -> list[ResultRecord]:
    text = (project / RESULTS_FILE).read_text(encoding="utf-8")
    records = [ResultRecord.from_json(line) for line in text.split("\n") if line]
    wanted = set(ids)
    return [record for record in records if record.id in wanted]


def _analysis(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    run = state.get("experiment_run", "")
    manifest = f"runs/{run}/manifest.json"
    inputs = {manifest: hash_file(project / manifest)}
    records = _read_records(project, state.get("results", []))
    listing = "\n".join(
        f"- {r.id}: {r.metric} on {r.dataset}"
        + (f", split {r.split}" if r.split else "")
        + (f", model {r.model}" if r.model else "")
        + f": {r.value!r} {r.unit}"
        for r in records
    )
    asked = (
        f"The result records of run {run}:\n\n{listing}"
        if records
        else f"Run {run} has no result records."
    )
    ids = {r.id for r in records}
    output = _ask(
        context,
        "analysis",
        asked,
        AnalysisOutput,
        check=lambda answer: check_analysis_text(answer.text, ids),
    )
    text = render_results(output, records)
    # Checked again as written: no number in results.md without its record.
    check_results(text, records)
    atomic_write_text(staging.path("results.md"), text)
    metrics = f"runs/{run}/outputs/{METRICS_FILE}"
    artifact = _record_artifact(
        project,
        staging,
        "results",
        "results.md",
        Stage.EXPERIMENT,
        "agent:analyst",
        _current_id(project, metrics),
    )
    return {
        "inputs": inputs,
        "outputs": {"results.md": hash_file(staging.path("results.md"))},
        "artifacts": [artifact],
    }, {}


_BODIES: dict[str, Callable[[_Context, RunState, _Staging], tuple[StageRecord, RunState]]] = {
    "methodology": _methodology,
    "implementation": _implementation,
    "experiment": _experiment,
    "analysis": _analysis,
}


def _node(context: _Context, node: str) -> Callable[[RunState], RunState]:
    def run_node(state: RunState) -> RunState:
        if context.services.before_stage is not None:
            context.services.before_stage(node)
        if node == "implementation":
            check_method((context.project / "method.md").read_text(encoding="utf-8"))
        if node in GATE_BEFORE:
            gate, path = GATE_BEFORE[node]
            if context.config.oversight.gate_enabled(gate):
                _pass_gate(context, gate, path)
        stage = STAGE_OF[node]
        context.log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.STAGE_START,
                status=EventStatus.OK,
                run_id=context.run_id,
                stage=stage,
                data={"node": node},
            )
        )
        staging = _Staging(context.project, node)
        # A node that runs again after a crash starts from an empty area.
        staging.clean()
        record, updates = _BODIES[node](context, state, staging)
        if context.services.inside_stage is not None:
            context.services.inside_stage(node, "staged")
        staging.move_into_project()
        if context.services.inside_stage is not None:
            context.services.inside_stage(node, "moved")
        context.log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.STAGE_END,
                status=EventStatus.OK,
                run_id=context.run_id,
                stage=stage,
                data={"node": node},
                artifacts=tuple(record["artifacts"]),
            )
        )
        if context.commits:
            commit_stage(context.project, f"utux: {node} ({context.run_id})")
        stages = dict(state.get("stages", {}))
        stages[node] = record
        result: RunState = {"stages": stages}
        result.update(updates)
        return result

    return run_node


# The check after the analysis, and routing back (M1-12)

CHECK_NODE = "check"
"""The deterministic check after the analysis; not a stage, so it writes no
stage events and makes no commit."""

DEFAULT_RETRY_CAP = 2
"""The default of `workflow.retry_cap`: how many times a run may be routed
back to one stage before it pauses."""

RUN_FAILED = "run_failed"
METRIC_MISSING = "metric_missing"
NO_FINDING = "none"
REJECTED_AT_GATE = "rejected_at_gate"
HARDCODED_METRIC = "hardcoded_metric"
END_ROUTE = "end"
FINDINGS = (RUN_FAILED, HARDCODED_METRIC, METRIC_MISSING, REJECTED_AT_GATE, NO_FINDING)
ROUTES = (*NODES, END_ROUTE)

_ROUTE_FOR = {
    RUN_FAILED: "implementation",
    HARDCODED_METRIC: "implementation",
    METRIC_MISSING: "methodology",
}
_METRIC_LINE = re.compile(r"^- metric: ([A-Za-z0-9][A-Za-z0-9_.-]*)$")
_LOOKS_LIKE_METRIC_LINE = re.compile(r"^\s*[-*+]?\s*metric\b", flags=re.IGNORECASE)


def named_metrics(method: str) -> set[str]:
    """The metrics a method names.

    A metric is named on a line of exactly this form: `- metric: <name>`,
    the hyphen at the start of the line, one space on each side of
    `metric:`, and a name of letters, digits, `_`, `.` and `-` that starts
    with a letter or digit, with nothing after it.
    """
    return {
        found.group(1)
        for line in method.splitlines()
        if (found := _METRIC_LINE.fullmatch(line)) is not None
    }


def check_method(method: str) -> None:
    """Refuse a method that names no metric, or whose metric line is malformed.

    Raises:
        MethodFormatError: No line names a metric, or a line looks like a
            metric line but is not of the exact form.
    """
    for number, line in enumerate(method.splitlines(), start=1):
        if _LOOKS_LIKE_METRIC_LINE.match(line) and _METRIC_LINE.fullmatch(line) is None:
            raise MethodFormatError(
                f"method.md, line {number}: {line!r} is not a metric line of the form "
                "'- metric: <name>'; correct method.md and run utux run again"
            )
    if not named_metrics(method):
        raise MethodFormatError(
            "method.md names no metric; add a line '- metric: <name>' for each metric "
            "the method's success criteria use, and run utux run again"
        )


def _finding(context: _Context, state: RunState) -> str:
    project = context.project
    run = state.get("experiment_run", "")
    manifest = load_run_manifest(project / "runs" / run / "manifest.json")
    if manifest.exit_status != 0 or manifest.stopped_by is not None:
        return RUN_FAILED
    records = _read_records(project, state.get("results", []))
    code = (project / "code" / "main.py").read_text(encoding="utf-8")
    if any(hard_coded(code, record.value, record.tolerance) for record in records):
        return HARDCODED_METRIC
    method = (project / "method.md").read_text(encoding="utf-8")
    if named_metrics(method) - {record.metric for record in records}:
        return METRIC_MISSING
    return NO_FINDING


def _decimals(tolerance: float) -> int | None:
    """The decimals a tolerance implies.

    Rounding to them errs by at most the tolerance. None for a tolerance of
    zero, which asks for the exact value.
    """
    if tolerance <= 0:
        return None
    return max(0, math.ceil(-math.log10(2 * tolerance) - 1e-9))


def hard_coded(code: str, value: float, tolerance: float) -> bool:
    """Whether a metric's value appears as a numeric literal in the code.

    The value and every int or float literal are rounded to the decimals the
    tolerance implies before they are compared. The code is parsed, never
    run; code that does not parse has no literals to compare. This is a
    heuristic that catches only the plain case of a value written into the
    code; the reviewer (M3) and the negative control (M4) are the stronger
    checks.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    decimals = _decimals(tolerance)

    def rounded(number: float) -> float:
        return number if decimals is None else round(number, decimals)

    target = rounded(value)
    for node in ast.walk(tree):
        literal = node.value if isinstance(node, ast.Constant) else None
        # bool is an int, but True and False are not numbers written into code.
        if (
            isinstance(literal, int | float)
            and not isinstance(literal, bool)
            and rounded(float(literal)) == target
        ):
            return True
    return False


def _routes_so_far(context: _Context, to_stage: str) -> tuple[int, int]:
    """The route backs to a stage in this run, and the approved raises of its cap."""
    routes = 0
    refused: set[str] = set()
    for event in context.log:
        if event.type is not EventType.ROUTE_BACK or event.run_id != context.run_id:
            continue
        if event.data.get("to_stage") != to_stage:
            continue
        if event.status is EventStatus.OK:
            routes += 1
        else:
            refused.add(event.event_id)
    answered = _answered(context)
    raises = sum(
        1
        for approval_id, request in _requests_of_run(context)
        if request.kind is ApprovalKind.RETRY_LIMIT
        and request.refused_event_id in refused
        and answered.get(approval_id) == Decision.APPROVE.value
    )
    return routes, raises


def _check(context: _Context) -> Callable[[RunState], RunState]:
    def run_check(state: RunState) -> RunState:
        finding = _finding(context, state)
        if finding == NO_FINDING:
            return {"route_to": END_ROUTE, "finding": NO_FINDING}
        to = _ROUTE_FOR[finding]
        to_stage = STAGE_OF[to].value
        routes, raises = _routes_so_far(context, to_stage)
        attempt, cap = routes + 1, context.config.workflow.retry_cap + raises
        data: dict[str, Scalar] = {
            "from_stage": Stage.EXPERIMENT.value,
            "to_stage": to_stage,
            "finding": finding,
            "attempt": attempt,
            "cap": cap,
        }
        if attempt > cap:
            refused = context.log.append(
                NewEvent(
                    actor=SYSTEM_ACTOR,
                    type=EventType.ROUTE_BACK,
                    status=EventStatus.REFUSED,
                    status_reason=RETRY_LIMIT,
                    run_id=context.run_id,
                    stage=Stage.EXPERIMENT,
                    data=data,
                )
            )
            _ask_for_approval(
                context,
                Stage.EXPERIMENT,
                kind=ApprovalKind.RETRY_LIMIT,
                refused_event_id=refused.event_id,
            )
        context.log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.ROUTE_BACK,
                status=EventStatus.OK,
                run_id=context.run_id,
                stage=Stage.EXPERIMENT,
                data=data,
            )
        )
        return {"route_to": to, "finding": finding}

    return run_check


RETRY_LIMIT = "retry_limit"


# Gates and pauses (M1-11, ADR-0011)

GATE_BEFORE: dict[str, tuple[Gate, str]] = {
    "implementation": (Gate.METHOD, "method.md"),
    "experiment": (Gate.EXPERIMENT_PLAN, "code/main.py"),
}
"""The gate checked before a node starts, and the file it approves.

The method gate approves `method.md` before the implementation. The
experiment-plan gate approves the code the experiment will run, before it
runs.
"""

APPROVALS_DIRECTORY = "approvals"


def _next_approval_id(project: Path) -> str:
    taken = [
        int(path.name.split(".")[0][2:])
        for path in (project / APPROVALS_DIRECTORY).glob("a-*.request.json")
    ]
    return f"a-{max(taken, default=0) + 1:06d}"


def _request_path(project: Path, approval_id: str) -> Path:
    return project / APPROVALS_DIRECTORY / f"{approval_id}.request.json"


def _response(project: Path, approval_id: str) -> ApprovalResponse | None:
    path = project / APPROVALS_DIRECTORY / f"{approval_id}.response.json"
    return load_approval_response(path) if path.is_file() else None


def _requests_of_run(context: _Context) -> list[tuple[str, ApprovalRequest]]:
    """The requests of this run, in the order they were made."""
    ids = [
        str(event.data["approval_id"])
        for event in context.log
        if event.type is EventType.APPROVAL_REQUESTED and event.run_id == context.run_id
    ]
    return [(i, load_approval_request(_request_path(context.project, i))) for i in ids]


def _answered(context: _Context) -> dict[str, str]:
    """The decisions recorded for this run, by approval id."""
    return {
        str(event.data["approval_id"]): str(event.data["decision"])
        for event in context.log
        if event.type is EventType.APPROVAL_ANSWERED and event.run_id == context.run_id
    }


def _ask_for_approval(
    context: _Context,
    stage: Stage,
    *,
    kind: ApprovalKind,
    gate: Gate | None = None,
    artifact: ArtifactMetadata | None = None,
    refused_event_id: str | None = None,
    execution: PlannedExecution | None = None,
) -> NoReturn:
    """Write a request and its event, then pause the run."""
    approval_id = _next_approval_id(context.project)
    request = ApprovalRequest(
        schema_version=ApprovalRequest.SCHEMA_VERSION,
        approval_id=approval_id,
        kind=kind,
        gate=gate,
        artifact_id=None if artifact is None else artifact.artifact_id,
        content_hash=None if artifact is None else artifact.content_hash,
        path=None if artifact is None else artifact.path,
        stage=None if kind is ApprovalKind.ARTIFACT else stage,
        refused_event_id=refused_event_id,
        execution=execution,
        requested_by=SYSTEM_ACTOR,
        requested_at=_timestamp(),
    )
    atomic_write_text(_request_path(context.project, approval_id), request.to_json())
    context.log.append(
        NewEvent(
            actor=SYSTEM_ACTOR,
            type=EventType.APPROVAL_REQUESTED,
            status=EventStatus.OK,
            run_id=context.run_id,
            stage=stage,
            data={
                "approval_id": approval_id,
                "kind": kind.value,
                "gate": None if gate is None else gate.value,
            },
            artifacts=() if artifact is None else (artifact.artifact_id,),
        )
    )
    raise _paused(approval_id)


def _paused(approval_id: str, detail: str = "") -> RunPausedError:
    path = f"{APPROVALS_DIRECTORY}/{approval_id}.request.json"
    return RunPausedError(
        f"the run waits for an answer to {approval_id} ({path}){detail}; answer it, then run "
        "utux run again",
        approval_id,
    )


def _pass_gate(context: _Context, gate: Gate, path: str) -> None:
    """Continue if the current version of the file is approved, else pause."""
    current = current_artifact(context.project, path)
    if current is None:
        raise RunRefusedError(f"there is no version of {path} for the {gate.value} gate")
    # The execution the experiment would run now; an experiment-plan
    # approval covers only the execution its request recorded.
    planned = (
        planned_execution(context.config, context.services.image_digest)
        if gate is Gate.EXPERIMENT_PLAN
        else None
    )
    answered = _answered(context)
    for approval_id, request in reversed(_requests_of_run(context)):
        if request.kind is not ApprovalKind.ARTIFACT or request.gate is not gate:
            continue
        if request.execution != planned:
            break
        decision = answered.get(approval_id)
        if decision is None:
            if request.artifact_id == current.artifact_id:
                raise _paused(approval_id)
            break
        if decision == Decision.REJECT.value:
            # A rejected version is never approved, even if the stage gave the
            # same output again: the gate asks anew.
            break
        response = _response(context.project, approval_id)
        approved = {request.artifact_id}
        if response is not None and response.edited_artifact_id is not None:
            approved.add(response.edited_artifact_id)
        if current.artifact_id in approved:
            return
        break
    _ask_for_approval(
        context,
        current.stage,
        kind=ApprovalKind.ARTIFACT,
        gate=gate,
        artifact=current,
        execution=planned,
    )


def _pause_for_budget(context: _Context, node: str, error: BudgetExhaustedError) -> NoReturn:
    _ask_for_approval(
        context,
        STAGE_OF[node],
        kind=ApprovalKind.BUDGET_EXHAUSTED,
        refused_event_id=error.refused_event_id,
    )


def _budget_raised_after(context: _Context, approval_id: str, stage: Stage | None) -> bool:
    """Whether a setting_changed event for the budget follows the request."""
    keys = {"budget.total_usd"} | ({f"budget.per_stage_usd.{stage.value}"} if stage else set())
    seen_request = False
    for event in context.log:
        if (
            event.type is EventType.APPROVAL_REQUESTED
            and event.data.get("approval_id") == approval_id
        ):
            seen_request = True
        elif (
            seen_request
            and event.type is EventType.SETTING_CHANGED
            and event.data.get("key") in keys
        ):
            return True
    return False


def mark_stale(project: Path, old_artifact_id: str) -> tuple[str, ...]:
    """Mark every artifact built from a version, directly or not, as stale.

    Returns:
        The ids marked, sorted.
    """
    sidecars = {s.artifact_id: s for s in _sidecars(project)}
    marked: set[str] = set()
    frontier = {old_artifact_id}
    while frontier:
        found = {
            sidecar.artifact_id
            for sidecar in sidecars.values()
            if frontier & set(sidecar.input_artifacts) and sidecar.artifact_id not in marked
        }
        marked |= found
        frontier = found
    for artifact_id in marked:
        sidecar = sidecars[artifact_id].model_copy(update={"state": ArtifactState.STALE})
        atomic_write_text(project / ".utux" / "meta" / f"{artifact_id}.json", sidecar.to_json())
    return tuple(sorted(marked))


def _take_edit(context: _Context, request: ApprovalRequest, response: ApprovalResponse) -> None:
    """Record the version a person saved at a gate, and mark what was built before it."""
    assert request.path is not None
    assert request.artifact_id is not None
    edited = context.project / request.path
    actual = _hash_or_none(edited)
    if actual is None or actual != response.edited_content_hash:
        raise ApprovalMismatchError(
            f"{request.path} has the hash {actual}, not the {response.edited_content_hash} "
            f"that the answer to {request.approval_id} names; save the edited file and "
            "answer again"
        )
    old = current_artifact(context.project, request.path)
    assert old is not None
    name, version = str(response.edited_artifact_id).rsplit("-v", 1)
    if name != old.artifact_id.rsplit("-v", 1)[0] or int(version) <= _version(old.artifact_id):
        raise ApprovalMismatchError(
            f"the answer to {request.approval_id} names {response.edited_artifact_id}, which "
            f"is not a later version of {old.artifact_id}"
        )
    sidecar = ArtifactMetadata(
        schema_version=ArtifactMetadata.SCHEMA_VERSION,
        artifact_id=str(response.edited_artifact_id),
        path=request.path,
        stage=old.stage,
        created_by=response.answered_by,
        created_at=response.answered_at,
        input_artifacts=(request.artifact_id,),
        content_hash=actual,
        state=ArtifactState.VALID,
    )
    target = context.project / ".utux" / "meta" / f"{response.edited_artifact_id}.json"
    atomic_write_text(target, sidecar.to_json())
    mark_stale(context.project, request.artifact_id)


def _apply_answers(context: _Context) -> None:
    """Take the answers written since the run paused, and act on them.

    Raises:
        ApprovalMismatchError: An edit does not match its file.
        RunPausedError: A budget pause is approved but the budget was not
            raised after the request.
        RunRejectedError: A request of the run was rejected.
    """
    answered = _answered(context)
    for approval_id, request in _requests_of_run(context):
        if approval_id in answered:
            continue
        response = _response(context.project, approval_id)
        if response is None:
            continue
        check_response_matches_request(request, response, f"{approval_id}.response.json")
        if response.decision is Decision.EDIT:
            _take_edit(context, request, response)
        if (
            request.kind is ApprovalKind.BUDGET_EXHAUSTED
            and response.decision is Decision.APPROVE
            and not _budget_raised_after(context, approval_id, request.stage)
        ):
            raise _paused(
                approval_id,
                ": it is approved, but the budget was not raised; raise budget.total_usd "
                "or the stage's budget in utux.yaml first",
            )
        context.log.append(
            NewEvent(
                actor=response.answered_by,
                type=EventType.APPROVAL_ANSWERED,
                status=EventStatus.OK,
                run_id=context.run_id,
                stage=request.stage,
                data={
                    "approval_id": approval_id,
                    "decision": response.decision.value,
                    "feedback": response.feedback,
                },
            )
        )
        answered[approval_id] = response.decision.value
    # A rejected artifact sends the run back to the stage that made it (see
    # _rejected_gate); a rejected budget or retry pause stops the run.
    unbound = {
        approval_id
        for approval_id, request in _requests_of_run(context)
        if request.kind is not ApprovalKind.ARTIFACT
    }
    rejected = [
        i for i, decision in answered.items() if decision == Decision.REJECT.value and i in unbound
    ]
    if rejected:
        raise RunRejectedError(
            f"{rejected[-1]} was rejected, so the run stops; see its feedback in "
            f"{APPROVALS_DIRECTORY}/{rejected[-1]}.response.json"
        )


# The graph and its checkpoints


@contextmanager
def _saver(project: Path) -> Iterator[SqliteSaver]:
    connection = sqlite3.connect(project / CHECKPOINT_FILE, check_same_thread=False)
    with closing(connection):
        yield SqliteSaver(connection, serde=StrictCheckpointSerializer())


def _graph(context: _Context, saver: SqliteSaver) -> Any:
    graph: StateGraph[RunState, None, RunState, RunState] = StateGraph(RunState)
    for node in NODES:
        graph.add_node(node, _node(context, node))  # type: ignore[call-overload]
    graph.add_edge(START, NODES[0])
    for first, second in itertools.pairwise(NODES):
        graph.add_edge(first, second)
    graph.add_node(CHECK_NODE, _check(context))  # type: ignore[call-overload]
    graph.add_edge(NODES[-1], CHECK_NODE)
    graph.add_conditional_edges(
        CHECK_NODE,
        lambda state: state["route_to"],
        {"implementation": "implementation", "methodology": "methodology", END_ROUTE: END},
    )
    return graph.compile(checkpointer=saver)


def _thread(run_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": run_id}}


def _context(project: Path, services: WorkflowServices, run_id: str, commits: bool) -> _Context:
    config = load_project_config(project / CONFIG_FILE)
    log = EventLog(project / EVENT_LOG_FILE)
    caller = LoggedModelCaller(log, services.provider, config.data_policy, config.budget)
    return _Context(project, services, config, log, caller, run_id, commits)


def _outcome(project: Path, run_id: str, commits: bool, state: RunState) -> RunOutcome:
    records = tuple(_read_records(project, state.get("results", [])))
    return RunOutcome(run_id=run_id, commits=commits, results=records)


def run_workflow(project: Path, services: WorkflowServices) -> RunOutcome:
    """Run the four nodes from the start, under the project lock.

    The run starts with the test commit of ADR-0010 and a `run_started`
    event. If the check fails, `auto` mode refuses to start and `guided` mode
    runs without commits.

    Raises:
        RunRefusedError: `auto` mode, and commits fail. Nothing else is written.
        ProjectLockedError: Another command holds the project lock.
    """
    with writing_command(project, "run"):
        config = load_project_config(project / CONFIG_FILE)
        log = EventLog(project / EVENT_LOG_FILE)
        check = check_commits(project)
        mode = config.oversight.mode
        data: dict[str, Scalar] = {
            "mode": mode.value,
            "commits": check.ok,
            "commit_check_reason": check.reason,
        }
        if not check.ok and mode is OversightMode.AUTO:
            log.append(
                NewEvent(
                    actor=SYSTEM_ACTOR,
                    type=EventType.RUN_STARTED,
                    status=EventStatus.REFUSED,
                    status_reason=check.reason,
                    data=data,
                )
            )
            raise RunRefusedError(
                f"the test commit failed ({check.reason}); in auto mode a run does not start "
                "without commits. Fix git commit signing, or run in guided mode"
            )
        started = log.append(
            NewEvent(
                actor=SYSTEM_ACTOR, type=EventType.RUN_STARTED, status=EventStatus.OK, data=data
            )
        )
        run_id = started.event_id
        context = _context(project, services, run_id, check.ok)
        with _saver(project) as saver:
            app = _graph(context, saver)
            initial: RunState = {"stages": {}, "results": []}
            final = app.invoke(initial, _thread(run_id), durability="sync")
        return _outcome(project, run_id, check.ok, final)


def checkpointed_state(project: Path, run_id: str) -> tuple[dict[str, Any], Any]:
    """The checkpointed state of a run, and the serializer that read it."""
    with _saver(project) as saver:
        checkpoint = saver.get_tuple(_thread(run_id))
        if checkpoint is None:
            raise NoRunToResumeError(f"there is no checkpoint of run {run_id}")
        return dict(checkpoint.checkpoint["channel_values"]), saver.serde


def _threads(project: Path) -> list[str]:
    with closing(sqlite3.connect(project / CHECKPOINT_FILE)) as connection:
        rows = connection.execute("select distinct thread_id from checkpoints").fetchall()
    return [str(row[0]) for row in rows]


def resume_workflow(project: Path, services: WorkflowServices) -> RunOutcome:
    """Resume the last unfinished run from its checkpoint, under the project lock.

    The files win: if an input that a finished node recorded has changed,
    the run restarts at the earliest such node, and a `run_restarted` event
    records it. A file that a finished node wrote and that changed is
    recorded as a new version made by a person (`human:unknown`).

    Raises:
        NoRunToResumeError: There is no checkpoint, or the run is finished.
        CheckpointMismatchError: No `run_started` event matches the
            checkpoint. Nothing is written.
        ProjectLockedError: Another command holds the project lock, or a
            crashed run left it behind.
    """
    with writing_command(project, "run"):
        if not (project / CHECKPOINT_FILE).is_file():
            raise NoRunToResumeError(f"there is no {CHECKPOINT_FILE} to resume from")
        threads = _threads(project)
        log = EventLog(project / EVENT_LOG_FILE)
        started = {
            event.event_id: event
            for event in log
            if event.type is EventType.RUN_STARTED and event.status is EventStatus.OK
        }
        matching = [thread for thread in threads if thread in started]
        if not threads:
            raise NoRunToResumeError(f"{CHECKPOINT_FILE} holds no run")
        if not matching:
            raise CheckpointMismatchError(
                f"{CHECKPOINT_FILE} holds run {', '.join(sorted(threads))}, but no run_started "
                f"event in {EVENT_LOG_FILE} matches it, so it is not a run of this project; "
                "utux does not resume from it. Move the file aside to start a new run"
            )
        run_id = max(matching, key=lambda thread: int(thread.removeprefix("e-")))
        commits = bool(started[run_id].data["commits"])
        context = _context(project, services, run_id, commits)
        with _saver(project) as saver:
            app = _graph(context, saver)
            snapshot = app.get_state(_thread(run_id))
            if not snapshot.next:
                raise NoRunToResumeError(f"run {run_id} is finished; there is nothing to resume")
            log.append(
                NewEvent(
                    actor=SYSTEM_ACTOR,
                    type=EventType.RUN_RESUMED,
                    status=EventStatus.OK,
                    run_id=run_id,
                )
            )
            state: RunState = snapshot.values
            # Answers first, so that an edit at a gate is recorded as the
            # person's version, not as an edit outside utux.
            _apply_answers(context)
            _record_edits(project, state)
            rejection = _rejected_gate(context)
            restart = None if rejection is not None else _restart_point(project, state)
            if rejection is not None:
                approval_id, node = rejection
                position = NODES.index(node)
                _route_after_rejection(context, node)
                kept = {n: state["stages"][n] for n in NODES[:position]}
                as_node = NODES[position - 1] if position else START
                app.update_state(
                    _thread(run_id),
                    {
                        "stages": kept,
                        "route_to": node,
                        "finding": REJECTED_AT_GATE,
                        "feedback": approval_id,
                    },
                    as_node=as_node,
                )
            if restart is not None:
                position, node, path, expected, actual = restart
                log.append(
                    NewEvent(
                        actor=SYSTEM_ACTOR,
                        type=EventType.RUN_RESTARTED,
                        status=EventStatus.OK,
                        run_id=run_id,
                        stage=STAGE_OF[node],
                        data={
                            "changed_path": path,
                            "expected_hash": expected,
                            "actual_hash": actual,
                        },
                    )
                )
                kept = {n: state["stages"][n] for n in NODES[:position]}
                as_node = NODES[position - 1] if position else START
                app.update_state(_thread(run_id), {"stages": kept}, as_node=as_node)
            final = app.invoke(None, _thread(run_id), durability="sync")
        return _outcome(project, run_id, commits, final)


_PRODUCER = {Gate.METHOD: "methodology", Gate.EXPERIMENT_PLAN: "implementation"}
"""The node that makes the file a gate approves."""


def _rejected_gate(context: _Context) -> tuple[str, str] | None:
    """The rejected gate request the run has not yet acted on, and its node.

    A rejection is acted on by running the node again, after which the gate
    asks anew; so a rejection waits as long as it is the latest request of
    its gate.
    """
    answered = _answered(context)
    latest: dict[Gate, str] = {}
    for approval_id, request in _requests_of_run(context):
        if request.kind is ApprovalKind.ARTIFACT and request.gate is not None:
            latest[request.gate] = approval_id
    for gate, approval_id in latest.items():
        if answered.get(approval_id) == Decision.REJECT.value and gate in _PRODUCER:
            return approval_id, _PRODUCER[gate]
    return None


def _route_after_rejection(context: _Context, node: str) -> None:
    """Record the route back after a rejection, within the retry cap, or pause."""
    stage = STAGE_OF[node]
    routes, raises = _routes_so_far(context, stage.value)
    attempt, cap = routes + 1, context.config.workflow.retry_cap + raises
    data: dict[str, Scalar] = {
        "from_stage": stage.value,
        "to_stage": stage.value,
        "finding": REJECTED_AT_GATE,
        "attempt": attempt,
        "cap": cap,
    }
    if attempt > cap:
        refused = context.log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.ROUTE_BACK,
                status=EventStatus.REFUSED,
                status_reason=RETRY_LIMIT,
                run_id=context.run_id,
                stage=stage,
                data=data,
            )
        )
        _ask_for_approval(
            context, stage, kind=ApprovalKind.RETRY_LIMIT, refused_event_id=refused.event_id
        )
    context.log.append(
        NewEvent(
            actor=SYSTEM_ACTOR,
            type=EventType.ROUTE_BACK,
            status=EventStatus.OK,
            run_id=context.run_id,
            stage=stage,
            data=data,
        )
    )


def _record_edits(project: Path, state: RunState) -> None:
    """Record a new version of every output of a finished node that changed."""
    for record in state.get("stages", {}).values():
        for path, recorded in record["outputs"].items():
            current = current_artifact(project, path)
            actual = _hash_or_none(project / path)
            if current is None or actual is None or actual == current.content_hash:
                continue
            if actual == recorded:
                continue
            name = current.artifact_id.rsplit("-v", 1)[0]
            _record_artifact(
                project, None, name, path, current.stage, EDITED_BY, (current.artifact_id,)
            )


def _restart_point(
    project: Path, state: RunState
) -> tuple[int, str, str, str | None, str | None] | None:
    """The earliest finished node whose inputs changed, and the first change."""
    stages = state.get("stages", {})
    for position, node in enumerate(NODES):
        record = stages.get(node)
        if record is None:
            return None
        now = _current_inputs(project, node, state)
        for path in sorted(set(record["inputs"]) | set(now)):
            expected = record["inputs"].get(path)
            actual = now.get(path)
            if expected != actual:
                return position, node, path, expected, actual
    return None
