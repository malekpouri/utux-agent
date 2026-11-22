"""`utux cache`: the machine-wide cache of API responses and source texts."""

import typer

from utux.errors import UtuxError
from utux.sources.cache import ContentCache, cache_directory

cache_app = typer.Typer(help="The machine-wide cache of API responses and source texts.")


@cache_app.callback()
def cache_root() -> None:
    """The machine-wide cache of API responses and source texts."""


@cache_app.command("clear")
def clear() -> None:
    """Remove every entry of the cache, under the cache's lock."""
    directory = cache_directory()
    try:
        removed = ContentCache(directory).clear()
    except UtuxError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    entries = f"{removed} {'entry' if removed == 1 else 'entries'}"
    typer.echo(f"Removed {entries} from the cache in {directory}.")
