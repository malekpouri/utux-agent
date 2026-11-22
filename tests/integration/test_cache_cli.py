"""M2-03: `utux cache clear`. The cache directory is a temporary one."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.sources.cache import ContentCache

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def test_cache_clear_empties_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UTUX_CACHE_DIR", str(tmp_path))
    ContentCache(tmp_path).put_text(b"Synthetic text.")
    result = runner.invoke(app, ["cache", "clear"])
    assert result.exit_code == 0, result.output
    assert "1 entry" in result.output
    assert str(tmp_path) in result.output
    help_result = runner.invoke(app, ["cache", "clear", "--help"])
    assert help_result.exit_code == 0
