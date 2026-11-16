"""Root command of the `utux` CLI."""

from pathlib import Path
from typing import Annotated

import typer

from utux import __version__
from utux.errors import SchemaExportError
from utux.schemas.export import export_json_schemas

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
