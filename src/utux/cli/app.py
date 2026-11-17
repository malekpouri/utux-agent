"""Root command of the `utux` CLI."""

from pathlib import Path
from typing import Annotated

import typer

from utux import __version__
from utux.errors import SchemaExportError, UtuxError
from utux.events.log import repair_log
from utux.schemas.export import export_json_schemas
from utux.schemas.project_config import DataPolicy
from utux.workspace.layout import EVENT_LOG_FILE
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
