"""Root command of the `utux` CLI."""

import getpass
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from utux import __version__
from utux.budget.accounting import CostReport, CostTotals, project_cost_report, remaining, usd
from utux.core.approvals import answer_approval
from utux.core.services import services_for_run
from utux.core.status import ProjectStatus, RunState, project_status
from utux.core.workflow import run_or_resume, run_stage
from utux.errors import (
    ApprovalAnswerError,
    RunPausedError,
    RunRejectedError,
    SchemaExportError,
    UtuxError,
)
from utux.executors.image import DIGEST_FILE, build_image
from utux.schemas.approval import ApprovalKind, Decision, ExecutionLimits
from utux.schemas.common import Tier
from utux.schemas.export import export_json_schemas
from utux.schemas.project_config import DataPolicy
from utux.workspace.layout import EVENT_LOG_FILE
from utux.workspace.model_calls import ping_model
from utux.workspace.project import init_project
from utux.workspace.validation import require_valid, validate_project
from utux.workspace.writer import LOCK_FILE, LockState, repair_project_log, unlock_project

app = typer.Typer(
    name="utux",
    help="utux Agent: reliable computational research, from idea to reviewed manuscript.",
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"utux {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the package version and exit.",
        ),
    ] = False,
) -> None:
    """Run the root command; print help when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("init")
def init(
    directory: Annotated[
        Path, typer.Argument(help="Directory of the new project. Empty, or not yet there.")
    ],
    budget_usd: Annotated[
        float, typer.Option("--budget-usd", help="Total budget of the project in US dollars.")
    ],
    data_policy: Annotated[
        DataPolicy,
        typer.Option("--data-policy", help="What may be sent to external services."),
    ],
    profile: Annotated[
        str | None, typer.Option("--profile", help="Profile. Default: the schema's default.")
    ] = None,
    domain_pack: Annotated[
        str | None,
        typer.Option("--domain-pack", help="Domain pack. Default: the schema's default."),
    ] = None,
) -> None:
    """Create a new project in DIRECTORY."""
    try:
        project = init_project(
            directory,
            budget_usd=budget_usd,
            data_policy=data_policy,
            profile=profile,
            domain_pack=domain_pack,
        )
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Created project in {project}")


@app.command("validate")
def validate(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
    json_output: Annotated[
        bool, typer.Option("--json", help="Print a machine-readable JSON report.")
    ] = False,
) -> None:
    """Check every contract file of a project and report every problem."""
    report = validate_project(directory)
    if json_output:
        typer.echo(report.to_json(), nl=False)
    else:
        for problem in report.problems:
            typer.echo(problem.message)
        for warning in report.warnings:
            typer.echo(f"warning: {warning.message}")
        if report.newer_schema_version:
            typer.echo(
                "This project was written by a newer version of utux; upgrade utux to work with it."
            )
        if report.valid:
            count = len(report.warnings)
            warnings = f", {count} {'warning' if count == 1 else 'warnings'}" if count else ""
            typer.echo(
                f"The project is valid ({report.files_checked} contract files checked{warnings})."
            )
        else:
            count = len(report.problems)
            typer.echo(f"{count} {'problem' if count == 1 else 'problems'} found.")
    if not report.valid:
        raise typer.Exit(code=1)


log_app = typer.Typer(help="Work with the event log of a project.")
app.add_typer(log_app, name="log")


@log_app.callback()
def log_root() -> None:
    """Work with the event log of a project."""


@log_app.command("repair")
def log_repair(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
) -> None:
    """Save an incomplete last line of the event log aside and record the repair."""
    try:
        repairs, changes = repair_project_log(directory)
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    for event in changes.events:
        typer.echo(f"Recorded the change of {event.data['key']} in utux.yaml as {event.event_id}.")
    if not repairs:
        typer.echo(f"nothing to repair: the last line of {EVENT_LOG_FILE} is complete")
        return
    for repair in repairs:
        if repair.interrupted:
            typer.echo(
                f"Completed an interrupted repair: recorded {repair.fragment_file} "
                f"({repair.fragment_bytes} bytes) as {repair.event.event_id}."
            )
        else:
            typer.echo(
                f"Saved the incomplete last line ({repair.fragment_bytes} bytes) "
                f"to {repair.fragment_file}."
            )
            typer.echo(f"The log now ends with {repair.event.event_id}, which records the repair.")


model_app = typer.Typer(help="Work with the models of a project.")
app.add_typer(model_app, name="model")


@model_app.callback()
def model_root() -> None:
    """Work with the models of a project."""


@model_app.command("ping")
def model_ping(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
    tier: Annotated[Tier, typer.Option("--tier", help="The tier whose model is asked.")] = (
        Tier.LIGHT
    ),
) -> None:
    """Send a fixed short prompt to the model of a tier and print tokens and cost."""
    try:
        ping = ping_model(directory, tier)
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    usage = ping.response.usage
    cost = (
        "cost unknown: the provider reported none"
        if ping.response.cost_usd is None
        else f"cost {_decimal(ping.response.cost_usd)} USD"
    )
    typer.echo(
        f"{ping.response.model} answered through {ping.provider}: "
        f"{_count(usage.tokens_in, 'token')} in, {_count(usage.tokens_out, 'token')} out, {cost}"
    )


def _count(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def _decimal(value: float) -> str:
    """Write a cost without an exponent, as precise as the float was given."""
    return format(Decimal(repr(value)), "f")


@app.command("cost")
def cost(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Print the cost of a project against its budget, per stage and per actor."""
    try:
        report = project_cost_report(directory)
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    if as_json:
        typer.echo(json.dumps(report.to_json(), indent=2))
        return
    for line in _cost_lines(report):
        typer.echo(line)


def _cost_lines(report: CostReport) -> list[str]:
    total = report.summary.total
    limit = usd(report.budget.total_usd)
    left = (
        "exhausted"
        if total.known_cost_usd >= limit
        else f"{_money(remaining(total, limit))} USD left"
    )
    lines = [
        f"Known cost: {_money(total.known_cost_usd)} USD of a budget of {_money(limit)} USD "
        f"({left})",
        f"Calls: {total.calls} made, {total.refused_calls} refused",
    ]
    if total.local_unbilled_calls:
        lines.append(f"Local, not billed: {_count(total.local_unbilled_calls, 'call')}")
    if total.failed_unbilled_calls:
        lines.append(
            f"Failed, not billed: {_count(total.failed_unbilled_calls, 'call')} "
            "(assumed: the provider rejected them)"
        )
    if total.unknown_cost_calls:
        lines.append(
            f"Unknown cost: {_count(total.unknown_cost_calls, 'call')} to an external provider "
            "reported no cost"
        )
        lines.append(
            "The budget cannot be fully enforced while calls of unknown cost exist: "
            "only the known cost is compared with the budget."
        )
    lines += ["", "Per stage:"]
    stages = report.stages()
    lines += [
        f"  {'no stage' if stage is None else stage.value}: {_totals(totals, stage_limit)}"
        for stage, totals, stage_limit in stages
    ] or ["  no calls"]
    lines += ["", "Per actor:"]
    lines += [f"  {actor}: {_totals(totals, None)}" for actor, totals in report.actors()] or [
        "  no calls"
    ]
    return lines


def _totals(totals: CostTotals, limit: Decimal | None) -> str:
    parts = [f"{_money(totals.known_cost_usd)} USD"]
    if limit is not None:
        parts[0] += f" of a budget of {_money(limit)} USD"
        if totals.known_cost_usd >= limit:
            parts.append("exhausted")
    parts.append(_count(totals.calls, "call"))
    if totals.local_unbilled_calls:
        parts.append(f"{totals.local_unbilled_calls} local, not billed")
    if totals.failed_unbilled_calls:
        parts.append(f"{totals.failed_unbilled_calls} failed, not billed")
    if totals.unknown_cost_calls:
        parts.append(f"{totals.unknown_cost_calls} of unknown cost")
    if totals.refused_calls:
        parts.append(f"{totals.refused_calls} refused")
    return ", ".join(parts)


def _money(amount: Decimal) -> str:
    """Write an amount without an exponent or trailing zeros."""
    return format(amount.normalize(), "f")


schema_app = typer.Typer(help="Work with the schemas of the file contracts.")
app.add_typer(schema_app, name="schema")


@schema_app.callback()
def schema_root() -> None:
    """Work with the schemas of the file contracts."""


@schema_app.command("export")
def schema_export(
    directory: Annotated[
        Path, typer.Argument(help="Directory to write the JSON Schema files into.")
    ],
) -> None:
    """Write one JSON Schema file per file contract into DIRECTORY."""
    try:
        written = export_json_schemas(directory)
    except SchemaExportError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    for path in written:
        typer.echo(str(path))


def main() -> None:
    """Entry point of the `utux` console script."""
    app()


image_app = typer.Typer(help="Build the container image of a pack.")
app.add_typer(image_app, name="image")


@image_app.callback()
def image_root() -> None:
    """Build the container image of a pack."""


@image_app.command("build")
def image_build(
    directory: Annotated[
        Path,
        typer.Argument(help="The pack's image directory. Default: packs/generic/image."),
    ] = Path("packs/generic/image"),
    docker: Annotated[str, typer.Option("--docker", help="The docker command.")] = "docker",
) -> None:
    """Build a pack's image and record its id in digest.txt beside the Dockerfile."""
    try:
        image_id = build_image(directory, docker=docker)
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Built {image_id}")
    typer.echo(f"Recorded it in {directory / DIGEST_FILE}; commit that file.")


# Runs (M1-14). Each command refuses a project that fails utux validate.


def _fail(error: UtuxError, hint: str | None = None) -> typer.Exit:
    typer.echo(f"error: {error}", err=True)
    if hint is not None:
        typer.echo(hint, err=True)
    return typer.Exit(code=1)


def _spend(directory: Path) -> str:
    return _cost_lines(project_cost_report(directory))[0]


@app.command("run")
def run(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
    from_stage: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="Start a new run at this stage: methodology, implementation or experiment.",
        ),
    ] = None,
    to_stage: Annotated[
        str | None,
        typer.Option("--to", help="Stop after this stage; a later utux run continues."),
    ] = None,
) -> None:
    """Resume the last run if it is unfinished, else start a new one."""
    try:
        require_valid(directory, "run")
        start = None if from_stage is None else run_stage(from_stage, "--from")
        stop = None if to_stage is None else run_stage(to_stage, "--to")
        outcome = run_or_resume(
            directory, services_for_run(directory), from_stage=start, to_stage=stop
        )
    except RunPausedError as paused:
        typer.echo(f"Run paused: {paused}.")
        typer.echo(
            f"Answer it with: utux approve {directory} {paused.approval_id} "
            "approve|reject|edit [--feedback TEXT]"
        )
        typer.echo(_spend(directory))
        return
    except RunRejectedError as error:
        raise _fail(
            error, f"Start a new run with: utux run {directory} --from methodology"
        ) from error
    except UtuxError as error:
        raise _fail(error) from error
    if outcome.finished:
        records = _count(len(outcome.results), "result record")
        typer.echo(f"Run {outcome.run_id} finished, with {records}.")
    else:
        typer.echo(
            f"Run {outcome.run_id} stopped after {to_stage}, as --to asked; "
            f"utux run {directory} continues it."
        )
    typer.echo(_spend(directory))


def _approve_arguments(first: str, second: str, third: str | None) -> tuple[Path, str, Decision]:
    directory, approval_id, decision = (
        (Path(), first, second) if third is None else (Path(first), second, third)
    )
    try:
        return directory, approval_id, Decision(decision)
    except ValueError:
        raise typer.BadParameter(
            f"{decision!r} is not a decision; give approve, reject or edit"
        ) from None


@app.command("approve")
def approve(
    first: Annotated[str, typer.Argument(metavar="[DIR] APPROVAL_ID", show_default=False)],
    second: Annotated[str, typer.Argument(metavar="", show_default=False)],
    third: Annotated[
        str | None, typer.Argument(metavar="approve|reject|edit", show_default=False)
    ] = None,
    feedback: Annotated[
        str | None, typer.Option("--feedback", help="Your remarks; required for reject.")
    ] = None,
    by: Annotated[
        str | None,
        typer.Option("--by", help="Your id, recorded as human:<id>. Default: your login name."),
    ] = None,
) -> None:
    """Answer an approval request: approve, reject (with feedback) or edit.

    For edit, save your change to the file first; the answer names the saved
    file as the next version, which the run takes when it resumes.
    """
    directory, approval_id, decision = _approve_arguments(first, second, third)
    try:
        require_valid(directory, "approve")
        person = by
        if person is None:
            try:
                person = getpass.getuser()
            except (OSError, KeyError) as error:
                raise ApprovalAnswerError(
                    "your login name cannot be read; give your id with --by"
                ) from error
        answer = answer_approval(directory, approval_id, decision, person=person, feedback=feedback)
    except UtuxError as error:
        raise _fail(error) from error
    response = answer.response
    typer.echo(f"Wrote {answer.path}: {response.decision.value} by {response.answered_by}.")
    if response.edited_artifact_id is not None:
        typer.echo(
            f"It names your saved file as {response.edited_artifact_id} "
            f"({response.edited_content_hash})."
        )
    typer.echo(f"utux run {directory} takes the answer and continues the run.")


def _limits(limits: ExecutionLimits) -> str:
    def limit(name: str, value: float | None, unit: str = "") -> str:
        return f"{name} not set" if value is None else f"{name} {value:g}{unit}"

    return ", ".join(
        [
            limit("cpus", limits.cpus),
            limit("memory", limits.memory_mb, " MB"),
            limit("gpus", limits.gpus),
            limit("disk", limits.disk_mb, " MB"),
            limit("processes", limits.max_processes),
            limit("output", limits.output_mb, " MB"),
            limit("timeout", limits.timeout_seconds, " s"),
        ]
    )


_STATE_TEXT = {
    RunState.RUNNING: "running",
    RunState.PAUSED: "paused at {waiting}, waiting for an answer",
    RunState.ANSWERED: "paused at {waiting}, which is answered; utux run continues",
    RunState.STOPPED: (
        "stopped: {waiting} was rejected; start a new run with utux run --from methodology"
    ),
    RunState.UNFINISHED: "not finished; utux run continues it",
    RunState.FINISHED: "finished",
}


def _lock_line(lock: LockState) -> str:
    holder = lock.holder
    if not lock.exists:
        return "Lock: not held"
    if holder is None:
        return f"Lock: {LOCK_FILE} exists but cannot be read"
    if lock.running is None:
        return f"Lock: held by {holder.describe()}; that host cannot be checked from here"
    if not lock.running:
        return (
            f"Lock: left by {holder.describe()}, which is no longer running; check the "
            "project with utux validate, then remove the lock with utux unlock"
        )
    if holder.command == "run":
        return f"Lock: held by the run, {holder.describe()}"
    return f"Lock: held by {holder.describe()}"


def _status_lines(status: ProjectStatus) -> list[str]:
    run = status.run
    if run is None:
        lines = ["No run yet."]
    else:
        commits = "on" if run.commits else "off"
        state = _STATE_TEXT[run.state].format(waiting=run.waiting_for)
        if run.last_error is not None:
            state += f" (its last event is an error: {run.last_error})"
        lines = [f"Run {run.run_id} ({run.mode} mode, commits {commits}): {state}"]
        if run.node is None or run.stage is None:
            lines.append("Stage: none started")
        else:
            ended = "finished" if run.node_finished else "started, not finished"
            lines.append(f"Stage: {run.stage.value} (node {run.node}, {ended})")
    lines.append("Pending approvals:" if status.pending else "Pending approvals: none")
    for pending in status.pending:
        request = pending.request
        answered = " (answered; taken when the run resumes)" if pending.answered else ""
        if request.kind is ApprovalKind.ARTIFACT:
            assert request.gate is not None
            lines.append(
                f"  {pending.approval_id}: {request.gate.value} gate, {request.path} "
                f"({request.artifact_id}, {request.content_hash}){answered}"
            )
        else:
            stage = request.stage.value if request.stage is not None else "none"
            lines.append(
                f"  {pending.approval_id}: {request.kind.value}, stage {stage}, refused event "
                f"{request.refused_event_id}{answered}"
            )
        if request.execution is not None:
            execution = request.execution
            lines += [
                f"    command: {' '.join(execution.command)}",
                f"    image: {execution.image_digest}",
                f"    read-only paths: {', '.join(execution.read_only_paths) or 'none'}",
                f"    limits: {_limits(execution.limits)}",
            ]
    last = status.last_execution
    if last is not None:
        ended = "no exit status" if last.exit_status is None else f"exit status {last.exit_status}"
        stopped = "" if last.stopped_by is None else f", stopped by {last.stopped_by.value}"
        lines.append(f"Last execution: {last.run_id}, {ended}{stopped}")
        note = last.note()
        if note is not None:
            lines.append(f"  Note: {note}.")
    lines.append(_cost_lines(status.cost)[0])
    lines.append(_lock_line(status.lock))
    return lines


@app.command("status")
def status(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
) -> None:
    """Show the last run, pending approvals, spend against budget and the lock."""
    try:
        require_valid(directory, "status")
        report = project_status(directory)
    except UtuxError as error:
        raise _fail(error) from error
    for line in _status_lines(report):
        typer.echo(line)


@app.command("unlock")
def unlock(
    directory: Annotated[
        Path, typer.Argument(help="The project directory. Default: the current directory.")
    ] = Path(),
) -> None:
    """Remove a project lock left by a process on this host that is no longer running."""
    try:
        require_valid(directory, "unlock")
        event = unlock_project(directory)
    except UtuxError as error:
        raise _fail(error) from error
    data = event.data
    typer.echo(
        f"Removed {LOCK_FILE}, left by process {data['pid']} on {data['host']} "
        f"({data['command']}, since {data['started_at']}); recorded as {event.event_id}."
    )
