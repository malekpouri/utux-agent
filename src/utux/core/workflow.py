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

import itertools
import os
import platform
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from utux.core.checkpoints import StrictCheckpointSerializer
from utux.errors import (
    CheckpointMismatchError,
    ModelProviderConfigError,
    NoRunToResumeError,
    RunRefusedError,
)
from utux.events.log import EventLog
from utux.interfaces.executor import ExecutionStep, Executor, ResourceLimits
from utux.interfaces.model_provider import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
)
from utux.schemas.artifact_metadata import ArtifactMetadata, ArtifactState
from utux.schemas.common import Scalar, Stage, Tier
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.schemas.json_io import parse_json
from utux.schemas.project_config import OversightMode, ProjectConfig, load_project_config
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import Container, GitState, Hardware, RunManifest
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

# The prompts of the skeleton. Versioned prompts and real agents are M1-13.
PROMPT_VERSION = "skeleton@1"
_AGENTS = {"methodology": "agent:methodologist", "implementation": "agent:implementer"}
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
    """The graph state. Only ids, relative paths, hashes and node names."""

    stages: dict[str, StageRecord]
    experiment_run: str
    results: list[str]


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


def _ask(context: _Context, node: str, prompt: str) -> str:
    role = _AGENTS[node].removeprefix("agent:")
    tier = context.config.models.roles.get(role, Tier.STANDARD)
    model = context.config.models.tiers.get(tier)
    if model is None:
        raise ModelProviderConfigError(
            f"no model is configured for the tier {tier.value} of the role {role} in "
            f"{CONFIG_FILE} (models.tiers)"
        )
    response = context.caller.call(
        ModelRequest(
            model=model,
            messages=(Message(role=MessageRole.USER, content=prompt),),
            timeout_seconds=300.0,
        ),
        actor=_AGENTS[node],
        prompt_version=PROMPT_VERSION,
        stage=STAGE_OF[node],
        run_id=context.run_id,
    )
    return response.content


def _methodology(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    inputs = {p: hash_file(project / p) for p in _question_files(project)}
    question = "\n\n".join((project / p).read_text(encoding="utf-8") for p in inputs)
    method = _ask(context, "methodology", "Write the method for this question.\n\n" + question)
    atomic_write_text(staging.path("method.md"), method)
    artifact = _record_artifact(
        project, staging, "method", "method.md", Stage.METHODOLOGY, _AGENTS["methodology"], ()
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
    code = _ask(context, "implementation", "Write the code for this method.\n\n" + method)
    atomic_write_text(staging.path("code/main.py"), code)
    artifact = _record_artifact(
        project,
        staging,
        "code",
        "code/main.py",
        Stage.IMPLEMENTATION,
        _AGENTS["implementation"],
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


def _experiment(
    context: _Context, state: RunState, staging: _Staging
) -> tuple[StageRecord, RunState]:
    project = context.project
    services = context.services
    inputs = {"code/main.py": hash_file(project / "code/main.py")}
    run = _next_run_id(project)
    resources = context.config.resources
    step = ExecutionStep(
        run_id=run,
        command=("python", "code/main.py"),
        image_digest=services.image_digest,
        read_only_paths=("code", "inputs"),
        # The container writes into the staging area; the outputs are moved
        # to runs/<run>/outputs when the node completes.
        output_directory=f"{staging.relative}/runs/{run}/outputs",
        limits=ResourceLimits(
            cpus=resources.cpus,
            memory_mb=resources.memory_mb,
            gpus=resources.gpus,
            disk_mb=resources.disk_mb,
            max_processes=resources.max_processes,
            output_mb=resources.output_mb,
        ),
        timeout_seconds=float(resources.wall_clock_seconds or _DEFAULT_TIMEOUT_SECONDS),
        environment={},
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
    lines = [
        "# Results",
        "",
        f"Run {run}. Every number below is a result record in results.jsonl.",
        "",
    ]
    if not records:
        lines.append(f"No result records were made for run {run}.")
    for r in records:
        where = r.dataset + (f" ({r.split})" if r.split else "")
        model = f", model {r.model}" if r.model else ""
        lines.append(f"- {r.metric} on {where}{model}: {r.value!r} {r.unit} [{r.id}]")
    atomic_write_text(staging.path("results.md"), "\n".join(lines) + "\n")
    metrics = f"runs/{run}/outputs/{METRICS_FILE}"
    artifact = _record_artifact(
        project,
        staging,
        "results",
        "results.md",
        Stage.EXPERIMENT,
        SYSTEM_ACTOR,
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
    graph.add_edge(NODES[-1], END)
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
            _record_edits(project, state)
            restart = _restart_point(project, state)
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
