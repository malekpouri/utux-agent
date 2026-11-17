"""Root command of the `utux` CLI."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from utux import __version__
from utux.budget.accounting import CostReport, CostTotals, project_cost_report, remaining, usd
from utux.errors import SchemaExportError, UtuxError
from utux.events.log import repair_log
from utux.schemas.common import Tier
from utux.schemas.export import export_json_schemas
from utux.schemas.project_config import DataPolicy
from utux.workspace.layout import EVENT_LOG_FILE
from utux.workspace.model_calls import ping_model
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project

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
        if report.newer_schema_version:
            typer.echo(
                "This project was written by a newer version of utux; upgrade utux to work with it."
            )
        if report.valid:
            typer.echo(f"The project is valid ({report.files_checked} contract files checked).")
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
        repairs = repair_log(directory / EVENT_LOG_FILE)
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
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
