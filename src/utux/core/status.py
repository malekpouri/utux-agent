"""What `utux status` reports (M1-14).

Everything is read from the project's files: the event log, the approval
requests and responses, the run manifests, the checkpoint and the lock.
Nothing is written and the project lock is not taken, so the status can be
read while a run holds it.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from utux.budget.accounting import CostReport, project_cost_report
from utux.core.workflow import (
    APPROVALS_DIRECTORY,
    CHECKPOINT_FILE,
    END_ROUTE,
    checkpointed_state,
)
from utux.errors import NoRunToResumeError
from utux.events.log import EventLog
from utux.schemas.approval import (
    ApprovalKind,
    ApprovalRequest,
    Decision,
    load_approval_request,
)
from utux.schemas.common import LimitKind, Stage
from utux.schemas.event import Event, EventStatus, EventType, event_number
from utux.schemas.run_manifest import load_run_manifest
from utux.workspace.layout import EVENT_LOG_FILE
from utux.workspace.writer import LockState, read_lock

_RUN_DIRECTORY = re.compile(r"^r([0-9]+)$")

KILLED_EXIT_STATUS = 137
"""128 + 9: the process was killed with SIGKILL."""


class RunState(StrEnum):
    """Where the last run is."""

    RUNNING = "running"
    PAUSED = "paused"
    ANSWERED = "answered"
    STOPPED = "stopped"
    UNFINISHED = "unfinished"
    FINISHED = "finished"


@dataclass(frozen=True)
class PendingApproval:
    """A request the run has not yet acted on.

    Attributes:
        approval_id: The request.
        request: Its content.
        answered: Whether a response is written; the run takes it when it
            resumes.
    """

    approval_id: str
    request: ApprovalRequest
    answered: bool


@dataclass(frozen=True)
class RunStatus:
    """The last run of the project.

    Attributes:
        run_id: The run, the id of its `run_started` event.
        mode: Its oversight mode.
        commits: Whether its stages are committed.
        state: Where it is.
        waiting_for: The request a paused or stopped run is about.
        node: The node that started last, or None.
        stage: That node's stage.
        node_finished: Whether that node finished.
        last_error: The reason of an `error` event that is the run's last
            event, or None.
    """

    run_id: str
    mode: str
    commits: bool
    state: RunState
    waiting_for: str | None
    node: str | None
    stage: Stage | None
    node_finished: bool
    last_error: str | None


@dataclass(frozen=True)
class LastExecution:
    """The last execution run of the project, from its manifest.

    Attributes:
        run_id: The execution run, `rNNN`.
        exit_status: Its exit status, or None.
        stopped_by: The limit that stopped it, as Docker reported it, or None.
    """

    run_id: str
    exit_status: int | None
    stopped_by: LimitKind | None

    def note(self) -> str | None:
        """A note for a person on how the run ended, or None.

        Exit status 137 without a reported limit is often the memory limit,
        but only Docker's report names a limit; the note does not.
        """
        if self.exit_status == KILLED_EXIT_STATUS and self.stopped_by is None:
            return (
                "exit status 137 means the process was killed; this is often the memory "
                "limit, but Docker did not report a limit, so none is recorded"
            )
        return None


@dataclass(frozen=True)
class ProjectStatus:
    """What `utux status` shows.

    Attributes:
        run: The last run, or None if there is none.
        pending: Requests the runs have not acted on, by id.
        last_execution: The last execution run, or None.
        cost: Spend against the budget.
        lock: The project lock.
    """

    run: RunStatus | None
    pending: tuple[PendingApproval, ...]
    last_execution: LastExecution | None
    cost: CostReport
    lock: LockState


def _pending(project: Path, events: list[Event]) -> tuple[PendingApproval, ...]:
    taken = {str(e.data["approval_id"]) for e in events if e.type is EventType.APPROVAL_ANSWERED}
    pending = []
    for path in sorted((project / APPROVALS_DIRECTORY).glob("a-*.request.json")):
        approval_id = path.name.removesuffix(".request.json")
        if approval_id in taken:
            continue
        answered = (path.parent / f"{approval_id}.response.json").is_file()
        pending.append(PendingApproval(approval_id, load_approval_request(path), answered))
    return tuple(pending)


def _last_execution(project: Path) -> LastExecution | None:
    runs = [
        (int(found.group(1)), path)
        for path in (project / "runs").glob("r*")
        if (found := _RUN_DIRECTORY.match(path.name)) and (path / "manifest.json").is_file()
    ]
    if not runs:
        return None
    _, path = max(runs)
    manifest = load_run_manifest(path / "manifest.json")
    return LastExecution(manifest.run_id, manifest.exit_status, manifest.stopped_by)


def _finished(project: Path, run_id: str) -> bool:
    if not (project / CHECKPOINT_FILE).is_file():
        return False
    try:
        values, _ = checkpointed_state(project, run_id)
    except NoRunToResumeError:
        return False
    return bool(values.get("route_to") == END_ROUTE)


def _run(
    project: Path, events: list[Event], pending: tuple[PendingApproval, ...], lock: LockState
) -> RunStatus | None:
    started = [e for e in events if e.type is EventType.RUN_STARTED and e.status is EventStatus.OK]
    if not started:
        return None
    run = started[-1]
    own = [e for e in events if e.run_id == run.event_id]
    starts = [e for e in own if e.type is EventType.STAGE_START]
    node = str(starts[-1].data["node"]) if starts else None
    node_finished = bool(starts) and any(
        e.type is EventType.STAGE_END
        and e.data["node"] == node
        and event_number(e.event_id) > event_number(starts[-1].event_id)
        for e in own
    )
    asked = {str(e.data["approval_id"]) for e in own if e.type is EventType.APPROVAL_REQUESTED}
    mine = [p for p in pending if p.approval_id in asked]
    rejected = [
        str(e.data["approval_id"])
        for e in own
        if e.type is EventType.APPROVAL_ANSWERED and e.data["decision"] == Decision.REJECT.value
    ]
    unbound_rejected = [
        approval_id
        for approval_id in rejected
        if (project / APPROVALS_DIRECTORY / f"{approval_id}.request.json").is_file()
        and load_approval_request(
            project / APPROVALS_DIRECTORY / f"{approval_id}.request.json"
        ).kind
        is not ApprovalKind.ARTIFACT
    ]
    holder = lock.holder
    waiting_for: str | None = None
    if lock.running and holder is not None and holder.command == "run":
        state = RunState.RUNNING
    elif [p for p in mine if not p.answered]:
        state, waiting_for = RunState.PAUSED, next(p.approval_id for p in mine if not p.answered)
    elif mine:
        state, waiting_for = RunState.ANSWERED, mine[0].approval_id
    elif unbound_rejected:
        state, waiting_for = RunState.STOPPED, unbound_rejected[-1]
    elif _finished(project, run.event_id):
        state = RunState.FINISHED
    else:
        state = RunState.UNFINISHED
    last = own[-1] if own else None
    last_error = (
        last.status_reason
        if last is not None and last.type is EventType.ERROR and state is RunState.UNFINISHED
        else None
    )
    return RunStatus(
        run_id=run.event_id,
        mode=str(run.data["mode"]),
        commits=bool(run.data["commits"]),
        state=state,
        waiting_for=waiting_for,
        node=node,
        stage=starts[-1].stage if starts else None,
        node_finished=node_finished,
        last_error=last_error,
    )


def project_status(project: Path) -> ProjectStatus:
    """Read the status of a project. Nothing is written.

    Raises:
        ContractValidationError: A file it reads is not valid.
        EventLogCorruptError: The event log cannot be read.
    """
    events = list(EventLog(project / EVENT_LOG_FILE))
    lock = read_lock(project)
    pending = _pending(project, events)
    return ProjectStatus(
        run=_run(project, events, pending, lock),
        pending=pending,
        last_execution=_last_execution(project),
        cost=project_cost_report(project),
        lock=lock,
    )
